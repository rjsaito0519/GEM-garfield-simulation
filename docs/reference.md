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

`results/root/<baseName>_avalanche.root`は1ファイルに最大2つのTTreeを持つ。
`gem_avalanche`と`export_avalanche_trajectories`はどちらも`TFile::Open(...,
"UPDATE")`で開き、自分の書くtreeの古いcycleだけを`Delete("<TreeName>;*")`で
消してから書き直すので、片方だけを再実行してももう片方のtreeは残る。

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

## 5. 関連ドキュメント

- `README.md` — プロジェクト概要、対象デバイス、実行環境
- `docs/debugging_notes.md` — GEM1→GEM2電子透過率問題の調査ログ（issue #2）
- `docs/pipeline_gotchas.md` — Gmsh/Elmer/Garfield++連携で踏んだ落とし穴集
- `CLAUDE.md` — AIエージェント向けエントリポイント
