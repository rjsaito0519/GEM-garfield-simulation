# リファレンス: パイプラインの実行方法・出力構成

`README.md`が全体像の要約なら、こちらは実際にコマンドを叩いて一からモデルを
再現するための詳細手順。新しいモデル（別の電圧・別の孔径など）を試すときも、
基本的にこのページの流れをなぞればよい。

## 1. 全体のパイプライン

```
geometry/build_*.py (Gmsh Python API)
  → results/mesh/<baseName>.msh, results/json/<baseName>_model_info.json,
    results/json/<baseName>_mesh_surfaces.json
  ↓
elmer/run_field_solve.sh <baseName> (ElmerGrid → elmer/write_sif.py → ElmerSolver)
  → results/mesh/<baseName>/ (mesh.header, mesh.elements, ..., <baseName>.result)
  ↓
macros/*.cpp (Garfield++, ビルド済みバイナリは macros/build/ 配下)
  → results/root/<baseName>_avalanche.root, results/json/field_*.json,
    results/img/*.png
  ↓
visualization/*.py, geometry/plot_*.py
  → results/html/*.html, results/img/*.png
```

各段はいまの`<baseName>`のモデル一式が前段の出力として存在していることだけを
前提にしている。つまり別モデルに切り替えるときは、この4段を`<baseName>`を
変えて順番に流し直せばよい。

現在存在する`<baseName>`（`geometry/build_*.py`のどれかに対応）:

| baseName | スクリプト | 内容 |
|---|---|---|
| `single_gem_field` | `geometry/build_single_gem_field_mesh.py` | 単段GEM(50µm)テスト。Milestone 2の元祖モデル |
| `single_gem100_field` | `geometry/build_single_gem100_field_mesh.py` | GEM1(100µm)単体を実機条件で切り出したテスト。`python3 build_single_gem100_field_mesh.py [transfer_field_v_per_cm]`でtransfer電場を上書き可能（診断用、デフォルト2000） |
| `triple_gem_field` | `geometry/build_triple_gem_field_mesh.py` | 3段GEMスタック本番モデル |

## 2. 実際に叩くコマンド（triple_gem_fieldの例）

```bash
# 1. ジオメトリ・メッシュ生成
cd geometry
python3 build_triple_gem_field_mesh.py

# 2. Elmer電場ソルブ
cd ../elmer
bash run_field_solve.sh triple_gem_field

# 3. Garfield++マクロ (macros/build/ でビルド済みが前提。ビルド手順は下記)
cd ../macros/build

# 電位分布の可視化（PNG）
./view_gem_field ../../results/mesh/triple_gem_field

# 電場サンプル（3Dビューア用JSON）
./export_field_samples ../../results/mesh/triple_gem_field ../../results/json

# 電子雪崩ゲイン計算（ROOT "Endpoints" tree + drift-lines PNG）
./gem_avalanche ../../results/mesh/triple_gem_field ../../resources/ar_ch4_90_10.gas \
  100 -0.2029 0.8405 0.4235 0.021 0.03637306695894642 0.1 0.0005 \
  ../../results/root ../../results/img

# 雪崩の全軌跡（ROOT "Trajectories" tree、少数イベント推奨）
./export_avalanche_trajectories ../../results/mesh/triple_gem_field ../../resources/ar_ch4_90_10.gas \
  5 -0.2029 0.8405 0.4235 0.021 0.03637306695894642 0.1 0.0005 ../../results/root

# 4. Python可視化
cd ../../visualization
python3 plot_triple_gem.py triple_gem_field   # geometry+電場+trajectory+streamlineをHTMLに
python3 plot_z_profiles.py triple_gem_field   # Ez(z)/|E|(z)/Ne(z)診断プロット
```

`gem_avalanche`/`export_avalanche_trajectories`のCLI引数（`zSensorMin`,
`zSensorMax`, `zInjection`, `xHalfCm`, `yHalfCm`）はモデルによって異なる。
各macroの冒頭docstringに意味の説明があるほか、実際の値は
`results/json/<baseName>_model_info.json`の`"geometry"`ブロック
(`z_domain_min_cm`, `z_domain_max_cm`, `half_extent_x_cm`, `half_extent_y_cm`)
から読み取れる（`macros/model_info.hh`がC++側でも同じJSONを単一の情報源として
参照している。ハードコードの重複を避けるための設計 — 詳細は
`docs/pipeline_gotchas.md`参照）。

### C++マクロのビルド

```bash
cd macros
mkdir -p build && cd build
cmake ..
cmake --build . -j"$(nproc)"
```

## 2.5. 現在のproduction condition (`baseName` = `triple_gem_field_v1.15x_n7`) の再現手順

README.md「現在のproduction condition」に対応する、実際に叩くコマンド全体
（2026-09-24時点、GitHub issue #7/#8）。上の§2のtriple_gem_field例との違いは
voltage multiplier(1.15)・n_cells(7)・ElmerSolverのpreconditioner override・
avalanche計算をbsub分割で行う点。

```bash
# 1. ジオメトリ・メッシュ生成（voltage_multiplier=1.15, n_cells=7）
cd geometry
python3 build_triple_gem_field_mesh.py 1.15 7
# -> results/mesh/triple_gem_field_v1.15x_n7.msh,
#    results/json/triple_gem_field_v1.15x_n7_model_info.json

# 2. Elmer電場ソルブ（ILU1を明示指定 -- デフォルトのILU2は7x7規模の
#    メッシュ(約545万ノード)では "CRS_IncompleteLU: Number of nonzeros
#    larger than HUGE(Integer)" で失敗する。docs/debugging_notes.md
#    2026-09-24節参照）
cd ../elmer
bash run_field_solve.sh triple_gem_field_v1.15x_n7 ILU1 2000

# 3. 電子雪崩計算（KEKCC bsub分割、50イベントを10ジョブに分割）
cd ..
python3 batch/run_avalanche_batch.py \
  results/mesh/triple_gem_field_v1.15x_n7 resources/ar_ch4_90_10.gas \
  50 -0.2029 0.8405 0.4235 0.049 0.08487048957087498 0.1 0.0005 \
  --njobs 10 --avalanche-size-limit 20000
# queue引数省略時のデフォルトは"l"(2026-09-26変更、下記参照)。
# -> results/root/triple_gem_field_v1.15x_n7_avalanche.root ("Trajectories" + "RunInfoTrajectories" tree)

# 4. genuine plane-crossing解析（GEM1-extracted cohortのfunnel、最終fate等）
cd geometry
python3 analyze_plane_crossings.py \
  ../results/root/triple_gem_field_v1.15x_n7_avalanche.root
```

この`_avalanche.root`は"RunInfoTrajectories" treeを持つため、
`analyze_plane_crossings.py`はn_cells等の幾何条件を自動で読み取る
（末尾の明示的なn_cells引数は不要、GitHub issue #6 item 2）。

**2026-09-25時点で解消: production limitは`avalanche_size_limit=20000`
を使用する。** `EnableAvalancheSizeLimit(2000)`がPenning transfer有効化後
は頻繁に到達していた問題（このproduction条件で50イベント中28イベントが
到達）を受け、GitHub issue #12 item 1として`triple_gem_field_v1.15x_n5`上
で2000/5000/10000/20000の小統計(各10-20イベント)sweepを実施:

| avalanche_size_limit | limit到達割合 | avalanche size (mean/median/max) |
|---|---|---|
| 2000  | 2/20 (10.0%) | 773.5 / 362.5 / 2005 |
| 5000  | 0/20 (0.0%)  | 1120.5 / 947.5 / 3635 |
| 10000 | 0/20 (0.0%)  | 716.1 / 423.0 / 3037 |
| 20000 | 0/20 (0.0%)  | 553.5 / 288.5 / 2318 |

limit到達割合は5000以上で0%に落ち、GEM1-extracted cohortの各funnel段
(GEM1 extraction, GEM2 hole entrance, GEM2 bottom, 等 -- `analyze_plane_crossings.py`
出力)の比率もlimit値に対して系統的な傾向は見られず、10-20イベントの統計
誤差内で一致した（詳細はissue #12のコメント参照）。よって
`avalanche_size_limit=20000`（9x9のfinite geometry convergence run
[issue #12 item 3]で既に使用中）を今後の production limitとして採用する。
**ただし各点10-20イベントと統計が小さく、厳密な収束証明ではなく「傾向として
問題なし」という判断である点に注意。**

**2026-09-25/26解消 (issue #14): `triple_gem_field_v1.15x_n7_avalanche.root`を
`--avalanche-size-limit 20000`で再生成済み。** 50イベント中limit到達は1件のみ
（旧`avalanche_size_limit=2000`では28件だった）。再生成の過程で2つの実バグを
発見・修正:

- queue "s"(150分CPU上限)では、limitが緩んだ分イベント処理が長引き
  10ジョブ中7ジョブがTERM_CPULIMITで失敗 -- 9x9バッチと同じ原因。queue "l"
  (1200分)へ`--retry-indices`で再投入して解決。**2026-09-26、9x9・n7の両方で
  同じ理由でqueue "s"→"l"のリトライが発生したため、`run_avalanche_batch.py`
  の`--queue`デフォルトを"s"から"l"に変更**（"sで投入→CPU上限で失敗を発見→
  lに再投入」という毎回の無駄な待ち時間を避けるため）。
- 一部partファイル(特にサイズの大きいもの)がROOTのTTree autosaveで
  複数cycleを持つ状態になり、`uproot`で読めなくなる
  (`ValueError: read length must be non-negative or -1`、ROOT自体/`hadd`は
  問題なく読める)不具合を発見。`export_avalanche_trajectories.cpp`/
  `gem_avalanche.cpp`で`SetAutoSave(0)`を設定し、1 runにつき1 cycleのみに
  することで解消（該当partは`hadd`で1cycle化して復旧、entry数が一致することを
  確認済み）。
- `--resume-run-id`利用時に`--base-seed`を明示しないと再試行のたびに
  異なるseedが使われ、`_validate_part`のrng_seed厳密一致チェックが
  誤って失敗することが判明。rng_seedの妥当性チェックのみに緩和
  （offset/n_events/avalanche_size_limit/geometry_typeのチェックは維持）。

**2026-09-25解消: issue #12 item 3 (7x7 vs 9x9 finite geometry
convergence)。** `triple_gem_field_v1.15x_n9`(9x9、50イベント、
avalanche_size_limit=20000)を`triple_gem_field_v1.15x_n7`(7x7、50イベント)
と`analyze_plane_crossings.py`で比較（2026-09-26、n7がissue #14で
avalanche_size_limit=20000に再生成された後の数値に更新、両者とも
同じlimitでの比較になった）:

| 指標 (GEM1-extracted cohort比) | 7x7 (limit=20000) | 9x9 (limit=20000) |
|---|---|---|
| T1 25%→75%の低下 | 41.1%→39.2% | 41.1%→40.9% |
| GEM2 hole entrance | 15.3% | 16.1% |
| GEM2 bottom | 2.7% | 2.8% |
| GEM3 top | 0.3% | 0.4% |
| GEM3 bottom | 0.1% (5/8615) | 0.1% (10/10309) |
| 最終fateでの"StatusLeftDriftArea"(ラテラル脱出) | 0件 | 0件 |

GEM2以降の各比率は統計誤差内で一致し、両方とも最終fateにラテラル脱出が
一切ない（5x5で見られた34.2%の大きな損失は完全に解消済み）。7x7側の
transfer gap 1内でのT1 25%→75%のわずかな残存低下（9x9では消失）のみが
差分だが、無視できる規模。よって**7x7を production tile sizeとして
継続採用する**（9x9へ拡張する必要なし）。

同issue item 2として`collisionSteps`(trajectory export時のcollision point
間引き)の1/5/20 sweepも実施し、GEM1 extraction等の比率・avalanche size
limit到達割合ともにcollisionSteps値に対する系統的な傾向は見られなかった
（同じく10-20イベントの統計内）。よって production では軽い設定
（`collisionSteps`のデフォルト値、現状のproduction再現手順が使う値）を
そのまま使用してよいと判断する。

## 3. 出力ディレクトリ構成 (`results/`)

2026-09-23にファイル種別ごとの構成へ整理した。以前は`geometry/output/`,
`macros/output/`, `visualization/output/`と分散していたが、現在は
リポジトリ直下の`results/`に一本化されている。

```
results/
  mesh/       Gmsh出力(.msh)とElmerGrid変換後のメッシュディレクトリ(<baseName>/)
              (mesh.header, mesh.elements, mesh.nodes, mesh.names,
               mesh.boundary, dielectrics.dat, entities.sif, <baseName>.result,
               <baseName>_t0001.vtu, <baseName>.sif)
  json/       model_info.json, mesh_surfaces.json, field_vectors/slice_*.json
  root/       <baseName>_avalanche.root （"Endpoints", "Trajectories" tree、後述）
  img/        検証用の全PNG（git管理対象はこのディレクトリのPNGのみ）
  html/       PyVista/Plotlyのインタラクティブ3Dビューア (.html)
```

`.gitignore`は`results/`以下を丸ごと無視しつつ、`results/img/*.png`だけを
例外的に追跡する（再現可能な生成物なので、目視確認用の画像だけをgit管理する
方針。他のディレクトリの中身はパイプラインを再実行すればいつでも再生成できる）。

`macros/export_field_samples.cpp`が書き出すJSON
（`<baseName>_field_vectors_full.json`, `<baseName>_field_slice_full.json`等、
2026-09-24より`<baseName>`プレフィックス付き）も他の出力と同様
`results/json/`直下に書かれる。可視化スクリプトを実行する前に、対象に
したい`<baseName>`で`export_field_samples`を一度実行しておくこと。

## 4. ROOT出力のスキーマ

`results/root/<baseName>_avalanche.root`は1ファイルに最大4つのTTreeを持つ
（`Endpoints`, `Trajectories`, `RunInfoEndpoints`, `RunInfoTrajectories`
-- batch mergeされたファイルはさらに`BatchMergeProvenance`も持つ、
`batch/run_avalanche_batch.py`参照）。`gem_avalanche`と
`export_avalanche_trajectories`はどちらも`TFile::Open(..., "UPDATE")`で
開き、自分の書くtreeの古いcycleだけを`Delete("<TreeName>;*")`で消してから
書き直すので、片方だけを再実行してももう片方が書いたtreeは残る。

### `Endpoints` (macros/gem_avalanche.cpp が書く)

電子1個の終端点ごとに1エントリ。

| branch | 型 | 意味 |
|---|---|---|
| `event` | int | 何番目の注入イベントか |
| `xs,ys,zs` | double | 始点座標 [cm] |
| `ts,es` | double | 始点の時刻 [ns] / エネルギー [eV] |
| `xe,ye,ze` | double | 終点座標 [cm] |
| `te,ee` | double | 終点の時刻 [ns] / エネルギー [eV] |
| `status` | int | Garfield++の終端ステータス（`GarfieldConstants.hh`参照。よく出るのは`-5`=StatusLeftDriftMedium(固体に衝突), `-7`=StatusAttached(付着)） |

Pythonから読む例（`uproot`使用）:
```python
import uproot
with uproot.open("results/root/triple_gem_field_avalanche.root") as f:
    data = f["Endpoints"].arrays(["ze", "status"], library="np")
```

### `Trajectories` (macros/export_avalanche_trajectories.cpp が書く)

電子1個の経路の記録点ごとに1エントリ（`(event, track)`のペアで1本の経路を
識別する。`track`は`AvalancheMicroscopic::GetElectrons()`内でのイベントごとの
インデックスで、グローバルに一意ではない）。

| branch | 型 | 意味 |
|---|---|---|
| `event` | int | 何番目の注入イベントか |
| `track` | size_t | イベント内の電子インデックス |
| `x,y,z` | double | 座標 [cm] |
| `t` | double | 時刻 [ns] |
| `energy` | double | 運動エネルギー [eV] |

少数イベント推奨（`view_gem_avalanche_cross_section.cpp`と同じ理由:
100イベント分の全経路を出すと可視化に使えないほど巨大になる）。

### `RunInfoEndpoints` / `RunInfoTrajectories` (gem_avalanche.cpp / export_avalanche_trajectories.cpp がそれぞれ書く)

2026-09-24追加（GitHub issue #6 item 1）。そのrunで実際に使われた条件を、
key/value文字列ペア1つにつき1エントリで記録する固定でないスキーマ
（`macros/run_info.hh`参照）。single-GEM/triple-GEMで`model_info.json`の
`geometry`ブロックの形が違う（後者のみ`layers`を持つ）ため、個々の
フィールドに分解せず`model_info_json`キーの下に元のJSON全体をそのまま
埋め込んでいる。

**2026-09-25、GitHub issue #11 item 1でtree名を分離**: 当初は両マクロとも
同じ`RunInfo`という名前で書いていたため、同じ出力ファイルに両方を実行すると
最後に実行した方の条件で上書きされてしまっていた（`Endpoints`/
`Trajectories`自体は互いに影響しない）。`gem_avalanche`は
`RunInfoEndpoints`、`export_avalanche_trajectories`は`RunInfoTrajectories`
という別々の名前で書くように変更、双方が同じファイルに共存できる。

| key | 意味 |
|---|---|
| `executable` | `"gem_avalanche"` / `"export_avalanche_trajectories"` |
| `git_commit_hash`, `git_dirty` | ビルド時（`cmake`実行時点、ビルドの度ではない）のgit commit hashと、その時点でtracked fileに未commit差分があったか |
| `mesh_dir`, `geometry_type` | argv[1]そのもの、およびそのbaseName |
| `gas_file`, `gas_temperature_k`, `gas_pressure_torr` | 使用した`.gas`ファイルと、`MediumMagboltz::LoadGasFile()`後に実際に読み込まれた温度・圧力 |
| `gas_material_index` | `model_info.hh`の`geo.gas_material_index`（GitHub issue #6 item 3、#10 item 1で`mesh.names`由来に修正） |
| `penning_transfer_enabled`, `penning_r`, `penning_lambda_cm` | Penning transferの有効/無効と、有効な場合に実際に使われたr/λ（GitHub issue #11 item 3。Garfield++バージョンが変わると内蔵の自動計算値も変わりうるため、フラグだけでなく実値を記録） |
| `n_events`, `z_sensor_min_cm`, `z_sensor_max_cm`, `z_injection_cm`, `x_half_cm`, `y_half_cm`, `e0_ev`, `injection_radius_cm` | CLI引数そのまま |
| `avalanche_size_limit`, `n_events_at_avalanche_size_limit` | `EnableAvalancheSizeLimit()`の値と、そのrunで実際に上限に達したイベント数 |
| `rng_seed` | 明示seedを渡した場合はその値、渡さなければ`"auto (process-default)"` |
| `model_info_json` | `<baseName>_model_info.json`の生の中身（geometry・physical_group_ids・electrode_potentials_v・dielectric_relative_permittivity・garfield_material_indices等すべて含む） |

Pythonから読む例:
```python
import uproot
with uproot.open("results/root/triple_gem_field_avalanche.root") as f:
    arr = f["RunInfoTrajectories"].arrays(["key", "value"], library="np")
    run_info = dict(zip(arr["key"], arr["value"]))
    print(run_info["rng_seed"], run_info["git_commit_hash"])
```

## 5. KEKCC batch (bsub) でのavalanche計算並列化 (`batch/`)

`export_avalanche_trajectories`のavalanche計算はイベント間で状態を共有
しない（embarrassingly parallel）ため、統計を増やす際（100-200イベント
規模）はKEKCCのLSF batch (`bsub`)に分割投入した方が速い。`batch/`配下に
専用の軽量スクリプトを用意した（2026-09-24、GitHub issue #2の議論より）。

- `batch/bsub_utils.py` — `bsub`投入・`bjobs -a`による状態ポーリングの
  薄いラッパー。ジョブ数が増えても`bjobs`を1回だけ叩いてまとめて状態を
  引く設計（`~/analyzer/JPARC2025E72/runmanager`のBJobManagerのアイデア
  を参考にしたが、DST解析固有のrunlistスキーマ等は持ち込んでいない）。
  投入コマンドは`bash -lc`でログインシェル経由にする
  （`~/.bashrc`の`$LSB_JOBID`分岐でenvfsの代わりに本来のROOT/condaパスに
  フォールバックする仕組みに乗るため、ノードローカルのenvfsマウントに
  依存しない）。
- `batch/run_avalanche_batch.py` — 総イベント数をN個のジョブに分割し、
  各ジョブに`export_avalanche_trajectories`の新しい`eventOffset`引数
  （2026-09-24追加）で重複しないevent番号範囲を割り当てて`bsub`投入、
  全ジョブ完了を待ってから`hadd`で`results/root/<baseName>_avalanche.root`
  に結合する。既存の解析スクリプトは(event,track)をglobalに一意な
  キーとして扱うため、この分割・結合方式でも変更なしにそのまま動く。

```bash
# まず必ず --dry-run で投入内容を確認する（bsubは一切呼ばれない）
python3 batch/run_avalanche_batch.py results/mesh/<baseName> resources/ar_ch4_90_10.gas \
  <n_events_total> <zSensorMin> <zSensorMax> <zInjection> <xHalfCm> <yHalfCm> \
  [e0_eV] [injectionRadiusCm] [collisionSteps] --njobs 10 --dry-run

# 実際に投入する場合は --dry-run を外す（--queueを省略するとデフォルトの"l"に投入される）
python3 batch/run_avalanche_batch.py ... --njobs 10
```

各ジョブの中間ファイル・bsubログは`results/root/.batch_tmp/<baseName>/<run_id>/partNNN/`
に残る（`run_id`は実行ごとのタイムスタンプ、デバッグ用、自動削除しない
-- 2026-09-25、GitHub issue #9で実行ごとに独立したディレクトリに変更）。
**注意**: バッチジョブ投入（`bsub`実行）はプロジェクトの安全ルール上、
ユーザーが明示的にその場で依頼したときのみ行う（`--dry-run`なしでの
実行は自動では行わない）。Elmer solve自体（MPI分割等）はこの枠組みの
対象外 — 単一の線形システムを解く工程であり、avalanche計算のような
単純な並列分割ができないため。

## 5.5. Efficiency の定義（GitHub issue #7 item 5 / #12 item 5）

複数の解析スクリプトが別々のefficiency量を計算しているため、混同を
避けるためにここで一箇所にまとめる。

| 用語 | 定義 | 測定方法 |
|---|---|---|
| **Collection efficiency** | GEM上方の広い一様領域から注入された一次電子のうち、実際にホール開口部へ入った割合 | `geometry/analyze_collection_efficiency.py`。**単独GEM（一様上方電場）でのみ意味を持つ**定義 -- 3段スタック中のGEM2/GEM3は前段の非一様な雪崩出力を受け取るため、この意味でのcollection efficiencyは定義できない（下記「次GEM進入率」参照） |
| **Local multiplication** | collectionされた一次電子1個あたりの、そのGEM内での二次電子生成数（`track`数） | `analyze_collection_efficiency.py`の`Local multiplication`出力 |
| **Extraction efficiency** | collectionされた一次電子のうち、そのGEMの底面を実際に下向きに通過した（genuine crossing）割合 | `analyze_collection_efficiency.py`の`Extraction efficiency`出力、または`analyze_single_gem_plane_crossings.py` |
| **Transfer efficiency** | あるGEMを抜けた電子のうち、transfer gapを生き残って次段のGEM近傍に到達した割合 | `analyze_plane_crossings.py`のfunnel（例: "T1 75%"等の中間平面通過率） |
| **次GEM進入率 (next-GEM collection)** | 3段スタックのembedded文脈で、あるGEMの実際の（非一様な）雪崩出力のうち、次GEMの実ホール開口部へ入った割合 -- 上記collection efficiencyとは別概念、cascade特有の量 | `analyze_plane_crossings.py`の"GEM2 top (hole entrance)"等 |
| **Effective gain** | 1個の一次電子（あるいは1個の実イベント）あたり、最終的にreadout/induction面に到達した電子数 -- `AvalancheMicroscopic::GetAvalancheSize()`が返す"gain"（`ne`）とは異なる。`GetAvalancheSize()`は雪崩木全体で生成された総電子数（後で吸収されるものも含む）であり、detector effective gainではない | まだ標準出力化されていない（issue #12 item 1のavalanche size limit convergence確認後に整備予定） |

`macros/gem_avalanche.cpp`のコメントは`GetAvalancheSize()`の`ne`を
"gain"（生成総数）と呼び、"detector effective gain"とは呼ばないよう
既に整理済み（2026-09-24）。

## 6. 関連ドキュメント

- `README.md` — プロジェクト概要、対象デバイス、実行環境
- `docs/debugging_notes.md` — GEM1→GEM2電子透過率問題の調査ログ（issue #2）
- `docs/pipeline_gotchas.md` — Gmsh/Elmer/Garfield++連携で踏んだ落とし穴集
- `CLAUDE.md` — AIエージェント向けエントリポイント
