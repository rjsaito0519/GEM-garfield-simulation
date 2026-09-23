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

## 2026-09-23: 重要な訂正 — 「transmission ≈ 0%」は判定方法の問題だった

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

## 2026-09-23: tracking解像度の仮説(a)を反証、GEM電圧scanは実行環境の壁にぶつかる

### `SetCollisionSteps=1`での実ステップ幅確認 → 仮説(a)を反証

`macros/export_avalanche_trajectories.cpp`の`SetCollisionSteps`をCLI引数化
（新規、`[collisionSteps]`引数、デフォルト100のまま）し、1（＝実際の衝突ごとに
記録）で単段GEM100(`single_gem100_field`)を1イベント実行。GEM1の孔近傍
（|z|<60µm、孔の厚み全体をカバー）での実際の1ステップあたりの移動距離:

```
中央値: 0.16-0.17 um
平均:   0.26-0.28 um
最大:   2.8 um
```

孔の半径スケール（17.5〜32.5µm）と比べて、典型的なステップは**100倍以上**、
最大ステップでも**10倍以上**小さい。つまり実際のマイクロスコピック輸送計算は
孔の形状に対して十分細かい解像度で境界判定を行っており、
**「tracking解像度が粗すぎて壁への衝突判定がおかしい」という仮説(a)は反証された**。
残る有力仮説は(b)「孔内部の局所電場が支配的な、現実的な物理的帰結」のみ。

### GEM電圧を上げる診断scan → 実行環境の制約で難航（未完了）

「電場を強くすれば増幅・透過が改善するか」を直接確認するため、GEM電圧を
2〜3倍にする診断scanを試みたが、以下の技術的な壁にぶつかり、まだ結論が
出ていない:

1. **3段フルスタックでのElmer収束問題**: 電圧を3倍にすると、デフォルトの
   `CG + ILU1`ソルバー設定では2000反復で収束せず(`Too many iterations`)。
   反復上限を20000に増やしても22分収束せず。`BiCGStab + ILU2`は逆に発散
   (`System diverged`)。`CG + ILU2`も同様に低速。1.5倍でも同じ傾向。
   → 診断目的なら**フルスタックではなく`single_gem100_field`（GEM1単体、
   ノード数が1/40）に切り替えるべき**と判断（GEM1単体で同じ現象が再現する
   ことは既に確認済みなので、この切り替えは有効）。
2. **`single_gem100_field`でも電場3倍だとavalanche計算が極端に遅い**:
   原因は電子のエネルギーがMagboltzの衝突レートテーブルのデフォルト範囲を
   大きく超え(`Rate at 135eV is not included...`のような警告が多数)、
   その都度テーブルを動的に拡張していたため。`gem_avalanche.cpp`に
   `MediumMagboltz::SetMaxElectronEnergy()`をCLI引数化
   （新規、`[maxElectronEnergyEv]`引数）して事前にテーブル範囲を広げる
   対応を追加、テーブル拡張の警告は出なくなったが、それでも数分かかる
   （大きな雪崩自体の計算コストは減らないため）。

`elmer/write_sif.py`の`_SOLVER_BLOCK`は`CG + ILU2`, 反復上限20000のまま
残してある（元の`CG + ILU1`, 2000反復よりは頑健なはずだが、根本的な
高電圧での収束性は未解決）。

## 2026-09-23: 孔形状（biconical vs cylindrical）sensitivity scan → 主因ではないと判明

外部から「現在の100µm GEM孔は65→35→65µmの対称なbiconical/hourglass形状だが、
実機（LCP + laser etching製造）はほぼcylindricalという文献例もある。この
taper形状自体が電子をneckに大量吸収させている主因では」という仮説が来た。

### 手法

`geometry/gem_params.py`の`GEM_100UM`は変更せず、`build_single_gem100_field_mesh.py`
に孔の内径（最も狭い部分、mid-dielectric）をCLI引数で上書きできる機能を追加
（新規`[inner_diameter_um]`引数、outer径65µmは固定）。`geometry/gem_unit_cell.py`
に`_cone_or_cylinder`ヘルパーを新設（OCCの`addCone`は内外径が完全に同じだと
「degenerate cone」としてエラーになるため、その場合`addCylinder`にフォールバック
— cylindrical孔＝biconical taperの内径=外径の極限、として扱えるようにした）。

4ケースを`single_gem100_field`（GEM1単体、実条件そのまま）で比較:

| ケース | 内径 | Mean gain (30 events) |
|---|---|---|
| A（現状） | 35µm | 30.9 |
| B | 45µm | 47.1 |
| C | 55µm | 54.0 |
| D（cylindrical） | 65µm | 64.8 |

### 結果: taper形状を変えてもgenuine extractionは変わらずほぼ0%

`xe`/`ye`が領域境界（単段GEM100は3x3タイル化していない単一セルなので、
境界アーティファクトの影響がここでも大きい: 全endpointの15-20%）にある
ものを除外した「genuine」endpointだけで見ると、GEM1の底（z<-64µm、59µmの
foil厚みに5µmのマージン）まで実際に抜けた電子は**4ケース全てでほぼゼロ**
（769〜1664件のgenuine endpoint中、0〜1件）。

孔を大きく広げる（gainは2倍以上に増加）、あるいは完全にcylindricalにしても、
**電子が孔を実際に脱出する割合は変わらなかった**。genuine endpointのz分布も
4ケースともほぼ同じ（中央値-50〜-52µm、GEM1底面近傍に集中）。

**→ biconical taper形状（65→35→65）自体が主因という仮説は反証された。**
gainが増える（孔が広いほど電離しやすい）のは直感通りだが、それでも生成された
電子が実際に孔から出られない、という核心部分は形状非依存。

### 既知の限界

`single_gem100_field`は単一セル（3x3タイル化していない）なので、境界
アーティファクトの寄与（15-20%）が大きく、genuine抽出の統計（0〜1件）は
サンプルサイズが小さい。より確実にするなら3x3タイル化した単段GEM100
モデルで再確認する余地はあるが、cylindrical（最も極端な形状変更）でも
改善が見られなかったことから、taper形状が主因である可能性は低いと判断。

## 2026-09-23: field-line extraction test → 電場自体は下流に接続している（軸に近ければ）

electron avalanche（拡散・確率的散乱あり）を介さず、純粋な静電場だけで
「孔から入れたseed点が最終的にどこへ向かうか」を決定論的に追跡する新規マクロ
`macros/trace_field_lines.cpp`を作成（`ComponentElmer::ElectricField()`を
直接呼び、-E方向に固定ステップ(デフォルト0.01µm)でEuler積分、他の輸送計算
は一切介さない）。GEM1(`single_gem100_field`)の孔上端から、半径rを変えて
seedを撒いた結果:

```
r=0, 8, 16 um:  100% が2mm下流まで壁に一切衝突せず到達 (max_steps_reached)
r=24, 32 um:    80% が孔の中（foil内部）で壁に衝突 (stuck_in_foil)
```
（孔の外径=32.5µm、内径=17.5µm）

**電場ライン自体は、軸に近い（r≲20µm程度）経路については問題なく下流まで
接続している。** 孔の外側寄り（wallに近いr）だけが電場的にも壁に向かう。
つまり「電場配置そのものが下流への接続を妨げている」わけではなく、
**avalanche中に生成されるsecondary electronが（強い散乱・電離により）
軸から外れた位置に生まれてしまい、その時点で既に「壁行きの」電場ライン領域に
入ってしまう**、という確率的な効果が本質的な原因である可能性が高まった。
神経質な孔のneckサイズ（r_in=17.5µm）に対して、複数世代にわたる荒い
avalanche過程で生成点が軸から外れやすいこと自体が、この低い透過率の
根本メカニズムと考えられる。

## 2026-09-23: GEM電圧3倍 → 2000（avalanche size上限）に到達、genuine extractionはごくわずかに改善

`SetMaxElectronEnergy(500)`を使い、`single_gem100_field_v3x`で3イベント
完走（実行時間の問題で20イベントは断念、詳細は上記「実行環境の壁」参照）。

```
Event 0-2: gain = 2000 (EnableAvalancheSizeLimit の上限に完全に到達)
genuine extraction (境界アーティファクト除外): 5/4841 (0.103%)
```

ベースライン(1倍電圧)の0/769 (0%)と比べると、確率としてはわずかに改善
（0% → 0.1%）しているが、依然として非常に小さい。電圧を3倍にしても
avalanche gainは(上限に張り付くほど)大きく増えるのに対し、genuine
extractionの改善はごく僅かに留まる — 電場の「強さ」を上げるだけでは
根本解決しないことを裏付ける。

## 2026-09-23: plane-crossing判定のバグ修正 — transfer gap全体で徐々に失われている、単一原因ではない

外部レビューから、`analyze_plane_crossings.py`（旧版）の`z_min < z_plane`判定は
「そのplaneより下流のどこかにGEM2内で新しく生まれた電子」も誤って
「planeを通過した」とカウントしてしまう、という重大な指摘があった
（GEM2内部で電離により生まれた電子は最初から`z < GEM2 top`を満たすため）。
確認したところ、実際に**389件中30件(2.2%)、GEM2の z 範囲内で「生まれた」
track**が存在しており、指摘の通りだった。

### 修正内容

`geometry/analyze_plane_crossings.py`を全面改訂:
- **真のplane crossing判定**: `z_i >= threshold` かつ `z_{i+1} < threshold`
  という連続する記録点のペアが存在するかで判定（「born below」を除外）。
- **birth region分類**: 各trackの最初の記録点がどの領域（drift/GEM1/
  transfer1/GEM2/...）にあるかを記録。
- **GEM1脱出cohortでのfunnel解析**: 「GEM1 bottomを真に通過した電子」を
  cohortとして固定し、そのcohortが後続のplane（transfer gapの25/50/75%、
  GEM2 top-50µm/-10µm、GEM2孔入口、GEM2 bottom）をどこまで通過するかを
  段階的に追跡（新しく生まれた電子を混入させない）。
- **GEM2孔入口の定義**: plane通過点の(x,y)を線形補間し、3x3タイル化された
  25個の孔のどれかの半径内にあるかで判定（z平面だけでなく実際の孔の中に
  入ったかを区別）。
- **最終fate分類**: `export_avalanche_trajectories.cpp`に`status`
  branchを追加（Endpoints treeにはtrack番号がなくjoinできないため、
  Trajectories tree自身にstatusを持たせた）。cohortの各電子の最終記録点
  のstatus + z領域で分類。

### 結果（triple_gem_field、50イベント、1361 avalanche electrons）

```
GEM1-extracted cohort (genuine crossing): 582 / 1361 (42.8%)

  T1 25%                    :  196 ( 33.7% of cohort)
  T1 50%                    :  110 ( 18.9% of cohort,  56.1% of T1 25%)
  T1 75%                    :   59 ( 10.1% of cohort,  53.6% of T1 50%)
  GEM2 top-50um             :   31 (  5.3% of cohort,  52.5% of T1 75%)
  GEM2 top-10um             :   31 (  5.3% of cohort, 100.0% of GEM2 top-50um)
  GEM2 top (hole entrance)  :    8 (  1.4% of cohort,  25.8% of GEM2 top-10um)
  GEM2 bottom               :    0 (  0.0% of cohort)

  GEM2 top-10um到達8件中、実際にGEM2の孔内に入ったのは 8/8 (100%)
    （↑「GEM2 top (hole entrance)」自体が孔内判定なので同じ8件）
```

最終fate（cohort582件）: 71.3%がtransfer gap 1内、27.0%がGEM1内
（境界付近を行き来した後に戻って吸収されたと見られる）、1.4%がGEM2内で
`StatusLeftDriftMedium`。

**追加検証（境界アーティファクトか否か）**: transfer gap 1内で死亡した415件のうち
x/y領域境界(|x|≈210µm or |y|≈364µm、3x3タイル境界)にフラグが立たなかった
残り202件について、最終位置(x,y)と**GEM1側**の25個の孔中心（タイル化済み）
との最短距離を調べたところ、median 37.9µm・198/202(98%)がGEM1孔半径
(32.5µm)の2倍以内に収まっていた。すなわちこの202件は「ドメイン境界での
数値アーティファクト」ではなく、**GEM1のいずれかの孔のすぐ近くで、脱出後
まもなく（z_last中央値が transfer gapの深部でなくGEM1出口寄り）GEM1自身の
下面Cu（孔周囲の平坦な銅面）に再吸収された、という物理的に妥当な描像**を
裏付ける。→ transfer gap 1内の415件の内訳は「約半分(213件)が3x3タイル化
境界での数値アーティファクト、残り約半分(202件)がGEM1孔近傍での再吸収と
いう genuine物理」の混在と結論。

**この結果から分かること**: GEM1→GEM2は単一のcliff（崖）ではなく、
**transfer gap全域にわたって徐々に失われている**（25%地点で既に2/3が
失われ、以降も各区間で約半分ずつ減っていく、指数関数的な減衰パターン）。
「transfer gap 1内でsolid materialに衝突」とされた415件のうち、
約半分(213件、51.3%)はx/y領域境界ちょうど（3x3タイルの端）にあり、
**依然として境界アーティファクトが無視できない規模で残っている**ことも
判明。残り約半分は境界とは無関係で、GEM1脱出直後（z≈3711µm、GEM1底面の
すぐ下）で失われており、GEM1自身の下面Cu（孔以外の平坦な銅面）への
再吸収と見られる。さらに、GEM2の高さまで到達した電子(31件)のうち
実際に孔に入ったのは8件（25.8%）のみで、**GEM2の孔への収集効率自体も
低い**ことが分かった。

**→ 「transfer gap輸送」と「GEM2孔への収集」の両方が効いており、
単一の原因に絞り込めない。** 定量化できたので、以降はこの内訳を元に
改善余地（3x3よりさらに広いタイル化で境界アーティファクトを削減できるか、
等）を検討できる。

## 現時点の結論と次の一手候補

- 電場の「向き」（仮説1）・「大きさ」（transfer field scan、GEM電圧3倍scan）・
  注入距離（仮説2）・注入方向（仮説3）・単一セル境界（仮説4、ただし訂正あり）・
  統計不足（仮説5）・medium連続性・3段スタック特有性・
  **tracking解像度（仮説a、反証）**・**孔のtaper形状（反証）**・
  **単一の"崖"原因（2026-09-23、反証）**は、いずれも唯一の原因ではないと
  切り分けられた。
- **field-line extraction testにより、電場自体は軸に近い経路については
  下流に正しく接続していることを確認** — 「電場配置が悪い」という仮説
  （仮説C）も否定的。
- 上記の訂正により、「GEM1が電子をほぼ完全にブロックする」という当初の描像から、
  「各段で有限の抽出効率がある、カスケード的な透過率低下」という描像に更新。
  さらに2026-09-23の訂正により、この「低下」はtransfer gap全域にわたる
  徐々の減衰（一部は依然として境界アーティファクト）と、GEM2孔への
  収集効率の低さ（26%程度）の組み合わせであることが判明。
- 現時点で最も有力な描像: **孔が非常に狭い(r_in=17.5µm)ため、avalanche過程で
  生成されるsecondary electronの多くが軸から外れた位置に生まれ、その位置
  からの電場ライン自体が既に壁を向いている**（field-line extraction test
  で確認）ことに加え、**transfer gap内での拡散による横方向の広がりが
  GEM2の孔サイズに対して無視できない**ため、GEM2到達時点で孔を外れやすい
  — geometryのバグでもtrackingのバグでもなく、この特定の孔径・電圧・
  ピッチの組み合わせにおける現実的な（望ましくない）物理的帰結である
  可能性が高い。
- 残る作業: (i) 境界アーティファクトを減らすため5x5タイル化を試す、
  (ii) 統計をさらに増やしてGEM2孔収集効率をもっと正確に見積もる、
  (iii) この効率が実機のGEM透過率（文献値）と比べて妥当な範囲か評価する、
  (iv) mesh convergence test（孔近傍のメッシュを細かくしても結果が
  変わらないか）、(v) 100µm GEM孔形状の文献的な裏付け（現状は
  Kim et al. 2020のTable 1数値をbiconicalと仮定しているだけで、実際の
  断面写真等では未確認）、(vi) 単段GEM100モデルのtransfer field scan
  (2 vs 10kV/cm)をこの修正済みplane-crossing判定で再評価する（未実施）。
- `e0`（初期エネルギー）scanは優先度が低いとの調査方針書の判断に従い、まだ未実施。

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
