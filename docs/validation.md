# Validation: production baseline configuration and convergence結果

`docs/reference.md`が「どう実行するか」、`docs/debugging_notes.md`が「開発
過程で何を調べたか」なら、こちらは「現在のproduction condition一式と、その
妥当性確認（収束チェック）の結果」を一箇所にまとめたもの。値そのものの再現
コマンドは`docs/reference.md` §2.5、開発時の詳細な調査経緯は
`docs/debugging_notes.md`を参照。

## 1. Production baseline configuration

`baseName = triple_gem_field_v1.15x_n7` が現在のproduction condition。

| 項目 | 値 | 備考 |
|---|---|---|
| GEM段構成 | 100µm(GEM1, ドリフト側) → 50µm(GEM2) → 50µm(GEM3, パッド側) | Kim et al. 2020の50→50→100µmとは異なる並び順（意図的な設計選択、`geometry/triple_gem_field_model.py`参照） |
| GEM電圧 | GEM1 = 526.125 V, GEM2/GEM3 = 350.75 V | voltage multiplier 1.15x適用後（baseline 1.0xから段階的に引き上げ、経緯は`docs/debugging_notes.md`） |
| Drift / Transfer / Induction field | 130 / 2000 / 3100 V/cm | |
| ガス | P-10 (Ar 90% + CH4 10%), 1 atm, Penning transfer有効 | `resources/ar_ch4_90_10.gas`、r≈0.222, λ=0（doi:10.1088/1748-0221/5/05/P05002） |
| Tile数 (n_cells_x/y) | 7×7 | §2.1参照 |
| avalanche_size_limit | 20000 | §2.2参照 |
| collisionSteps | 100 (デフォルト) | §2.3参照 |
| Injection条件 | GEM1ホール軸近傍、半径0.0005cm(5µm)の円盤内に面積一様(r=R√U)、downstream向き | §4参照。**detector全体のacceptanceを再現するものではない** |
| e0 (初期電子エネルギー) | 0.1 eV | ほぼ熱エネルギー |

再現コマンド一式は`docs/reference.md` §2.5。

## 2. Convergence studies

### 2.1 Finite-size (tiling) convergence: 7×7 vs 9×9

`triple_gem_field_v1.15x_n7`と`_n9`（各50イベント、avalanche_size_limit=20000）を
`analyze_plane_crossings.py`で比較（2026-09-25/26）:

| 指標 (GEM1-extracted cohort比) | 7×7 | 9×9 |
|---|---|---|
| T1 25%→75%の低下 | 41.1%→39.2% | 41.1%→40.9% |
| GEM2 hole entrance | 15.3% | 16.1% |
| GEM2 bottom | 2.7% | 2.8% |
| GEM3 top | 0.3% | 0.4% |
| GEM3 bottom | 0.1% (5/8615) | 0.1% (10/10309) |
| 最終fateでの"StatusLeftDriftArea"(ラテラル脱出) | 0件 | 0件 |

統計誤差内で一致し、両方ともラテラル脱出が皆無（5x5で見られた34.2%の
大きな損失は完全に解消済み）。**7×7をproduction tile sizeとして採用**、
9×9への拡張は不要と判断。

### 2.2 avalanche_size_limit convergence

**小統計sweep(2026-09-25)**: `triple_gem_field_v1.15x_n5`上で
2000/5000/10000/20000を各10-20イベントでsweep:

| avalanche_size_limit | limit到達割合 | avalanche size (mean/median/max) |
|---|---|---|
| 2000  | 2/20 (10.0%) | 773.5 / 362.5 / 2005 |
| 5000  | 0/20 (0.0%)  | 1120.5 / 947.5 / 3635 |
| 10000 | 0/20 (0.0%)  | 716.1 / 423.0 / 3037 |
| 20000 | 0/20 (0.0%)  | 553.5 / 288.5 / 2318 |

**Production統計での確認(2026-09-30)**: 実際のproduction file(n7/n9、
各50イベント)ではlimit=20000への到達率が上記sweepより高く（n7 1/50=2.0%,
n9 5/50=10.0%）、小統計sweepだけでは不十分だったことが判明。そこで
avalanche_size_limit=50000で同一条件(n9は同一seed)で再計算し比較:

| ファイル | 到達割合(20000) | 到達割合(50000) | avalanche size max (20000 / 50000) |
|---|---|---|---|
| n7 | 1/50 (2.0%) | 0/50 (0.0%) | 20057 / 23928 |
| n9 | 5/50 (10.0%) | 0/50 (0.0%) | 20068 / 28591 |

GEM1-extracted cohort数・funnel各段の比率は両limit間でほぼ完全に一致
（n9: cohort数10309→10307、n7: 各funnel比率の差1%未満）。
**avalanche_size_limit=20000はproduction数値を歪めていないことを、
実際のproduction統計で確認済み。**

備考: 9x9スケールのavalanche jobをavalanche_size_limitを大きく上げて
再計算する際は`--slots-per-job 3`以上が必要（未指定だと`TERM_MEMLIMIT`、
9x9メッシュは元々5.6GB RSS必要でqueue既定の1slot=4GB上限を超過）。

### 2.3 collisionSteps convergence

trajectory export時のcollision point間引き間隔(1/5/20)をsweep。GEM1
extraction等の比率・avalanche size limit到達割合ともに、collisionSteps
値に対する系統的な傾向は見られなかった（10-20イベントの統計内で一致）。
よってproductionでは軽い設定（デフォルト値100）をそのまま使用する。

## 3. Standard quantity definitions

複数の解析スクリプトが別々のefficiency量を計算しているため、混同を
避けるためにここで一箇所にまとめる。

| 用語 | 定義 | 測定方法 |
|---|---|---|
| **Collection efficiency** | GEM上方の広い一様領域から注入された一次電子のうち、実際にホール開口部へ入った割合 | `geometry/analyze_collection_efficiency.py`。**単独GEM（一様上方電場）でのみ意味を持つ**定義 -- 3段スタック中のGEM2/GEM3は前段の非一様な雪崩出力を受け取るため、この意味でのcollection efficiencyは定義できない（次GEM進入率を参照） |
| **Local multiplication (avalanche size)** | collectionされた一次電子1個あたりの、そのGEM内での二次電子生成数（`track`数） | `analyze_collection_efficiency.py`の`Local multiplication`出力。`GetAvalancheSize()`の`ne`と同じ量で、"gain"とは呼ばない（下記Effective gain参照） |
| **Extraction efficiency** | collectionされた一次電子のうち、そのGEMの底面を実際に下向きに通過した（genuine crossing）割合 | `analyze_collection_efficiency.py`の`Extraction efficiency`出力、または`analyze_single_gem_plane_crossings.py` |
| **Transfer efficiency** | あるGEMを抜けた電子のうち、transfer gapを生き残って次段のGEM近傍に到達した割合 | `analyze_plane_crossings.py`のfunnel（例: "T1 75%"等の中間平面通過率） |
| **次GEM進入率 (next-GEM collection)** | 3段スタックのembedded文脈で、あるGEMの実際の（非一様な）雪崩出力のうち、次GEMの実ホール開口部へ入った割合 -- 上記collection efficiencyとは別概念、cascade特有の量 | `analyze_plane_crossings.py`の"GEM2 top (hole entrance)"等 |
| **Effective gain** | 1個の一次電子（あるいは1個の実イベント）あたり、最終的にreadout/induction面に到達した電子数 -- `GetAvalancheSize()`が返す"avalanche size"（`ne`、雪崩木全体で生成された総電子数、後で吸収されるものも含む）とは異なる | まだ標準出力として整備されていない（avalanche_size_limit convergence確認後の整備予定、issue #15） |

`GetAvalancheSize()`に対応する量は"avalanche size"または"local
multiplication"と呼び、"effective gain"とは呼ばない（event log・summary
両方で統一済み、2026-09-30）。

## 4. Injection condition とその限界

現在のbaseline production runで使用している一次電子の注入条件:

- GEM1ホール軸近傍
- 半径0.0005cm(5µm)の円盤内で面積一様（r = R√U、r = RUではない -- 後者は
  中心付近に偏るバイアスがある）
- downstream向き（GEM1からパッド側へ、実際のdrift電子の運動方向）

これは診断目的の簡略化された注入条件であり、実機のdrift/diffusionを経た
後の分布や、detector全体の受光面積(acceptance)を再現するものではない。
`analyze_collection_efficiency.py`が測るCollection efficiencyのように、
広い一様領域からの注入が必要な量を測る場合は、この設定のままでは使えない
（同スクリプトのmodule docstring参照）。将来的にrealisticなdrift-region
injectionを行う場合は別studyとする。

## 5. Known limitations

`README.md`「既知の制約」も参照。

- **Periodic boundary condition**: 未実装（現状は有限タイル(7×7)での近似、[issue #15](https://github.com/rjsaito0519/GEM-garfield-simulation/issues/15)）
- **誘電体近似**: dielectric layerは比誘電率のみでモデル化（詳細構造は簡略化）
- **Production-level absolute gain validation** (voltage scan・文献比較): 進行中（issue #15）
