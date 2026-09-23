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
   - **[2026-09-23訂正]** 下記「さらなる調査」の通り、この結論は不完全だった。境界
     アーティファクトは消えておらず、`status`コードが`-1`から`-5`へ変わって
     `StatusLeftDriftMedium`の中に紛れ込んでいただけ（タイル化後も約16%が依然として
     境界アーティファクト）。ただし残りの約84%は`r_end`が公称孔半径に一致する
     **正真正銘の孔壁吸収**であることも同時に確認できたので、「孔壁吸収が支配的」
     という大枠の結論自体は変わらない。

5. **「一度に打ち込む電子の数を増やしてみては／統計を増やしては」** →
   `e0`と注入半径をCLI引数化した上で100イベント（合計2354終端点）を実行。
   結果は上記の通り**0/2354でGEM2到達ゼロ** → 統計不足ではないことを確認。

6. **「現実問題もう少し電子がエネルギーを持っているのでは」** → **未検証**
   （`e0`（初期エネルギー, デフォルト0.1eV）をCLI引数化済み。優先度は低いとの判断
   （外部から提供された調査方針書、下記参照）で今のところ後回し）。

## 2026-09-23: さらなる調査（外部から提供された調査方針に基づく）

ユーザーから詳細な調査手順書（endpoint位置の保存→z/r分布→medium連続性→単段テスト→
電場scan、の順で切り分ける方針）を受け取り、それに沿って実施。

### medium連続性プローブ

`macros/probe_field.cpp`にmedium名の出力を追加。中心軸(x=0,y=0)上でGEM1孔→GEM1直下→
transfer gap→GEM2孔まで連続してプローブした結果、`medium=Ar/CH4, status=0`が一貫して
おり、**gas medium割り当てに途切れはない**ことを確認（ガス境界面ちょうどの1点だけ
`status=-6`だが、fragment()で作った隣接ボリューム境界面上の点位置判定の数値的な
曖昧さで実害なし）。

### endpoint位置の保存とz_end/r_end分布解析

`macros/gem_avalanche.cpp`に終端点の座標(xs,ys,zs,ts,es,xe,ye,ze,te,ee,status)を
CSV出力する機能を追加（`<baseName>_avalanche_endpoints.csv`）。新規スクリプト
`geometry/plot_avalanche_endpoints.py`でCSVから`z_end`/`r_end`ヒストグラムと
`r_end` vs `z_end`散布図（公称孔壁半径をオーバーレイ）を作成。3段スタックの
100イベント分析（2109終端点）で判明したこと:

- 損失の大半（約70%）はGEM1のdielectric帯（孔のneck部分、z≈4096-4196µm）に集中し、
  `r_end`が公称孔壁半径にほぼ一致 → **正真正銘の孔壁吸収**。
- **GEM2のdielectric帯（z≈2058-2090µm）にも明確なクラスタあり** → GEM1と1回目の
  transfer gap(2mm)を実際に突破した電子が一定数存在し、GEM2のさらに狭い孔
  （r_in=12.5µm）で吸収されている。GEM1を単独で突破する経路自体は存在する。
- **新発見**: `status=-5`の**16.4%**（2107件中346件）は、`xe`または`ye`が
  シミュレーション領域の境界（`half_extent_x/y`）ちょうどに張り付いている電子だった
  （上記、仮説4の訂正）。

### 単段100µm GEM単体でのテスト

3段スタックとは独立に、GEM1の実際の条件（100µm、ΔV=457.5V、drift 130V/cm、
transfer 2kV/cm）だけを再現した単段GEMモデルを新規構築
（`geometry/build_single_gem100_field_mesh.py` → `single_gem100_field.*`、
既存の単段50µmテスト`single_gem_field.*`とは別物として追加、上書きしていない）。
100イベント実行の結果、境界アーティファクトを除いた「正真正銘の孔壁/Cu吸収」は
**すべてGEM1自身の箔厚み内（z∈[-59,+38]µm）に収まっており、transfer gapへ到達した
電子は1件もなし（0%）**。

**→ 3段スタック特有の問題ではなく、GEM1単体の孔形状・電場設定に起因することを確認。**
（隣接GEMとのカップリング、周期性、GEM間フィールドは原因から除外できる。）

### transfer電場scan（2 kV/cm → 10 kV/cm）

同じ単段GEM100モデル（`build_single_gem100_field_mesh.py`にCLI引数でtransfer電場を
上書きできるよう対応）でtransfer電場を5倍（2kV/cm→10kV/cm）にして再実行。
**genuine孔壁損失は依然として100%GEM1の箔厚み内に収まったまま、transfer gap到達は
やはり0件** — 電場を5倍にしても孔からの脱出は全く改善しなかった。

## 2026-09-24: 重要な訂正 — 「transmission ≈ 0%」は判定方法の問題だった

外部から改めてレビューを受け、**「endpointの最終status/位置だけを見て判定するのは
不十分ではないか」**という指摘があった。具体的には、電子がGEM1・transfer gapを
実際に突破してGEM2付近まで到達した後、最終的にGEM2自身の孔壁（またはCu）に
吸収されて`status=-5`になった場合、これまでの見方では「GEM2に到達していない」と
同じ扱いになってしまっていた。

これを受けて、endpointの最終状態ではなく**電子の記録済み経路(path)がある z 平面を
一度でも通過したか**で判定する新しいスクリプト
`geometry/analyze_plane_crossings.py`を作成し、既存のtrajectory ROOTデータ
（`macros/export_avalanche_trajectories.cpp`が書く`Trajectories` tree）に対して
実行した。3段GEM全体、20イベント（389 avalanche electrons）での結果:

```
Crossed GEM1 top     (z <  4205.0 um): 389 (100.0% of all)
Crossed GEM1 bottom  (z <  4087.0 um): 182 ( 46.8% of all,  46.8% of GEM1 top組)
Crossed GEM2 top     (z <  2087.0 um):  17 (  4.4% of all,   9.3% of GEM1 bottom組)
Crossed GEM2 bottom  (z <  2029.0 um):   3 (  0.8% of all,  17.6% of GEM2 top組)
Crossed GEM3 top     (z <    29.0 um):   0 (  0.0% of all,   0.0% of GEM2 bottom組)
```

**これまでの「GEM2到達0%」という結論は、正確には「GEM2に到達した"上で、かつ
GEM2自身の孔も抜けて"induction側まで完全通過した」電子がゼロ、という意味で
あって、「GEM2の近傍まで到達する電子自体がゼロ」という意味ではなかった。**
実際には約9.3%（GEM1脱出後基準）がGEM2の入り口付近まで到達しており、
「GEM1が電子をほぼ完全にブロックしている」という当初の描像は不正確だった。

正しい描像: 各段でカスケード的に効率が落ちていく（GEM1抽出効率~47%、
GEM1→GEM2到達~9%、GEM2抽出（サンプルが3件のみで精度は低い）~18%）。
この「各段で数十%ずつ削られていく」というパターンは、単一箇所が完全に
シミュレーションを壊しているような不自然な挙動ではなく、**むしろ現実的な
GEM物理（各段で有限の抽出効率がある）に近い形**であり、上記(b)の仮説
（コードのバグというより、この特定の孔径・電圧設定における現実的な低い
透過率）をさらに支持する結果と言える。ただしGEM2以降は統計が非常に少ない
ため、イベント数を増やしてより確実な数値を得る必要がある。

「avalanche gain」の定義についても整理: `AvalancheMicroscopic::GetAvalancheSize`
が返す`ne`は「readoutまで到達した電子数」ではなく「avalanche内で生成された
電子の総数（吸収されたものも含む）」に近い。今後は
「avalanche gain（GEM1内で生成された総数）」「GEM1 extraction efficiency」
「GEM1→GEM2 transmission」「最終的な実効ゲイン」を分けて評価する。

## 現時点の結論と次の一手候補

- 電場の「向き」（仮説1）・「大きさ」（上記scan）・注入距離（仮説2）・注入方向
  （仮説3）・単一セル境界（仮説4、ただし訂正あり）・統計不足（仮説5）・medium連続性・
  3段スタック特有性は、いずれも唯一の原因ではないと切り分けられた。
- 上記の訂正により、「GEM1が電子をほぼ完全にブロックする」という当初の描像から、
  「各段で有限の抽出効率がある、カスケード的な透過率低下」という描像に更新。
  残る作業: (a) 統計を増やしてGEM2・GEM3段の効率をもっと正確に見積もる、
  (b) この効率が実機のGEM透過率（文献値）と比べて妥当な範囲か評価する、
  (c) `SetCollisionSteps`を1（衝突ごとに記録）にした場合の実際のステップ幅を
  見て、tracking解像度に起因する見かけの効果がないか確認する（未実施）。
- `e0`（初期エネルギー）scanは優先度が低いとの調査方針書の判断に従い、まだ未実施。
- 次に検証するなら、(a)のtracking解像度感度、または孔径・GEM電圧を変えたときに
  透過率がどう変化するか（現実的な設計変更の効果を見る）が候補。

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
- `geometry/plot_avalanche_endpoints.py` — endpoint CSVから`z_end`/`r_end`分布を可視化
- `geometry/build_single_gem100_field_mesh.py` — GEM1単体（100µm、実条件）の切り分けテスト用モデル、transfer電場をCLI引数で上書き可能
