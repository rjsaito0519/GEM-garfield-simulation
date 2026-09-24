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

### `RunInfo` (macros/gem_avalanche.cpp と export_avalanche_trajectories.cpp が書く)

2026-09-24追加（GitHub issue #6 item 1）。そのrunで実際に使われた条件を、
key/value文字列ペア1つにつき1エントリで記録する固定でないスキーマ
（`macros/run_info.hh`参照）。single-GEM/triple-GEMで`model_info.json`の
`geometry`ブロックの形が違う（後者のみ`layers`を持つ）ため、個々の
フィールドに分解せず`model_info_json`キーの下に元のJSON全体をそのまま
埋め込んでいる。

| key | 意味 |
|---|---|
| `executable` | `"gem_avalanche"` / `"export_avalanche_trajectories"` |
| `git_commit_hash` | ビルド時（`cmake`実行時点、ビルドの度ではない）のgit commit hash |
| `mesh_dir`, `geometry_type` | argv[1]そのもの、およびそのbaseName |
| `gas_file`, `gas_temperature_k`, `gas_pressure_torr` | 使用した`.gas`ファイルと、`MediumMagboltz::LoadGasFile()`後に実際に読み込まれた温度・圧力 |
| `gas_material_index` | `model_info.hh`の`geo.gas_material_index`（GitHub issue #6 item 3） |
| `n_events`, `z_sensor_min_cm`, `z_sensor_max_cm`, `z_injection_cm`, `x_half_cm`, `y_half_cm`, `e0_ev`, `injection_radius_cm` | CLI引数そのまま |
| `avalanche_size_limit`, `n_events_at_avalanche_size_limit` | `EnableAvalancheSizeLimit()`の値と、そのrunで実際に上限に達したイベント数 |
| `rng_seed` | 明示seedを渡した場合はその値、渡さなければ`"auto (process-default)"` |
| `model_info_json` | `<baseName>_model_info.json`の生の中身（geometry・physical_group_ids・electrode_potentials_v・dielectric_relative_permittivity等すべて含む） |

`gem_avalanche`/`export_avalanche_trajectories`はどちらも自分の`RunInfo`
tree（既存cycleを`Delete("RunInfo;*")`で消してから書き直す）を持つため、
同じ出力ファイルに両方を続けて実行すると、`RunInfo`は最後に実行した方の
条件だけを反映する（`Endpoints`/`Trajectories`は互いに影響しない）。

Pythonから読む例:
```python
import uproot
with uproot.open("results/root/triple_gem_field_avalanche.root") as f:
    arr = f["RunInfo"].arrays(["key", "value"], library="np")
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

# 実際に投入する場合は --dry-run を外す
python3 batch/run_avalanche_batch.py ... --njobs 10 --queue s
```

各ジョブの中間ファイル・bsubログは`results/root/.batch_tmp/<baseName>/partNNN/`
に残る（デバッグ用、自動削除しない）。**注意**: バッチジョブ投入
（`bsub`実行）はプロジェクトの安全ルール上、ユーザーが明示的にその場で
依頼したときのみ行う（`--dry-run`なしでの実行は自動では行わない）。
Elmer solve自体（MPI分割等）はこの枠組みの対象外 — 単一の線形システムを
解く工程であり、avalanche計算のような単純な並列分割ができないため。

## 6. 関連ドキュメント

- `README.md` — プロジェクト概要、対象デバイス、実行環境
- `docs/debugging_notes.md` — GEM1→GEM2電子透過率問題の調査ログ（issue #2）
- `docs/pipeline_gotchas.md` — Gmsh/Elmer/Garfield++連携で踏んだ落とし穴集
- `CLAUDE.md` — AIエージェント向けエントリポイント
