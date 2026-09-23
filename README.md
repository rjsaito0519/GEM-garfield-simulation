# GEM-garfield-simulation

J-PARC E72 (HypTPC) の3段GEM電場・電子雪崩シミュレーション。
将来的に開発中のGlass GEMへの展開も見据える。
`GEM_Garfield` (https://github.com/hyptpc/GEM_Garfield) の設計思想（パラメータ駆動でGmsh/Elmer入力を生成する）を
参考にしつつ、独立に作り直したもの。

## 対象デバイス

HypTPC (J-PARC E42/E45/E72共通) の3段GEMスタック。
出典: S.H. Kim et al., "Development of a time projection chamber for J-PARC hadron physics program",
J. Phys.: Conf. Ser. 1498 (2020) 012023.

- 3層構成: 50 µm GEM → 50 µm GEM → 100 µm GEM (ゲート側からパッド側)
- ガス: P-10 (Ar 90% + CH4 10%), 1 atm

詳細パラメータは `geometry/gem_params.py`, `geometry/*_field_model.py` を参照
（`params/`によるYAML駆動化はまだ未実装、将来的な検討事項）。

## パイプライン

```
ジオメトリ生成 (Gmsh Python API) → メッシュ
  → Elmer (ElmerGrid/ElmerSolver, 静電場ソルブ) → Garfield++ (電子雪崩シミュレーション)
  → Python可視化 (PyVista/matplotlib)
```

実際にコマンドを叩いて再現する詳細手順は `docs/reference.md` を参照。

## ディレクトリ構成

```
geometry/       Gmsh Python APIによるジオメトリ・メッシュ生成スクリプト、Python可視化の一部
elmer/          .sif生成スクリプト、誘電率定義など
macros/         Garfield++実行マクロ (単段テスト、3段本番等) + CMakeビルド設定
include/        C++マクロ用のvendored third-partyヘッダ (nlohmann/json)
visualization/  PyVistaベースの3D可視化・診断プロット (issue #3)
resources/      ガステーブル (P10) 等
results/        全パイプライン段の出力（mesh/root/img/html/json、詳細はdocs/reference.md）
docs/           詳細ドキュメント（下記「ドキュメント」参照）
```

## ドキュメント

- `docs/reference.md` — パイプラインの実行手順、`results/`出力構成、ROOT出力スキーマ
- `docs/pipeline_gotchas.md` — Gmsh/Elmer/Garfield++/ROOT/Python連携で踏んだ落とし穴集
- `docs/debugging_notes.md` — GEM1→GEM2電子透過率問題の調査ログ（進行中、GitHub issue #2）
- `CLAUDE.md` — AIエージェント向けエントリポイント

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
定義箇所）。このリポジトリはグローバルな環境変数設定に頼らず、リポジトリ内の
セットアップスクリプトで明示的にパスを通す方針。

Garfield++の再ビルド手順（ROOTバージョンを上げた場合など）は
`docs/pipeline_gotchas.md`を参照。

## ステータス

- [x] Gmsh Python APIのセットアップ
- [x] 単段GEM(50µm)の単位胞ジオメトリ・メッシュ生成、可視化 (`geometry/build_single_gem.py`)
- [x] 単段GEMの電場マップ生成 (`geometry/single_gem_field_model.py`, `elmer/`, `macros/view_gem_field.cpp`)
- [x] ホール内部へのガス体積の追加・Garfield++側インデックスのオフバイワン修正（詳細はコード中コメント参照）
- [x] 3Dインタラクティブビューア (`macros/export_field_samples.cpp` + Plotly artifact、`geometry/plot_3d_*.py`)
- [x] 単段GEMでの電子雪崩ゲイン計算 (`macros/gen_gas_table.cpp`, `macros/gem_avalanche.cpp`)。
      P10ガステーブル生成 → 電子雪崩が動作することを確認。V_GEM=305Vで100イベントの平均ゲイン
      8.06±8.88（統計・注入位置ともにまだ粗い一次確認。定量的な妥当性検証は未実施）
- [x] 3段GEM (ギャップ含む) の電場マップ生成 (`geometry/triple_gem_field_model.py`,
      `geometry/build_triple_gem_field_mesh.py`)。並び順は**ドリフト側から100→50→50µm**
      （Kim et al. 2020論文の50→50→100µmとは異なる、2026-09-22にユーザーへ確認済みの現行設計）。
      ドリフトギャップは実機の55cmではなく4.2mmの簡略値（近傍物理には影響しないための意図的な簡略化）。
      電位連鎖（パッド面0V基準）: 各GEM電圧305V(50µm)/457.5V(100µm, 1.5倍則)、
      トランスファー2kV/cm、インダクション3.1kV/cm、ドリフト130V/cmを積み上げ、
      カソード側で約-2542V。ElmerGridでconformalメッシュ・ElmerSolve成功、
      Garfield++での電位分布も各GEMホールで妥当な漏斗形状を確認済み
- [~] 3段GEMでの電子雪崩・ゲイン計算: 単位セル1個では二次電子が100%孔の壁に吸収され
      GEM2に到達しない問題を発見。3x3セルにタイル化して境界アーティファクト由来の損失
      (16%)はゼロにできたが、孔の壁そのものへの吸収(84%)は残ったまま。100イベント
      (終端点2354個)まで統計を増やしても到達ゼロを確認し、統計不足ではなく系統的な
      効果であることを確認 — 未解決のオープンな問題。GEM1単体での切り分けテスト、
      medium連続性の直接確認、transfer電場scan(2→10kV/cm)でも改善せず、
      「3段スタック特有の問題ではない」ことは確認済み。検証済み/未検証の仮説一覧・
      次の一手候補・パイプライン構築時の落とし穴は `docs/debugging_notes.md` 参照
      （GitHub issue #2）
- [x] Python可視化レイヤー (GitHub issue #3): `macros/export_avalanche_trajectories.cpp`
      で雪崩電子の全経路をROOT出力、`visualization/plot_triple_gem.py`で
      geometry+電場スライス+電子経路+電場streamlineを1つのPyVistaシーンに
      overlay（インタラクティブHTML出力）、`visualization/plot_z_profiles.py`で
      Ez(z)/|E|(z)/Ne(z)診断プロット。いずれも`triple_gem_field`/`single_gem_field`
      両モデルで動作確認済み（モデル固有のハードコードなし）
- [x] 出力構成の整理とROOT化: 従来`geometry/output/`, `macros/output/`,
      `visualization/output/`に分散していた出力を`results/`（`mesh/root/img/html/json`
      にファイル種別ごと整理）へ一本化。電子endpoint/trajectoryのデータ出力も
      CSVからROOT TTree（`results/root/<baseName>_avalanche.root`の
      `Endpoints`/`Trajectories` tree）に変更、Python側は`uproot`で読み込み。
      詳細は `docs/reference.md` 参照
