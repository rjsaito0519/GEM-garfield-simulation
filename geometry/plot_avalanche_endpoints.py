"""Diagnostic: where do avalanche-generated electron endpoints actually end
up in z/r, for the 3-GEM stack? Distinguishes "hole wall" losses from
"bottom copper" losses etc. that all show up as the same status=-5
(StatusLeftDriftMedium) in gem_avalanche's own tally -- see
docs/debugging_notes.md for the open GEM1->GEM2 transmission problem this
is investigating.

Usage:
    python3 plot_avalanche_endpoints.py <avalanche.root> [output_dir]
    output_dir defaults to results/img/ (see docs/reference.md
    "出力ディレクトリ構成").
Input: the "Endpoints" tree written by macros/gem_avalanche to
       "<baseName>_avalanche.root" (event,xs,ys,zs,ts,es,xe,ye,ze,te,ee,status).
"""

import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import uproot

from triple_gem_field_model import TripleGemTestConfig, _layer_z_centers, _half_extent_cm

IMG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "img")

# GEM z-boundaries, for annotating the plots -- see triple_gem_field_model.py.
_CONFIG = TripleGemTestConfig()
_Z_CENTERS = _layer_z_centers(_CONFIG)


def _layer_bands():
    """[(label, z_bottom, z_top, kind), ...] for shading GEM Cu/dielectric
    bands on the z_end histogram, kind in {"cu", "dielectric"}."""
    bands = []
    for layer, zc in zip(_CONFIG.layers, _Z_CENTERS):
        half = _half_extent_cm(layer)
        half_diel = layer.params.dielectric_thickness_cm / 2.0
        cu = layer.params.copper_thickness_cm
        bands.append((f"{layer.name}_topCu", zc + half_diel, zc + half, "cu"))
        bands.append((f"{layer.name}_dielectric", zc - half_diel, zc + half_diel, "dielectric"))
        bands.append((f"{layer.name}_bottomCu", zc - half, zc - half_diel, "cu"))
    return bands


def _hole_radius_at_z(z_cm: float) -> float | None:
    """Nominal hole radius [cm] at height z, biconical: widest (outer) at
    the Cu faces, narrowest (inner) at the dielectric mid-plane, linear in
    between -- matches gem_unit_cell.py's hole profile. None if z is outside
    any GEM foil's thickness."""
    for layer, zc in zip(_CONFIG.layers, _Z_CENTERS):
        half = _half_extent_cm(layer)
        half_diel = layer.params.dielectric_thickness_cm / 2.0
        dz = abs(z_cm - zc)
        if dz > half:
            continue
        r_in, r_out = layer.params.hole_inner_radius_cm, layer.params.hole_outer_radius_cm
        if dz <= half_diel:
            # Inside the dielectric: linear taper from r_out (at the Cu
            # interface) to r_in (at the mid-plane).
            return r_out - (r_out - r_in) * (dz / half_diel) if half_diel > 0 else r_in
        return r_out  # inside the Cu thickness: constant outer radius
    return None


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: plot_avalanche_endpoints.py <avalanche.root> [output_dir]")
        sys.exit(1)
    root_path = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else IMG_DIR
    os.makedirs(out_dir, exist_ok=True)

    with uproot.open(root_path) as f:
        data = f["Endpoints"].arrays(
            ["xe", "ye", "ze", "status"], library="np"
        )
    xe, ye, ze, status = data["xe"], data["ye"], data["ze"], data["status"]
    re = np.sqrt(xe**2 + ye**2)

    lost_mask = status == -5  # StatusLeftDriftMedium: hit solid material
    print(f"Total endpoints: {len(status)}, status=-5 (lost to material): {lost_mask.sum()}, "
          f"other: {(~lost_mask).sum()}")

    # --- z_end histogram, with GEM Cu/dielectric bands shaded -----------
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(ze[lost_mask] * 1e4, bins=150, color="steelblue", label="status=-5 (hit material)")
    if (~lost_mask).any():
        ax.hist(ze[~lost_mask] * 1e4, bins=150, color="orange", label="other status")
    colors = {"cu": "#d9843344", "dielectric": "#33883344"}
    for label, z_bot, z_top, kind in _layer_bands():
        ax.axvspan(z_bot * 1e4, z_top * 1e4, color=colors[kind], lw=0)
    ax.set_xlabel("z_end [um]")
    ax.set_ylabel("count")
    ax.set_title("Electron endpoint z distribution (orange=Cu band, green=dielectric band)")
    ax.legend()
    fig.tight_layout()
    z_path = os.path.join(out_dir, "avalanche_endpoints_z_hist.png")
    fig.savefig(z_path, dpi=150)
    print(f"Wrote {z_path}")

    # --- r_end histogram --------------------------------------------------
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(re[lost_mask] * 1e4, bins=100, color="steelblue")
    ax.set_xlabel("r_end [um]")
    ax.set_ylabel("count")
    ax.set_title("Electron endpoint radial distribution (status=-5 only)")
    fig.tight_layout()
    r_path = os.path.join(out_dir, "avalanche_endpoints_r_hist.png")
    fig.savefig(r_path, dpi=150)
    print(f"Wrote {r_path}")

    # --- r_end vs z_end scatter, with the nominal hole-wall profile -----
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.scatter(ze[lost_mask] * 1e4, re[lost_mask] * 1e4, s=4, alpha=0.4, color="steelblue")
    z_line = np.linspace(min(_Z_CENTERS) - 0.02, max(_Z_CENTERS) + 0.02, 2000)
    r_line = np.array([(_hole_radius_at_z(z) or np.nan) for z in z_line])
    ax.plot(z_line * 1e4, r_line * 1e4, color="red", lw=1, label="nominal hole wall radius")
    ax.set_xlabel("z_end [um]")
    ax.set_ylabel("r_end [um]")
    ax.set_title("Electron endpoint r vs z (status=-5 only)")
    ax.legend()
    fig.tight_layout()
    rz_path = os.path.join(out_dir, "avalanche_endpoints_r_vs_z.png")
    fig.savefig(rz_path, dpi=150)
    print(f"Wrote {rz_path}")


if __name__ == "__main__":
    main()
