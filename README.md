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

詳細パラメータは `params/` を参照。

## パイプライン

```
パラメータ (YAML) → ジオメトリ生成 (Gmsh Python API) → メッシュ
  → Elmer (ElmerGrid/ElmerSolver, 静電場ソルブ) → Garfield++ (電子雪崩シミュレーション)
```

## ディレクトリ構成 (予定)

```
params/       パラメータ設定 (YAML)
geometry/     Gmsh Python APIによるジオメトリ・メッシュ生成スクリプト
elmer/        .sif生成スクリプト、誘電率定義など
src/ include/ C++コア (パラメータ読み込み、Elmerコンポーネント生成等)
macros/       Garfield++実行マクロ (単段テスト、3段本番等)
resources/    ガステーブル (P10) 等
```

## 実行環境

| ツール | バージョン / パス |
|---|---|
| Gmsh (CLI) | 4.13.1 (`~/local/gmsh-4.13.1-Linux64/bin/gmsh`) |
| Gmsh Python API | 4.15.2 (pipで`work`環境に導入済み。`conda install`はnumpy等の大規模ダウングレードを招くため使用しない) |
| Elmer | v9.0 (`~/elmer/bin/`, ローカルビルド。`/group/had/sks/software/elmer` は共有ライブラリ欠損で使用不可) |
| Garfield++ | ローカルビルド (`~/local/garfield`, パッケージバージョン文字列 "0.3") |
| ROOT | 6.40.04 (`~/local/root/6.40.04`)。Python/解析用とGarfield++ビルド用で統一 |
| CMake | 3.31.8 |
| gcc | 11.5.0 |

Elmer/Garfield++の環境変数は `~/.bashrc` では無効化されている(起動高速化のため, 詳細は
`~/local/envfs_README.md`)。このリポジトリではグローバル設定に頼らず、リポジトリ内の
セットアップスクリプトで明示的にパスを通す方針（`elmer/run_field_solve.sh`, `macros/CMakeLists.txt`）。

### Garfield++の再ビルドについて

`~/local/garfield`は元々ROOT 6.32.04向けにビルドされており(`/sw/packages/root/6.32.04`)、
`~/local/root/6.40.04`とはABIが非互換でリンクできませんでした。2026-09-22に
`~/.package_build/garfieldpp`(公式ソース, gitlab.cern.ch/garfield/garfieldpp)から
ROOT 6.40.04向けに再ビルド・再インストール済みです。再ビルドが必要になった場合:

```bash
cd ~/.package_build/garfieldpp/build
export ROOTSYS=~/local/root/6.40.04
export PATH="$ROOTSYS/bin:$PATH"
export LD_LIBRARY_PATH="$ROOTSYS/lib:$LD_LIBRARY_PATH"
cmake -DROOT_DIR="$ROOTSYS/cmake" .
cmake --build . -j"$(nproc)"
cmake --install .
```

`~/local/garfield`は本プロジェクト専用ではなく共有インストールなので、再ビルドする際は
他プロジェクトへの影響がないか確認してから行うこと。

## ステータス

- [x] Gmsh Python APIのセットアップ
- [x] 単段GEM(50µm)の単位胞ジオメトリ・メッシュ生成、可視化 (`geometry/build_single_gem.py`)
- [x] 単段GEMの電場マップ生成 (`geometry/single_gem_field_model.py`, `elmer/`, `macros/view_single_gem_field.cpp`)
- [x] ホール内部へのガス体積の追加・Garfield++側インデックスのオフバイワン修正（詳細はコード中コメント参照）
- [x] 3Dインタラクティブビューア (`macros/export_field_samples.cpp` + Plotly artifact、`geometry/plot_3d_*.py`)
- [x] 単段GEMでの電子雪崩ゲイン計算 (`macros/gen_gas_table.cpp`, `macros/single_gem_avalanche.cpp`)。
      P10ガステーブル生成 → 電子雪崩が動作することを確認。V_GEM=305Vで100イベントの平均ゲイン
      8.06±8.88（統計・注入位置ともにまだ粗い一次確認。定量的な妥当性検証は未実施）
- [ ] 3段GEM (ギャップ含む) の電場マップ生成
- [ ] 3段GEM本番マクロ
