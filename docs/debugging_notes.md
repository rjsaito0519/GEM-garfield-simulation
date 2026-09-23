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

### P(GEM1 bottom通過 | r_birth) — off-axis secondary仮説の直接検証

外部レビューの指摘で、「off-axis secondary electronが壁向きfield lineに
乗る」という仮説がまだ直接測定されていなかった点を指摘された。
`analyze_plane_crossings.py`に、GEM1内で生成された電子(1263件)について
生成位置の動径座標 `r_birth`（最も近いタイル化GEM1孔中心からの距離）を
求め、`r_birth` binごとにGEM1 bottom通過率を集計する機能を追加した。

```
r_birth in [  0.0,   5.0) um:   73 /  116 extracted ( 62.9%)
r_birth in [  5.0,  10.0) um:  149 /  242 extracted ( 61.6%)
r_birth in [ 10.0,  15.0) um:  180 /  326 extracted ( 55.2%)
r_birth in [ 15.0,  20.0) um:  113 /  304 extracted ( 37.2%)
r_birth in [ 20.0,  25.0) um:   46 /  157 extracted ( 29.3%)
r_birth in [ 25.0,  30.0) um:   10 /   79 extracted ( 12.7%)
r_birth in [ 30.0,  35.0) um:    1 /   39 extracted (  2.6%)
```

（GEM1孔半径: hole_inner=17.5µm、hole_outer=32.5µm）

**きれいな単調減少（63%→3%）を確認** — GEM1孔の中心軸近くで生まれた
secondary electronほどGEM1 bottomを通過しやすく、孔壁に近い場所で
生まれた電子ほど通過できない。これはfield-line extraction test
（軸に近いseedは100%下流に接続、r=24/32µmのseedは80%が壁に捕まる）
と定性的に一致しており、「off-axis secondaryがwall-directedな
field lineに乗って失われる」という仮説を**直接的なr_birth測定で
裏付けた**（従来はfield line側の証拠のみで、実際のavalanche電子の
生成位置分布との対応は未確認だった）。

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

## 2026-09-23: 単段GEM100 transfer field scan (2 vs 10 kV/cm) を修正済み指標で再評価

「単段100µm GEM単体でのテスト」「transfer電場scan（2 kV/cm → 10 kV/cm）」
（本ファイル上の方の節）は、当時**endpointの最終位置/statusのみ**で
「genuine孔壁損失は100% GEM1の箔厚み内に収まり、transfer gap到達は
0件、電場を5倍にしても変化なし」と結論していた。この結論を、修正済みの
真のplane-crossing判定で再評価した。

### 手法

新規`geometry/analyze_single_gem_plane_crossings.py`を作成（`analyze_
plane_crossings.py`の`_crossed`等を再利用、3段スタック用ロジックとは
別に単段GEM用のplane定義・birth region定義を実装）。GEM bottom
（z=-59µm）を真に通過した電子を「GEM-extracted cohort」と定義し
（3段スタックの`analyze_plane_crossings.py`と同じ流儀で、GEM topの
通過を前提条件にはしない — secondaryの大半はGEM内部で生まれるため）、
transfer gap内 10/25/50/75/90%地点への通過を段階的に追跡した。

`single_gem100_field`（tf=2000V/cm、既存の解済みmesh）と、新規に構築・
solveした`single_gem100_field_tf10000`（tf=10000V/cm）それぞれで
50イベントの`export_avalanche_trajectories`を実行（`status`branch
込みで再生成、旧ファイルはstatus branchがなく統計も1イベントのみ
だったため作り直し）。

### 結果

```
                              tf=2000 V/cm         tf=10000 V/cm
avalanche electrons (total)  1559                  1009
GEM-extracted cohort         732 (47.0%)           453 (44.9%)
  transfer 10%                66 ( 9.0% of cohort) 242 (53.4% of cohort)
  transfer 25%                 3 ( 0.4% of cohort)  75 (16.6% of cohort)
  transfer 50%                 0 ( 0.0% of cohort)   8 ( 1.8% of cohort)
  transfer 75%                 0 ( 0.0% of cohort)   3 ( 0.7% of cohort)
  transfer 90%                 0 ( 0.0% of cohort)   1 ( 0.2% of cohort)
```

### 単一セル（未タイル化）境界アーティファクトの確認

`single_gem100_field`は3x3タイル化されておらず**単一の六角形セルのみ**
なので、その側面(x/y)境界は3段スタックの3x3タイル境界よりも孔にずっと
近い。「transfer gap内でStatusLeftDriftMediumにより死亡」した電子の
最終(x,y)を確認したところ:

```
tf=2000 V/cm : 520件中 292件 (56.2%) が側面境界付近
tf=10000V/cm : 405件中 376件 (92.8%) が側面境界付近
```

境界近傍でない残り（tf2000で228件、tf10000で29件、境界許容を50µmまで
緩めるとさらに減る）は、そのほぼ全てがz=-59µm（GEM底面Cuの平坦面）
ちょうどに着地しており、GEM1自身の底面への再吸収（先述のtransfer gap 1
での202/415件と同種の物理現象）と判断できる。

### 解釈・従来結論の修正

- **GEM bottom抽出効率自体(47.0% vs 44.9%)はtransfer電場にほぼ依存しない**
  — これは従来の結論と整合的（GEM内部・孔ネック近傍の局所電場が支配的
  という描像を裏付ける）。
- 一方、**抽出後にどこまでtransfer gapへ侵入できるかは電場に強く依存する**
  — tf2000ではcohortの9.0%しか10%地点(200µm)へ届かず25%地点以降は
  ほぼ皆無なのに対し、tf10000では53.4%が10%地点、16.6%が25%地点、
  少数だが50-90%地点まで届く例もある。**「電場を5倍にしても孔からの
  脱出は全く改善しなかった」という従来の結論は不正確だった**
  — 実際には侵入深さについて明確な改善が見える。
- ただし、この深い侵入の大部分（tf10000で93%、tf2000でも56%）は
  **単一セルの側面境界アーティファクトと強く相関しており**、genuineな
  物理的透過なのか数値的アーティファクトなのか、現状の未タイル化
  セットアップでは十分に切り分けられない。3段スタックのGEM1と違い、
  この単段テストはタイル化されていないため、3段スタックより深刻な
  境界アーティファクトの影響を受けていると考えられる。
- **今後**: 単段GEM100テストベッドも3x3タイル化した上で同じscanを
  やり直すのが、この電場依存性を確定させるための次のステップ。

### 従来の「0%で電場に無反応」という結論への影響

3段スタックのGEM1→GEM2損失の主要因（狭い孔径によるoff-axis secondaryの
壁損失、および孔への収集効率の低さ）についての結論は変わらない
（transfer電場はGEM抽出効率自体には効いていないため）。ただし、
transfer gap内での輸送距離について「電場を強めても全く改善しない」と
断定していた部分は、今回の再評価で**部分的に撤回**する — 電場依存性は
確かに存在するが、単一セル境界アーティファクトと未分離であり、定量的な
結論は保留とする。

## 2026-09-23: 単段GEM100テストベッドを3x3タイル化 → transfer gap侵入深さの電場依存性を確定

前節の再評価で、「transfer gapへの侵入深さは電場に依存するが、深い侵入の
56-93%が単一セル（未タイル化）の側面境界アーティファクトと相関しており
切り分けられない」という留保付きの結論を残した。3段スタックと同じ
3x3タイル化を単段GEM100テストベッドにも適用し、この留保を解消した。

### 変更内容

`geometry/single_gem_field_model.py`の`SingleGemTestConfig`に
`n_cells_x`/`n_cells_y`（デフォルト3, 3、`triple_gem_field_model.py`の
`TripleGemTestConfig`と同じ流儀）を追加。`build_single_gem_field_model`で
`hole_centers()`（単一セル）ではなく`hole_centers_tiled()`を使い、
`_add_gas_box`・`build_gem_layer`・`build_hole_gas_volumes`に
`half_extent_x/y_cm`（3x3タイル footprint分）を渡すよう修正。
`geometry_info`の`half_extent_x/y_cm`もタイル済みの値に更新（macro側が
これを`model_info.json`経由で単一の情報源として参照するため）。

これにより`single_gem100_field`（tf=2000, tf=10000両方）のmeshを
再構築・再solve（21785ノード→303097ノード、Elmer収束は各48-50秒、
問題なし）、`export_avalanche_trajectories`を新しい半径・境界で
50イベントずつ再実行した。

### 結果: タイル化前後の比較

```
                              未タイル化(単一セル)          3x3タイル化
                              tf2000    tf10000            tf2000    tf10000
GEM-extracted cohort          732/1559  453/1009            491/1140  470/1689
  (% of all avalanche e-)     (47.0%)   (44.9%)             (43.1%)   (27.8%*)
  transfer 10%                 9.0%      53.4%               40.1%     80.6%
  transfer 25%                 0.4%      16.6%               32.2%     77.2%
  transfer 50%                 0.0%       1.8%               20.0%     65.3%
  transfer 75%                 0.0%       0.7%               12.4%     50.9%
  transfer 90%                 0.0%       0.2%                8.8%     43.2%
  died-in-transfer-gap のうち
  側面境界アーティファクト     56.2%     92.8%               46.5%     39.7%
```

（*tf10000では全avalanche電子中44.3%がtransfer gap自身の中で新たに
生まれている — 5倍という非現実的に強い電場のため、GEM孔外のオープンな
ガス中でもTownsend avalancheが進行しているとみられる。GEM-extracted
cohortの絶対数(470)自体は未タイル化(453)とほぼ変わらないため、比率の
低下はGEM抽出効率自体が下がったからではなく分母が膨らんだため。）

### 解釈

- **タイル化により、transfer gap侵入は劇的に「本物」だと分かった**:
  tf2000でもcohortの8.8%がtransfer gapの90%地点（GEM2位置相当、
  1800µm）まで到達する。未タイル化テストで「電場を強めても改善しない」
  としていた結論は、境界アーティファクトによる人為的な抑制だったことが
  確定した。
- **側面境界アーティファクトは残るが(40-47%)、3段スタックの transfer gap 1
  で見た水準(約51%)とほぼ同程度**まで下がった — もはや支配的要因ではなく、
  3段スタックの解析と同様「約半分が境界アーティファクト、残り半分が
  genuineな物理（GEM底面Cuへの再吸収や、gap内でのさらなる損失）」という
  扱いが妥当。
- **電場依存性は明確**: tf2000→tf10000で、90%地点到達率が8.8%→43.2%
  まで増加。ただしtf10000は非現実的に強い電場（5倍）であり、transfer
  gap内で新たな二次電離も起きているため、この特定の倍率を定量的な
  「realisticな電場依存性」として使うのは避けるべき（優先度ルールの
  「GEM電圧を極端に上げるtestの解釈には注意」と同じ理由）。今後
  1.0-1.3x程度の現実的なrange内でのfine scanが望ましい。

### 従来結論の最終的な位置づけ

「transfer電場を5倍にしても孔からの脱出は全く改善しなかった」という
当初の結論（endpointベース）は**誤りと確定**。修正済みのplane-crossing
指標＋タイル化されたgeometryにより、transfer gap侵入は電場に強く依存する
ことが明確になった。ただし、この結果がGEM1→GEM2の主要な損失原因
（off-axis secondaryのwall loss、GEM2孔への収集効率の低さ）の結論を覆す
ものではない — transfer電場はGEM抽出効率自体（GEM bottom crossing rate）
には影響しないため。

## 2026-09-24: 孔taper形状（biconical vs cylindrical）scanをタイル化geometryで再評価 → 結論は変わらず

前回の孔taper形状sensitivity scan（"2026-09-23: 孔形状..."節）はタイル化前の
単一セルgeometryで行われており、`Mean gain`（`GetAvalancheSize`が返す
総生成電子数、GEM抽出とは別の量）だけを比較していた。単段GEM100テスト
ベッドを3x3タイル化した今、修正済みplane-crossing指標（genuine GEM bottom
通過率）で同じ4ケースをやり直した。

### 手法

`single_gem100_field`（内径35µm、タイル化済み、既存）に加え、
id45/id55/id65を`build_single_gem100_field_mesh.py 2000 1.0 <id>`で
タイル化geometryとして再構築・再solve（各45-47秒で収束）、50イベントで
`export_avalanche_trajectories`を再実行。

### 結果

```
内径(µm)   avalanche e-   GEM-extracted cohort   transfer 90%到達
  35(現状)   1140          491 (43.1%)             8.8% of cohort
  45         1586          607 (38.3%)             9.6% of cohort
  55         2633         1022 (38.8%)              7.9% of cohort
  65(円筒)   4216         1565 (37.1%)              7.6% of cohort
```

孔が広いほどavalanche電子の絶対数（≈gain）は大きく増える（前回の
Mean gain 30.9→47.1→54.0→64.8という結果と定性的に整合）一方、
**genuine GEM抽出効率（GEM bottom通過率）もtransfer gap侵入の深さも、
4ケースでほぼ一定（抽出37-43%、90%地点到達7.6-9.6%）**。

### 結論

**「孔のtaper形状(biconical vs cylindrical)が主因ではない」という前回の
結論は、修正済みplane-crossing指標＋タイル化geometryでも変わらず確認
された。** 孔を広げるとavalanche gain自体は増えるが、抽出効率・輸送効率
にはほとんど影響しない。孔径ではなく、GEM孔内部の局所電場形状（off-axis
secondaryの発生位置とfield line方向の関係、2026-09-23の`r_birth`解析で
確認済み）がより支配的な要因と考えられる。

## 2026-09-24: field-line tracerのstep size convergence確認 → 数値的に収束済み

`macros/trace_field_lines.cpp`（固定ステップEuler積分）の結果を物理的な
証拠として使う前に、ステップ幅への依存性を確認した。タイル化済みの
`single_gem100_field`上で、GEM1の孔（外径32.5µm、r=0/8.125/16.25/24.375/
32.5µmの5リング×8方位=33本）から、step=0.02/0.01(デフォルト)/0.005µmの
3通りで再実行。

```
step=0.02um: downstream 17/33 (51.5%),        stuck_in_foil 16/33 (48.5%)
step=0.01um: max_steps_reached 17/33 (51.5%), stuck_in_foil 16/33 (48.5%)
step=0.005um: max_steps_reached 17/33 (51.5%), stuck_in_foil 16/33 (48.5%)
```

`downstream`と`max_steps_reached`はラベルは違うが同じ意味（foilを抜けて
open gas領域に達した後、mesh外へ出るか`maxSteps`上限に達したかの違いで
ラベルが変わるだけ — `maxSteps`をstep幅に対して固定しているため、step
を細かくすると同じstep数でカバーする距離が短くなり、mesh境界に届かず
"max_steps_reached"になりやすい。物理的な分類が変わったわけではない）。

**3種類のstep幅で、"foilを抜けたか/壁に吸収されたか"の内訳が完全に一致
（51.5% vs 48.5%）— field-line積分は数値的に収束していることを確認した。**
内訳も、近軸(r=0/8.125/16.25µm)の17本が抜け、外側(r=24.375/32.5µm)の
16本が壁に吸収される、という従来の定性的な結果（r≲20µmは100%下流、
r≳24µmは80%が壁）と一致しており、タイル化後のmeshでも同じ描像が保たれる
ことも確認できた。

## 2026-09-24: mesh convergence test → 収束済み、孔近傍メッシュは主因ではない

孔近傍のメッシュを細かくしても結果が変わらないかを確認した。
`build_single_gem100_field_mesh.py`に`_MESH_CURVATURE_OVERRIDE`環境変数
（`Mesh.MeshSizeFromCurvature`を上書き、この値を倍にすると曲面上の要素
サイズがおよそ半分になる — 当初`MeshSizeMin`を半分/4分の1にする案を
試したが**ノード数が全く変化せず**（303097→303097）、孔近傍では
`MeshSizeMin`が律速していないことが判明したため、`MeshSizeFromCurvature`
に切り替えた）を追加し、baseline(20, 303097ノード)に対し40（2倍細かい、
1776102ノード）でmesh再生成・Elmer再solve（約13分で収束）。

### 結果

```
                          baseline(curvature=20)   finer(curvature=40)
node数                    303097                    1776102
field-line分類(r方向)     downstream/stuck = 17/16  downstream/stuck = 17/16 (完全一致)
GEM-extracted cohort      43.1% (50 events)         41.2% (20 events)
transfer 90%到達          8.8% of cohort            9.1% of cohort
```

**field-line分類（決定論的な電場のみのテスト）は完全に一致。** avalanche
extraction効率・transfer gap侵入深さも、統計誤差（20 vs 50イベントの
違いによるばらつき、cohort~165-491件に対するBernoulli誤差は数%オーダー）
の範囲内で一致している。

### 結論

**孔近傍のメッシュ解像度は収束しており、主因ではない。** ノード数を
約6倍(303097→1776102)にしても結果は変わらないため、既存のbaseline
メッシュ（`Mesh.MeshSizeFromCurvature=20`）で十分と判断できる。
さらに4分の1（curvature=80、ノード数約700万と見積もられ、Elmer solve
だけで数十分〜時間オーダーになる可能性が高い）までは計算コストの都合で
未実施だが、20→40で既に完全収束しているため、追加のコストに見合う
情報は乏しいと判断し、優先度を下げる。

## 2026-09-24: 3段スタックを5x5タイル化 → transfer gap 1の境界アーティファクトを大幅削減

3段スタックのtransfer gap 1で「死亡」した電子の約51%が3x3タイルの
側面境界アーティファクトだった（2026-09-23の解析）。タイル数を5x5に
増やすことでこれが減るか確認した。

### 変更内容

`geometry/build_triple_gem_field_mesh.py`に2番目の位置引数`n_cells`
（デフォルト3、`n_cells_x/y`を両方この値に上書き、`SingleGemTestConfig`
と同じ流儀）を追加。BASE_NAMEに`_n{n_cells}`を付与（デフォルト値では
既存の`triple_gem_field`のまま、非デフォルト値のみ新規名前空間）。
また`geometry/analyze_plane_crossings.py`に3番目のCLI引数`n_cells`
（デフォルト3）を追加 — GEM2孔入口判定で使うタイル化孔中心リストが
実際のgeometryのタイル数と一致していないと、外側のタイルの孔が
リストから漏れて誤判定するため。

`triple_gem_field_n5`を構築・solve（842594→2603621ノード、Elmer収束
約13分）、50イベントで`export_avalanche_trajectories`を再実行。

### 結果

```
                              3x3タイル(既存)      5x5タイル(新規)
avalanche electrons           1361                 1145
GEM1-extracted cohort         582 (42.8%)          366 (32.0%)*
  T1 75%                       10.1% of cohort      33.6% of cohort
  GEM2 top-10um                 5.3% of cohort      29.0% of cohort
  GEM2 hole entrance            1.4% (8件)           9.0% (33件)
  GEM2 bottom                   0.0% (0件)           0.5% (2件、初めて非ゼロ)
  transfer gap 1で死亡した
  うち側面境界アーティファクト  51.3%                22.4%
```

（*別々の乱数シードによる独立実行のため、抽出効率自体の直接比較には
統計的なばらつきが乗る。birth region内訳を見ると5x5ではGEM2内生成
14.8%・GEM3内生成5.0%と、3x3(それぞれ2.2%・0%)より深いカスケードが
起きており、単純に電圧・geometryだけでなくrun間のシード差の影響も
混ざっている点に注意。）

r_birth解析（GEM1内生成電子、5x5）も3x3と同じ単調減少パターンを再現
（72.7%→54.6%→50.7%→38.3%→27.2%→20.3%→6.7%、3x3の62.9%→...→2.6%と
定性的に一致）— off-axis secondary仮説はタイル密度に依存しない頑健な
結果であることも確認できた。

### 結論

**5x5タイル化により、transfer gap 1の境界アーティファクト比率は
51.3%→22.4%まで大幅に削減された。** これにより、GEM2到達・孔収集・
GEM2通過（今回初めて2件のgenuineなGEM2完全通過を確認）の各段の
genuineな物理的効率がより正確に見積もれるようになった。5x5でも
境界アーティファクトは完全にはゼロにならない（22.4%残る）ため、
今後さらに広いタイル化（7x7等）や、計算コストとのトレードオフを
踏まえた判断が必要。

## 2026-09-24: realisticなtransfer field range(1.0-2.0x)でのfine scan → 単調な改善を確認

これまでのtransfer field scanは2kV/cm(baseline)と10kV/cm(5倍、非現実的に
強い電場、transfer gap内で新たな二次電離が起きるほど)の2点のみだった。
より現実的な1.0-2.0xの範囲（2000/2500/3000/4000 V/cm）でfine scanを行い、
5倍scanで見えた「電場を強めるとtransfer gap侵入が改善する」傾向が
現実的なrangeでも成り立つか確認した。

### 手法

タイル化済み`single_gem100_field`をベースに、tf=2500/3000/4000 V/cmの
mesh/solve/50イベントavalanche exportを追加実行（各45-50秒で収束）。

### 結果

```
tf(V/cm)  GEM-extracted cohort   T10%    T25%    T50%    T75%    T90%
  2000      43.1%                40.1%   32.2%   20.0%   12.4%    8.8%
  2500      40.7%                45.6%   38.2%   24.7%   14.4%   10.9%
  3000      41.5%                51.1%   42.7%   27.8%   18.2%   12.9%
  4000      42.4%                53.8%   48.4%   33.1%   18.8%   15.5%
```

### 結論

**GEM抽出効率（~41-43%）は4点で完全にフラット** — realisticなrangeでも
電場非依存という結論を再確認。**transfer gap侵入深さは電場に対して
単調かつなめらかに改善**（90%地点到達率が8.8%→10.9%→12.9%→15.5%と
ほぼ線形に増加）。5倍(10kV/cm)scanで見られた傾向は、非現実的な極端条件
の産物ではなく、**現実的な1.0-2.0xの範囲でも同じ方向性の、なめらかな
連続的トレンドとして確認できた。**

## 2026-09-24: 統計を150イベントに増強 → GEM2完全通過・GEM3到達を初めて統計的に有意な数で確認

5x5タイル化した3段スタックの統計を50→150イベントに増やし、event単位の
内訳も出力できるようにした（従来の集計だけでは、電子同士の相関
[同じprimary eventのsecondaryは独立ではない]を無視した誤った不確かさ
評価になってしまうため）。

### 変更内容

`geometry/analyze_plane_crossings.py`に、GEM1脱出数・T1 75%到達数・
GEM2到達数・GEM2孔進入数をevent単位で表示する新セクションを追加
（将来のevent-level bootstrap不確かさ評価のための下地）。
`triple_gem_field_n5`で150イベントの`export_avalanche_trajectories`を
再実行。

### 結果

```
avalanche electrons: 4323 (150 events)
GEM1-extracted cohort: 1362 / 4323 (31.5%)
  T1 25%                    :  559 ( 41.0% of cohort)
  T1 50%                    :  514 ( 37.7% of cohort)
  T1 75%                    :  432 ( 31.7% of cohort)
  GEM2 top-50um             :  368 ( 27.0% of cohort)
  GEM2 top-10um             :  364 ( 26.7% of cohort)
  GEM2 top (hole entrance)  :  144 ( 10.6% of cohort, 99.3%が実際に孔内)
  GEM2 bottom               :   28 (  2.1% of cohort) ← 初めて統計的に意味のある数に
  GEM3 top                  :    3 (  0.2% of cohort) ← 3段目に初めて到達
  GEM3 bottom               :    0 (  0.0% of cohort)
```

r_birth解析（3086電子、GEM1内生成）は従来と同じ単調減少パターンを
高い統計で再現: 61.0%(r<5µm)→59.5%→50.8%→40.6%→26.5%→15.8%→0.9%(30-35µm)。

側面境界アーティファクト比率も23.2%（859件中199件）と、50イベントでの
推定(22.4%)とよく一致し、この数字が統計的に安定していることを確認。

### event単位の内訳（統計処理上、重要な発見）

150イベント中**67イベント(44.7%)はGEM1脱出電子が1つもゼロ**だった一方、
1イベントあたりの平均は9.08件（少数の高倍率イベントに大きく偏った
分布）。**電子を独立なBernoulli試行として扱うと不確かさを大幅に過小
評価してしまうことが、この極端な分布から直接確認できた** — 今後の
不確かさ評価はevent単位（例えばevent-level bootstrap）で行うべき、
という調査方針書の指摘が定量的に裏付けられた。

### 結論

**GEM2を完全に通過する電子(28件)、GEM3にまで到達する電子(3件)が、
初めて統計的に意味のある数で確認できた。** 3段GEMスタック全体としての
透過は非常に低いものの、ゼロではなく、各段でカスケード的に効率が
落ちていくという描像を定量的に裏付けている。

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
  からの電場ライン自体が既に壁を向いている** — これはfield-line extraction
  testでの示唆に加え、2026-09-23の`P(GEM1 bottom通過 | r_birth)`測定
  （r_birth 0-5µmで63%→30-35µmで3%というきれいな単調減少）により
  **直接確認された**。加えて、**transfer gap内での拡散による横方向の
  広がりがGEM2の孔サイズに対して無視できない**ため、GEM2到達時点(31件)
  でも孔に入るのは26%(8件)にとどまる。これらはgeometryのバグでも
  trackingのバグでもなく、この特定の孔径・電圧・ピッチの組み合わせに
  おける現実的な（望ましくない）物理的帰結である可能性が高い。
- 残る作業（未実施、優先度順）: (i) ~~単段GEM100モデルのtransfer field scan
  (2 vs 10kV/cm)をこの修正済みplane-crossing判定で再評価~~ → 2026-09-23実施済み。
  ~~単段テストベッドの3x3タイル化~~ → 2026-09-23実施済み（`SingleGemTestConfig`に
  `n_cells_x/y`追加）。**確定した結論**: GEM抽出効率自体は電場非依存
  (~43-47%)、transfer gap侵入深さは電場に明確に依存（tf2000で90%地点
  8.8%到達 vs tf10000で43.2%）。境界アーティファクトは3段スタックと
  同水準(40-47%)まで低下し、もはや支配的要因ではない。~~孔taper
  形状の感度scanを同判定で再評価~~ → 2026-09-24実施済み（タイル化
  geometryで4ケース再実行。**確定した結論**: 抽出効率37-43%、90%地点
  到達7.6-9.6%といずれもtaper形状にほぼ非依存 — 「taper形状は主因では
  ない」という結論を再確認）。~~field-line tracerのstep size
  convergence確認(0.02/0.01/0.005µm)~~ → 2026-09-24実施済み（3種類の
  step幅で内訳が完全一致(51.5%/48.5%)、数値的に収束済みと確認）。
  ~~mesh convergence test（孔近傍メッシュを1/2に細かくしても結果が
  変わらないか）~~ → 2026-09-24実施済み（ノード数6倍(303097→1776102)
  でもfield-line分類は完全一致、extraction効率も統計誤差内で一致 —
  収束済みと確認。4分の1(curvature=80)は計算コストの都合で未実施だが
  優先度は低い）。~~3段スタックtransfer gap 1に残る境界アーティファクト
  (約51%)を減らすため5x5タイル化を試す~~ → 2026-09-24実施済み
  （境界アーティファクト比率51.3%→22.4%まで削減、GEM2完全通過を初めて
  2件確認。7x7等さらに広いタイル化は計算コストとのトレードオフで
  今後の判断）。~~realisticなtransfer field range(1.0-1.3x程度)での
  fine scan~~ → 2026-09-24実施済み（2000/2500/3000/4000 V/cmの4点。
  **確定した結論**: 抽出効率は41-43%でフラット、transfer gap 90%地点
  到達率は8.8%→15.5%と単調・なめらかに改善 — 5倍scanで見た傾向が
  非現実的な極端条件の産物ではないことを確認）。~~統計を100-200event
  まで増やし、event単位で集計してBernoulli独立性の誤りを避ける~~ →
  2026-09-24実施済み（150イベント。**確定した結論**: GEM2完全通過28件
  (2.1%)・GEM3到達3件(0.2%)を初めて統計的に有意な数で確認。67/150
  (44.7%)のイベントでGEM1脱出電子ゼロという極端な分布を確認し、
  Bernoulli独立試行扱いが不適切であることを定量的に裏付け。
  `analyze_plane_crossings.py`にevent単位breakdown出力を追加）、
  (vii) 100µm GEM孔形状の文献的な裏付け（現状はKim et al. 2020のTable 1
  数値をbiconicalと仮定しているだけで、実際の断面写真等では未確認）。
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
