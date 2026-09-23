# パイプライン構築時に踏んだ落とし穴集（Gmsh → Elmer → Garfield++ → ROOT/Python）

このパイプラインを拡張・改修する際に再度ハマりやすい、実際に踏んだバグ・
仕様上の注意点をまとめる。「一見動いているように見えて実は違う」系のものが
多いので、同種の変更をする前に目を通すこと。物理的な調査（GEM1→GEM2透過率
問題そのもの）は`docs/debugging_notes.md`、実行手順は`docs/reference.md`参照。

## Gmsh (OCC) ジオメトリ

1. **接触ボリュームは`gmsh.model.occ.fragment()`が必須。** 個別に`cut()`しただけ
   では幾何学的に接しているだけでメッシュはconformalにならない（ElmerGridが
   "mesh is non-conforming"と警告）。境界を共有する全ボリュームを
   `synchronize()`/メッシュ生成前に`fragment()`し、物理グループのタグを
   fragment結果のマップから付け直す（`gem_unit_cell.py`, `*_field_model.py`参照）。

2. **孔の空洞には明示的なGasボリュームが必要。** Cu/誘電体ブロックから孔を
   `cut()`でくり抜くだけだと、その空間は本当に「何もない」空洞になり、Gmshの
   メッシャーは警告なく無視する（ログに"Found void region"と出るだけ）。
   カット用と同じ形状のソリッドをもう一つ作り、`fragment()`とGas物理グループに
   含める必要がある（`gem_unit_cell.build_hole_gas_volumes`）。

3. **単一の六角ユニットセルには、横方向に拡散した電子が入れる「隣の孔」が
   存在しない。** 単位セル1個だけだと、雪崩で生成された二次電子が周辺に拡散
   したときに行き場がなく、ほぼ全てホール壁に吸収される（issue #2で発見）。
   `gem_unit_cell.hole_centers_tiled` + `TripleGemTestConfig.n_cells_x/y`で
   3x3タイル化すると軽減できるが、完全な解決ではない
   （`docs/debugging_notes.md`参照。タイル化後も約16%は依然として
   境界アーティファクトとして残っていることが後日判明した）。

## Elmerメッシュ変換・ソルブ

4. **ElmerGridは境界（および場合によってはボリューム）の物理グループIDを
   振り直す。** Gmsh側で付けたタグはそのままでは使えず、`.sif`の
   `Target Bodies`/`Target Boundaries`は`ElmerGrid`実行後に生成される
   `mesh.names`から読み取ったIDを使う必要がある（`elmer/write_sif.py`は
   ElmerGridの**後**に実行する）。

5. **Elmer向けメッシュは2次（10節点）四面体が必須。** デフォルトの
   `gmsh.model.mesh.generate(3)`は1次（4節点）を作るので、`generate(3)`の
   後に`gmsh.model.mesh.setOrder(2)`を呼ぶ。呼び忘れると
   `ComponentElmer::Initialise`が"Read 4 node indices for element0
   (expected 10)"で失敗する。

6. **`Simulation`ブロックに`Output File = "<name>.result"`が必要。** これが
   ないと`.vtu`（ParaView用）だけが出力され、`ComponentElmer`が読む`.result`
   が生成されないままElmerは正常終了する（エラーが出ないので見落としやすい）。

## Garfield++ (`ComponentElmer`, `AvalancheMicroscopic`)

7. **`ComponentElmer`の第4コンストラクタ引数は`mesh.boundary`ではなく
   誘電率ファイル。** シグネチャ: `ComponentElmer(header, elist, nlist,
   mplist, volt, unit)` — `mplist`は`dielectrics.dat`のような誘電率ファイル。
   `dielectrics.dat`のフォーマット: 1行目=配列サイズ、以降
   `<id(読み捨てられる)> <epsilon>`を1行ずつ、**行の並び順**が意味を持つ。

8. **`ComponentElmer`は`mesh.elements`のボディIDから内部で1を引く。**
   `mesh.names`は1始まりのID（例: `Gas = 1`）を報告するが、
   `SetMedium(imat, ...)`/`DriftMedium(imat)`やdielectrics.datのスロット
   位置は`body_id - 1`を使う必要がある。ここを間違えてもクラッシュせず、
   電場・電位の数値自体は正しいまま`status`（ドリフト媒質かどうかの判定）
   だけが静かに壊れる — 一番見つけにくいバグだった。症状: `status`だけ
   おかしいのに`Ex/Ey/Ez/V`の生の値は物理的に妥当に見える場合、まずこれを疑う。

9. **`AvalancheElectron()`の(dx,dy,dz)を(0,0,0)にすると「ランダム方向」を
   意味する。** 「初期速度なし」ではないので注意。ドリフト方向
   （このプロジェクトのz軸慣習では`(0,0,-1)`）を明示的に渡すこと。

10. **`AvalancheMicroscopic::EnableDriftLines()`を呼ばないと、経路の長さに
    関わらず始点・終点の2点しか記録されない。** `path`メンバへの記録は
    `EnablePlotting()`/`ViewDrift`とは独立で、`EnableDriftLines()`で明示的に
    有効化しないと`GetElectrons()[i].path`が実質空になる（デフォルトOFF）。
    `SetCollisionSteps(n)`は「何衝突ごとに記録するか」を制御するだけで、
    記録そのものを有効化するものではない。

11. **`AvalancheMicroscopic::EnableAvalancheSizeLimit(n)`は入れておく。**
    上限なしで大きめのイベント数を流すと、1イベントの雪崩が病的に
    大きく育つケースがあり、25分以上・RSS 3.5GB以上に達しても終わらない
    プロセスになったことがある。`EnableAvalancheSizeLimit(2000)`程度で
    単一イベントの暴走が全体を止めないようにする。

## ROOT / TApplication

12. **`TApplication`は`gROOT->SetBatch(kTRUE)`の**後**に構築すると
    ハングすることがある。** このクラスタでは`$DISPLAY`が設定されているが
    実際には接続できない（X11 forwardingが機能していない）。
    `TApplication app(...)`を先に構築すると、その接続試行で無期限にハング
    しうる。`SetBatch(kTRUE)`を`TApplication`構築より**前**に置くこと。

13. **ROOT/TApplicationを使うマクロは、正常終了後にteardown時のクラッシュ
    (double free / segfault / munmap_chunk invalid pointer)を起こすことが
    ある。** `view_gem_field`, `gem_avalanche`,
    `export_avalanche_trajectories`などで確認済み。実際のデータ書き込み・
    ファイルclose・PNG保存は全て正常に完了した**後**にプロセス終了時だけ
    落ちるパターンで、出力ファイルの中身自体は毎回正しいことを確認している。
    根本原因は未調査（ROOT/Garfield++の何らかのグローバル破棄順序の問題と
    推測）。実害はないので、終了コードが非ゼロでも出力ファイルが正しく
    書けていれば気にしなくてよい。

14. **同じ`.root`ファイルに複数のマクロがtreeを書き込む場合、
    `TFile::Open(path, "UPDATE")`で開き、自分のtreeだけ
    `file->Delete("<TreeName>;*")`で古いcycleを消してから書き直す。**
    そうしないと再実行のたびに`TreeName;1`, `TreeName;2`, ...と
    サイクルが増え続けたり、他のマクロが書いた別のtreeを壊したりする
    （`gem_avalanche.cpp`の"Endpoints"と`export_avalanche_trajectories.cpp`
    の"Trajectories"が同じ`<baseName>_avalanche.root`に共存する設計、
    `docs/reference.md`参照）。

## Python環境・依存パッケージ

15. **`matplotlib`は`gmsh`より先にimportする。** `gmsh`のネイティブ拡張が
    システムの古い`libstdc++`を先に読み込んでしまうと、より新しいABIを
    要求する`matplotlib`の拡張が読み込めなくなる（`env_gmsh_matplotlib_
    libstdcxx`参照）。

16. **PyVista導入時、`pip install pyvista`が同時に入れる最新の`vtk`
    （2026-09時点で9.7.0）は`trame_vtk`（2.8.13）のシーン直列化コードと
    非互換で、`TypeError: unhashable type 'VTKAOSArray_vtkFloatArray'`で
    HTML出力に失敗する。** `pip install "vtk==9.3.1"`で明示的に
    ダウングレードすると解決する。

17. **envfsキャッシュ（`~/local/bin/envfs.sh`）は、pip installの途中で
    repackすると不整合なイメージができる。** 環境変更（pip install/
    uninstallの一連の作業）が完全に終わってから`envfs.sh repack work`を
    実行すること。詳細・パッケージ追加履歴は`~/local/envfs_README.md`
    （このリポジトリの外、ホームディレクトリ直下）を参照。

## 出力ディレクトリ

18. ~~`macros/export_field_samples.cpp`が書くJSON（`field_vectors_full.json`
    等）だけは`<baseName>`プレフィックスが付かない。別モデルに切り替えて
    実行すると前のモデルの分を上書きする。~~ → **2026-09-24修正済み**
    （`results/json/<baseName>_field_{vectors,slice}_{full,zoom}.json`に
    プレフィックス付き）。この不整合を実際に踏んだ経緯: issue #3の
    可視化スクリプトを別モデル(`triple_gem_field_n5`)で確認しようとした際、
    直前に別モデル(`single_gem100_field`)向けに書かれた古いfield sample
    JSONがそのまま読み込まれ、streamlineが0本になる（seed点がgeometryと
    整合しない）という具体的な不具合を確認した。`visualization/plot_triple_gem.py`
    ・`plot_z_profiles.py`・`geometry/plot_3d_matplotlib.py`・
    `geometry/plot_3d_html.py`（後者2つは単段GEM専用の古いスクリプトで、
    `single_gem_field_`固定プレフィックスに更新）も合わせて修正済み。

19. **`macros/model_info.hh`の`LoadModelGeometryInfo`は、メッシュディレクトリ
    (`results/mesh/<baseName>/`)から2階層上がって`results/json/`を見に行く。**
    `results/mesh/`と`results/json/`が`results/`の直接の子であることを
    前提にしたパス計算なので、`results/`の構成自体を変える場合はこの関数の
    ロジックも一緒に直すこと。

20. **`results/mesh`・`results/root`はディスク容量が大きくなる（mesh/root
    ファイル合計で数GB～）ため、home配下ではなくgroupストレージに実体を置き、
    symlinkで`results/`配下から参照している。** 2026-09-24時点:
    `/group/had/sks/Users/sryuta/GEM_garfield/{mesh,root}`が実体、
    `results/mesh`・`results/root`はそこへのsymlink。`.gitignore`の
    `results/*`パターンはsymlink自体もパス名一致で無視するため、
    symlinkに変えても`git status`には出てこない。パス解決は透過的
    （`results/mesh/<baseName>/...`のようにこれまで通りアクセス可能）
    なので、上記19番の前提も壊れない。新しい実行環境でこのリポジトリを
    セットアップする場合は、このsymlinkが存在しないと`results/mesh`・
    `results/root`が単なる空ディレクトリとして作られてしまう点に注意
    （`geometry/build_*.py`等は`os.makedirs(..., exist_ok=True)`で
    ディレクトリを作るだけなので、symlinkが無くても動く自体は動くが、
    home配下の容量を消費してしまう）。

## Garfield++の再ビルド（ROOTバージョンを変えた場合）

Garfield++はROOTとABI互換性がある状態でリンクされている必要がある。ROOTを
アップグレードした場合、既存のGarfield++ビルドは（ソースが同じでも）
そのままでは新しいROOTとリンクできず、`undefined reference to
ROOT::TGenericClassInfo::TGenericClassInfo(...)`のようなリンクエラーになる。
公式ソース（gitlab.cern.ch/garfield/garfieldpp）から新しいROOT向けに
再ビルドし直す必要がある:

```bash
cd <garfieldppのソースツリー>/build
export ROOTSYS=<新しいROOTのインストール先>
export PATH="$ROOTSYS/bin:$PATH"
export LD_LIBRARY_PATH="$ROOTSYS/lib:$LD_LIBRARY_PATH"
cmake -DROOT_DIR="$ROOTSYS/cmake" .
cmake --build . -j"$(nproc)"
cmake --install .
```

Garfield++のインストール先が他プロジェクトとの共有インストールの場合、
再ビルドする前に他プロジェクトへの影響がないか確認すること。
