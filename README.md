# GEM-garfield-simulation

Triple-GEM検出器の静電場・電子雪崩（avalanche/transport）をシミュレーション
するためのframework。J-PARC E72 (HypTPC) の3段GEMを対象に、将来的な
Glass GEMへの展開も見据える。

使用する主なツール: **Gmsh** (geometry/mesh) → **Elmer FEM** (静電場ソルブ)
→ **Garfield++ / Magboltz** (microscopic avalanche simulation) → **Python**
(uproot/matplotlib/PyVista、解析・可視化)。

`GEM_Garfield` (https://github.com/hyptpc/GEM_Garfield) の設計思想
（パラメータ駆動でGmsh/Elmer入力を生成する）を参考にしつつ、独立に作り直したもの。

![電子雪崩アニメーション](results/img/avalanche_demo.gif)

上: 1イベント分の電子雪崩が3段GEMスタックを通過していく様子（斜め視点・
真横断面を並べて表示、下段に瞬間瞬間の電子数）。
`visualization/plot_avalanche_animation.py`で生成（再現・差し替え手順は
同スクリプトのdocstring参照）。

## 対象デバイス

HypTPC (J-PARC E42/E45/E72共通) の3段GEMスタック。
出典: S.H. Kim et al., "Development of a time projection chamber for J-PARC hadron physics program",
J. Phys.: Conf. Ser. 1498 (2020) 012023.

- 3層構成: 100 µm GEM → 50 µm GEM → 50 µm GEM (ドリフト側からパッド側。
  Kim et al. 2020論文の50→50→100µmとは異なる並び順を採用)
- ガス: P-10 (Ar 90% + CH4 10%), 1 atm

詳細パラメータは `geometry/gem_params.py`, `geometry/*_field_model.py` を参照。

## 現在のproduction condition

| 項目 | 値 |
|---|---|
| GEM段構成 | 100µm(GEM1, ドリフト側) → 50µm(GEM2) → 50µm(GEM3, パッド側) |
| GEM電圧 | GEM1 = 526.125 V, GEM2/GEM3 = 350.75 V (voltage multiplier 1.15x適用後) |
| Drift / Transfer / Induction field | 130 / 2000 / 3100 V/cm |
| ガス | P-10 (Ar 90% + CH4 10%), 1 atm、Penning transfer有効 |
| Tiling | 7×7 (`triple_gem_field_v1.15x_n7`)、9×9との比較で収束確認済み |
| Avalanche size limit | 20000 (`EnableAvalancheSizeLimit`) |
| baseName | `triple_gem_field_v1.15x_n7` |

各値の選定根拠・収束確認の詳細は `docs/reference.md`「現在のproduction
condition」および`docs/debugging_notes.md`を参照。再現コマンド一式は
`docs/reference.md`の同節にまとめてある。

## Workflow

```
ジオメトリ生成 (Gmsh Python API) → メッシュ
  → Elmer (ElmerGrid/ElmerSolver, 静電場ソルブ) → Garfield++ (電子雪崩シミュレーション)
  → Python可視化・解析 (PyVista/matplotlib/uproot)
```

各段が出力するもの: Gmsh → `.msh`メッシュ、Elmer → 電場解 (`.result`)、
Garfield++ → ROOT (`Endpoints`/`Trajectories` tree)、Python → 画像・
インタラクティブHTML。詳細は `docs/reference.md` §1-2参照。

## Quick start

`triple_gem_field`（3段GEM、baseline設定）でパイプライン全体を動かす例
（C++マクロは先にビルドが必要、`docs/reference.md`「C++マクロのビルド」参照）:

```bash
# 1. ジオメトリ・メッシュ生成
cd geometry && python3 build_triple_gem_field_mesh.py

# 2. Elmer電場ソルブ
cd ../elmer && bash run_field_solve.sh triple_gem_field

# 3. 電子雪崩の全軌跡を計算 (Garfield++)
cd ../macros/build
./export_avalanche_trajectories ../../results/mesh/triple_gem_field \
  ../../resources/ar_ch4_90_10.gas 5 -0.2029 0.8405 0.4235 0.021 \
  0.03637306695894642 0.1 0.0005 ../../results/root

# 4. 可視化・解析
cd ../../visualization && python3 plot_triple_gem.py triple_gem_field
cd ../geometry && python3 analyze_plane_crossings.py \
  ../results/root/triple_gem_field_avalanche.root
```

`zSensorMin`等の意味・値の求め方は`docs/reference.md` §2参照。3段GEM
production condition の完全な再現コマンドは同ファイル §2.5参照。KEKCC
LSFでのバッチ並列実行は`batch/run_avalanche_batch.py`（詳細は同ファイルの
docstringと`docs/reference.md` §5）。

## Repository structure

```
geometry/       Gmsh Python APIによるジオメトリ・メッシュ生成、plane-crossing等の解析スクリプト
elmer/          .sif生成スクリプト、誘電率定義など
macros/         Garfield++実行マクロ (単段テスト、3段本番等) + CMakeビルド設定
include/        C++マクロ用のvendored third-partyヘッダ (nlohmann/json)
visualization/  PyVistaベースの3D可視化・診断プロット・avalancheアニメーション
batch/          KEKCC (LSF/bsub) でのavalanche計算並列化
resources/      ガステーブル (P10) 等
results/        全パイプライン段の出力（mesh/root/img/html/json）
docs/           詳細ドキュメント（下記「ドキュメント」参照）
```

## Outputs

`results/`配下にファイル種別ごとに整理される（詳細は`docs/reference.md`
§3参照）:

- `results/mesh/` — Gmsh出力メッシュ、Elmer solve結果
- `results/root/` — 電子endpoint/trajectory (ROOT TTree、`uproot`で読める)
- `results/img/` — 静的な検証用画像・GIFアニメーション (git管理対象は`*.png`と`avalanche_demo.gif`のみ、他は再生成可能)
- `results/html/` — PyVistaのインタラクティブ3Dビューア
- `results/json/` — geometry/field sampleのメタデータ

## Current status

- Triple-GEM geometry・電場計算・avalanche simulation: 動作確認済み
- KEKCC batch (bsub) での並列実行: 動作確認済み
- Stage-by-stage transmission解析 (plane-crossing analysis): 動作確認済み
- Python可視化レイヤー (geometry/field/avalanche overlay、z方向診断プロット): 動作確認済み
- Finite-size (tiling) convergence: 7×7で収束確認済み (9×9との比較)
- Avalanche size limit convergence: 20000で収束確認済み（小統計での確認、詳細は下記「既知の制約」参照）
- Production-level absolute gain validation (voltage scan・文献比較): 進行中 ([issue #15](https://github.com/rjsaito0519/GEM-garfield-simulation/issues/15))

## 既知の制約

- **注入条件**: 現在の一次電子はGEM1ホール軸近傍への簡略化された注入
  （診断目的、実機のdrift/diffusion後の分布を再現するものではない）
- **avalanche size limit convergence**: 各sweep点10-20イベントの小統計に
  基づく判断であり、厳密な収束証明ではない
- **Periodic boundary condition**: 未実装（現状は有限タイルでの近似、[issue #15](https://github.com/rjsaito0519/GEM-garfield-simulation/issues/15)）
- **誘電体近似**: dielectric layerは比誘電率のみでモデル化（詳細構造は簡略化）

## ドキュメント

- `docs/installation_guide.pdf`（日本語版: `docs/installation_guide_ja.pdf`。
  LaTeXソースはそれぞれ`docs/installation_guide.tex` /
  `installation_guide_ja.tex`）— Gmsh/Elmer/Garfield++/ROOT/Pythonの
  詳細なインストール手順（バージョン互換性の制約、ビルド順序、既知の
  落とし穴を含む）
- `docs/reference.md` — パイプラインの実行手順、production condition再現、
  `results/`出力構成、ROOT出力スキーマ、efficiency定義
- `docs/debugging_notes.md` — 開発中の調査ログ・仮説検証の記録（日付順）
- `docs/pipeline_gotchas.md` — Gmsh/Elmer/Garfield++/ROOT/Python連携で踏んだ落とし穴集
- 関連する主な GitHub Issues: [#15](https://github.com/rjsaito0519/GEM-garfield-simulation/issues/15) (periodic boundary・voltage scan・文献比較、今後の作業)

## 実行環境

| ツール | バージョン |
|---|---|
| Gmsh (CLI) | 4.13.1 |
| Gmsh Python API | 4.15.2 |
| Elmer | v9.0 |
| Garfield++ | パッケージバージョン文字列 "0.3"（ROOT 6.40.04向けにビルド） |
| ROOT | 6.40.04（Python/解析用とGarfield++ビルド用で統一） |
| CMake | 3.31.8 |
| gcc | 11.5.0 |

いずれもこの実行アカウント内にローカルインストールされたもので、パスは環境固有
（`elmer/run_field_solve.sh`, `macros/CMakeLists.txt`が実際に使っているパスの
定義箇所）。Garfield++の再ビルド手順（ROOTバージョンを上げた場合など）は
`docs/pipeline_gotchas.md`を参照。
