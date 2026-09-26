"""1D diagnostic plots along z: Ez(z), |E|(z), and an approximate Ne(z)
(electron count vs. depth, from avalanche trajectories). Reuses the same
data sources as plot_triple_gem.py -- no new C++/simulation work needed.

Usage:
    python3 plot_z_profiles.py [baseName] [output.png]
    baseName defaults to "triple_gem_field"; output defaults to
    results/img/<baseName>_z_profiles.png. Ne(z) is skipped (with a printed
    note) if no "Trajectories" tree exists yet for baseName -- run
    macros/export_avalanche_trajectories first to get one.
"""

import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import uproot

# results/ is this project's single consolidated output tree -- see
# docs/reference.md "出力ディレクトリ構成" for what belongs in each subdir.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
JSON_DIR = os.path.join(RESULTS_DIR, "json")
ROOT_DIR = os.path.join(RESULTS_DIR, "root")
IMG_DIR = os.path.join(RESULTS_DIR, "img")


def load_axis_field_profile(slice_json_path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Ez(z) and |E|(z) along the column of the y=0 field slice
    (export_field_samples.cpp) closest to x=0 -- an approximate hole-axis
    lineout; the slice's grid spacing may not land exactly on x=0."""
    with open(slice_json_path) as f:
        data = json.load(f)
    nx, nz = data["nx"], data["nz"]
    samples = data["samples"]
    x = np.array([s["x"] for s in samples]).reshape(nx, nz)
    z = np.array([s["z"] for s in samples]).reshape(nx, nz)
    ex = np.array([s["ex"] for s in samples]).reshape(nx, nz)
    ey = np.array([s["ey"] for s in samples]).reshape(nx, nz)
    ez = np.array([s["ez"] for s in samples]).reshape(nx, nz)
    ix0 = int(np.argmin(np.abs(x[:, 0])))
    e_mag_axis = np.sqrt(ex[ix0] ** 2 + ey[ix0] ** 2 + ez[ix0] ** 2)
    return z[ix0], ez[ix0], e_mag_axis


def load_ne_profile(root_path: str, n_bins: int = 200) -> tuple[np.ndarray, np.ndarray]:
    """Approximate Ne(z): the number of distinct (event,track) electrons
    (macros/export_avalanche_trajectories.cpp's "Trajectories" tree) whose
    recorded path passes through each z-bin, averaged over the number of
    distinct primary events in the file -- reads as "electrons present per
    primary event", not a raw total that would scale with however many
    events were run. This is a rough proxy (path points aren't evenly
    spaced in time or distance), not a proper time-resolved electron
    count."""
    with uproot.open(root_path) as f:
        data = f["Trajectories"].arrays(["event", "track", "z"], library="np")
    z = data["z"]
    # Pack (event, track) into one integer key for fast uniqueness checks.
    keys = data["event"].astype(np.int64) * 1_000_000 + data["track"].astype(np.int64)
    n_events = max(1, len(np.unique(data["event"])))

    bin_edges = np.linspace(z.min(), z.max(), n_bins + 1)
    bin_idx = np.clip(np.digitize(z, bin_edges) - 1, 0, n_bins - 1)
    counts = np.zeros(n_bins)
    for b in range(n_bins):
        counts[b] = len(np.unique(keys[bin_idx == b]))
    z_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
    return z_centers, counts / n_events


def _has_tree(root_path: str, tree_name: str) -> bool:
    if not os.path.exists(root_path):
        return False
    with uproot.open(root_path) as f:
        return tree_name in f


def main() -> None:
    base_name = sys.argv[1] if len(sys.argv) > 1 else "triple_gem_field"
    os.makedirs(IMG_DIR, exist_ok=True)
    out_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        IMG_DIR, f"{base_name}_z_profiles.png"
    )

    slice_path = os.path.join(JSON_DIR, f"{base_name}_field_slice_full.json")
    trajectories_path = os.path.join(ROOT_DIR, f"{base_name}_avalanche.root")

    z_axis, ez_axis, e_mag_axis = load_axis_field_profile(slice_path)
    has_traj = _has_tree(trajectories_path, "Trajectories")

    n_panels = 3 if has_traj else 2
    fig, axes = plt.subplots(n_panels, 1, figsize=(9, 3 * n_panels), sharex=True)

    axes[0].plot(z_axis * 1e4, ez_axis)
    axes[0].axhline(0, color="gray", lw=0.5)
    axes[0].set_ylabel("Ez [V/cm]")

    axes[1].plot(z_axis * 1e4, e_mag_axis)
    axes[1].set_yscale("log")
    axes[1].set_ylabel("|E| [V/cm]")

    if has_traj:
        z_ne, ne = load_ne_profile(trajectories_path)
        axes[2].plot(z_ne * 1e4, ne)
        axes[2].set_ylabel("Ne(z) per event\n(approx., see docstring)")
        axes[2].set_xlabel("z [um]")
    else:
        axes[1].set_xlabel("z [um]")
        print(f"No \"Trajectories\" tree at {trajectories_path} -- skipping Ne(z) "
              "(run macros/export_avalanche_trajectories first)")

    fig.suptitle(f"{base_name}: z profiles (near hole axis)")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
