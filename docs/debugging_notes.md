# デバッグメモ: 3段GEM電子雪崩シミュレーション

2026-09-22時点の状況整理。`README.md`のステータス欄は要約のみなので、経緯・仮説検証・
未解決問題の詳細はこちらに残す。

## 現在のオープンな問題

3段GEMスタック（ドリフト側から100→50→50µm、`geometry/triple_gem_field_model.py`）で
電子雪崩を計算すると、**GEM1で発生した二次電子がほぼ100%GEM2に到達しない**。

100イベント（合計2354個の電子終端点）を回した結果:

```
status -7 (StatusAttached, 正味の付着): 6
status -5 (StatusLeftDriftMedium, 孔壁に衝突): 2354
Mean gain = 23.54 +/- 30.12 (n = 100)
```

GEM2に到達した電子（status上は孔を抜けて次段のガス領域に入る）は**ゼロ**。2354トライ
アルで0成功なので、真の透過率の95%上限は概算で0.1%程度 — 実機のGEM（透過率は条件に
よるが数十%〜90%程度が普通）と比べて明らかに異常な低さ。統計を増やせば通るように
なるという「統計不足」の話ではなく、系統的な効果である可能性が高い。

## これまでに検証した仮説

ユーザーの指摘を1つずつ潰していった記録。

1. **「induction/transfer電場が弱いのでは」** →
   `macros/probe_field.cpp`でGEM1孔出口付近の電場を直接プローブ。電場の向きが反転して
   いる箇所はなく、単調に押し出す方向を維持していることを確認。→ **電場の向きは問題
   ではないと判断**（ただし「向きは正しいが大きさが拡散に対して不十分」という、より
   踏み込んだバージョンは未検証 — 下記「次の一手」参照）。

2. **「十分遠方からドリフト電子が入射してくるはず。近すぎるのでは」** →
   注入距離を変えて比較（近傍/中間/遠方）。遠くから注入するほどむしろ悪化した。
   → **反証**（拡散が働く時間が増えるだけで、孔に入る前に外れる確率が上がる）。

3. **「方向や速度の設定が微妙に間違っているのでは」** →
   実際にバグを発見: `AvalancheElectron()`の末尾(dx,dy,dz)引数を`(0,0,0)`にしていたが、
   Garfield++はこれを「ランダムな初期方向をサンプルする」という意味に解釈する
   （「初期ドリフトなし」ではない）。ドリフト方向`(0,0,-1)`に修正済み
   （`macros/gem_avalanche.cpp`, `macros/view_gem_avalanche_cross_section.cpp`）。
   → **実在のバグだったので修正したが、根本問題（孔壁吸収）は解消しなかった**。
   雪崩で発生する二次電子は電離が起きたその場でGarfieldが物理的に方向を決めるため、
   この修正は初期電子（primary）の挙動にしか効かない。

4. **「その周り（中心セル）にいくつかのセルを生成しておくと効果があるのでは」** →
   単一の六角ユニットセルではなく3x3タイル化を実装
   （`geometry/gem_unit_cell.hole_centers_tiled`, `TripleGemTestConfig.n_cells_x/y`）。
   終端ステータスを`StatusLeftDriftArea`（センサー境界を横に抜けた=境界アーティファクト）
   と`StatusLeftDriftMedium`（孔壁に衝突=物理的な吸収）に分けて集計したところ:
   - `StatusLeftDriftArea`由来の損失（単一セルで約16%）は3x3タイル化で**完全にゼロ**に
     なった → 単一セルの境界アーティファクトだったと確認。
   - `StatusLeftDriftMedium`由来の損失（約84%）は**タイル化前後で変化なし** →
     境界アーティファクトでは説明できない、別の要因。

5. **「一度に打ち込む電子の数を増やしてみては／統計を増やしては」** →
   `e0`と注入半径をCLI引数化した上で100イベント（合計2354終端点）を実行。
   結果は上記の通り**0/2354でGEM2到達ゼロ** → 統計不足ではないことを確認。

6. **「現実問題もう少し電子がエネルギーを持っているのでは」** → **未検証**
   （`e0`（初期エネルギー, デフォルト0.1eV）をCLI引数化済み。高エネルギー側でのテスト
   はまだ実施していない。下記「次の一手」参照）。

## 次の一手候補（未着手）

- **トランスファー電場の大きさを振ってみる**: 仮説1は「電場の向き」しか検証していない。
  向きは正しくても、この細い孔（GEM1: 半径17.5〜32.5µm程度）を電子が拡散に負けずに
  抜けるには電場が弱すぎる、という可能性はまだ残っている。診断目的で
  `TripleGemTestConfig`のtransfer電場を意図的に強くしたモデルを再ビルドし、透過率が
  改善するか見るのが早い。
- **`e0`（初期エネルギー）を上げてテスト**: 仮説6がまだ手つかず。
  `gem_avalanche`の`e0_eV`引数（デフォルト0.1）を1.0, 5.0, 10.0あたりで振って
  status -5 / -7 / 到達の比率が変わるか比較する。
- 上記2つのどちらも効かない場合、「実際のGEM孔形状に対してこの拡散量・メッシュ密度
  でのマイクロスコピック輸送計算自体が何かおかしい」という、よりモデル寄りの可能性も
  検討する必要がある。

## パイプライン構築時に踏んだ落とし穴（Gmsh → Elmer → Garfield++）

こちらは物理の問題ではなく、素朴にハマったバグ・仕様。同種の変更をする際は再確認。

1. **OCCで作った接触ボリュームは`gmsh.model.occ.fragment()`が必要。** 個別に`cut()`
   しただけだと幾何学的に接しているだけでメッシュはconformalにならない
   （ElmerGridが"mesh is non-conforming"と警告）。境界を共有する全ボリュームを
   `synchronize()`/メッシュ生成前に`fragment()`し、物理グループのタグをfragment結果の
   マップから付け直す。
2. **ElmerGridは境界（および場合によってはボリューム）の物理グループIDを振り直す。**
   Gmsh側で付けたタグはそのままでは使えず、`.sif`の`Target Bodies`/`Target Boundaries`
   は`ElmerGrid`実行後に生成される`mesh.names`から読み取ったIDを使う必要がある。
3. **`ComponentElmer`の第4引数は`mesh.boundary`ではなく誘電率ファイル。** シグネチャは
   `ComponentElmer(header, elist, nlist, mplist, volt, unit)`。`dielectrics.dat`の
   フォーマット: 1行目=配列サイズ、以降`<id(未使用)> <epsilon>`を1行ずつ、行の並び順が
   意味を持つ（IDそのものは読み捨てられる）。
4. **Garfield++向けのElmerメッシュは2次（10節点）四面体が必須。** デフォルトの
   `gmsh.model.mesh.generate(3)`は1次（4節点）を作るので、`generate(3)`の後に
   `gmsh.model.mesh.setOrder(2)`を呼ぶ。
5. **`Simulation`ブロックに`Output File = "<name>.result"`が必要。** これがないと
   `.vtu`（ParaView用）だけが出力され、`ComponentElmer`が読む`.result`が生成されない
   ままElmerはエラーなく正常終了する。
6. **孔の空洞には明示的なGasボリュームが必要。** Cu/誘電体ブロックから孔を`cut()`で
   くり抜くだけだと、その空間は本当に「何もない」空洞になり、Gmshのメッシャーは
   警告なく無視する（ログに"Found void region"と出るだけ）。カット用と同じ形状の
   ソリッドをもう一つ作り、`fragment()`とGas物理グループに含める必要がある
   （`gem_unit_cell.build_hole_gas_volumes`）。
7. **`ComponentElmer`は`mesh.elements`のボディIDから内部で1を引く。** `mesh.names`は
   1始まりのID（例: `Gas = 1`）を報告するが、`SetMedium(imat, ...)`/`DriftMedium(imat)`
   やdielectrics.datのスロット位置は`body_id - 1`を使う必要がある。ここを間違えても
   クラッシュせず、電場・電位の数値自体は正しいまま`status`（ドリフト媒質かどうかの
   判定）だけが静かに壊れる — 一番見つけにくいバグだった。
8. **単一の六角ユニットセルには、横方向に拡散した電子が入れる「隣の孔」が存在しない。**
   上の「オープンな問題」節の仮説4を参照。3x3タイル化で対処可能だが、孔壁への吸収
   自体は解決しない。
9. **`AvalancheElectron()`の(dx,dy,dz)を(0,0,0)にすると「ランダム方向」を意味する。**
   上の仮説3を参照。「初期速度なし」ではないので要注意。

## 実行環境・運用まわりで踏んだトラブル

- **`TApplication`構築前に`gROOT->SetBatch(kTRUE)`を呼ばないとハングすることがある。**
  このクラスタでは`$DISPLAY`が設定されているが実際には接続できない（X11 forwardingが
  機能していない）。`TApplication app(...)`を先に構築すると、その接続試行で無期限に
  ハングしうる（CPU使用率ほぼ0%、出力なしのまま応答なし、という形で発現した）。
  `gem_avalanche.cpp` / `view_gem_avalanche_cross_section.cpp` / `view_gem_field.cpp`
  の3マクロ全てで、`SetBatch(kTRUE)`を`TApplication`構築より前に移動して修正済み。
- **`AvalancheMicroscopic::EnableAvalancheSizeLimit()`が必須。** 上限なしで150イベント
  流したところ、25分以上・RSS 3.5GB以上経過しても終わらないプロセスが発生（おそらく
  1イベントの雪崩が病的に大きく/詰まって成長し続けていた）。`EnableAvalancheSizeLimit
  (2000)`で単一イベントの暴走が全体を止めないようにした。`GetAvalancheSize()`は上限で
  打ち切られたサイズをそのまま返す。

## 関連ファイル

- `macros/gem_avalanche.cpp` — 本番の雪崩ゲイン計算マクロ（3段対応、CLI引数化済み）
- `macros/probe_field.cpp` — 任意の(x,y,z)点での電場・電位を直接プローブする診断ツール
- `macros/view_gem_avalanche_cross_section.cpp` — 断面(x-z)での雪崩可視化
- `geometry/gem_unit_cell.py` — `hole_centers_tiled`など、単位セル/タイル化ジオメトリ
- `geometry/triple_gem_field_model.py` — 3段GEMモデル（`TripleGemTestConfig`）
