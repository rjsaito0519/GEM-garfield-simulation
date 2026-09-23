"""Re-evaluation of the single-GEM100 transfer-field scan (2 vs 10 kV/cm)
using the corrected genuine-plane-crossing metric from analyze_plane_crossings.py
(see docs/debugging_notes.md, "2026-09-23: plane-crossing判定のバグ修正").

The original single-GEM100 transfer-field scan (docs/debugging_notes.md,
"transfer電場scan（2 kV/cm → 10 kV/cm）") concluded "genuine hole-wall loss
stays 100% inside the GEM foil's own z-band, 0 electrons reach the transfer
gap, even at 5x transfer field" -- but that conclusion was based on each
electron's final endpoint status/position (Endpoints tree), not on whether
it ever genuinely crossed a plane on its way down. This script redoes that
comparison with the same genuine per-segment plane-crossing definition used
for the 3-GEM stack, on the "Trajectories" tree written by
macros/export_avalanche_trajectories (status branch required).

Unlike the 3-GEM stack analysis, there is no second GEM downstream here --
this measures "does GEM1 (in isolation) let electrons out into the transfer
gap at all", cross-checked against the r_birth-binned extraction rate
already established for the full stack.

Usage:
    python3 analyze_single_gem_plane_crossings.py <avalanche.root>
"""

import sys

import numpy as np
import uproot

from analyze_plane_crossings import _crossed, _interpolated_xy_at_plane, _status_name
from gem_params import GEM_100UM

# Single-GEM foil z-boundaries (see single_gem_field_model.py:
# z_gem_top/z_gem_bottom, GEM centered at z=0).
_HALF_T_DIEL_CM = GEM_100UM.dielectric_thickness_cm / 2.0
Z_GEM_TOP = _HALF_T_DIEL_CM + GEM_100UM.copper_thickness_cm
Z_GEM_BOTTOM = -Z_GEM_TOP

# Transfer-gap diagnostic planes: fractions of the way from GEM bottom to
# the sensor's transfer-side boundary (SingleGemTestConfig.transfer_gap_cm
# = 0.20 cm = 2000um for GEM1's real operating point -- see
# build_single_gem100_field_mesh.py). Matches the fine-grained breakdown
# used for transfer gap 1 in the 3-GEM stack.
_TRANSFER_GAP_CM = 0.20
_TRANSFER_FRACTIONS = [0.10, 0.25, 0.50, 0.75, 0.90]


def _birth_region(z_val: float) -> str:
    if z_val > Z_GEM_TOP:
        return "drift (above GEM)"
    if z_val >= Z_GEM_BOTTOM:
        return "GEM"
    return "transfer gap"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: analyze_single_gem_plane_crossings.py <avalanche.root>")
        sys.exit(1)
    root_path = sys.argv[1]

    planes = [("GEM top", Z_GEM_TOP), ("GEM bottom", Z_GEM_BOTTOM)]
    for frac in _TRANSFER_FRACTIONS:
        planes.append((f"transfer {int(frac * 100)}%", Z_GEM_BOTTOM - frac * _TRANSFER_GAP_CM))

    with uproot.open(root_path) as f:
        tree = f["Trajectories"]
        has_status = "status" in tree.keys()
        branches = ["event", "track", "x", "y", "z"] + (["status"] if has_status else [])
        data = tree.arrays(branches, library="np")
    event, track, x, y, z = data["event"], data["track"], data["x"], data["y"], data["z"]
    status = data["status"] if has_status else None
    if not has_status:
        print("NOTE: no 'status' branch -- endpoint-fate classification skipped.\n")

    keys = [tuple(k) for k in np.unique(np.stack([event, track], axis=1), axis=0)]
    n_total = len(keys)
    n_events = len(np.unique(event))
    print(f"{root_path}: {n_events} primary events, {n_total} avalanche electrons "
          "(unique event,track pairs)\n")

    track_masks = {}
    birth_counts: dict[str, int] = {}
    for ev, tr in keys:
        m = (event == ev) & (track == tr)
        track_masks[(ev, tr)] = m
        label = _birth_region(z[m][0])
        birth_counts[label] = birth_counts.get(label, 0) + 1
    print("Birth region (first recorded point of each track):")
    for label in ("drift (above GEM)", "GEM", "transfer gap"):
        c = birth_counts.get(label, 0)
        print(f"  {label:20s}: {c:4d} ({100 * c / n_total:5.1f}%)")
    print()

    # Informational only: almost all avalanche electrons are secondaries
    # born already inside the GEM (see birth-region breakdown above), so
    # "crossed GEM top" is ~ the primary/seed electrons only, not a useful
    # cohort-defining plane here.
    gem_top_thresh = dict(planes)["GEM top"]
    n_crossed_top = sum(1 for key in keys if _crossed(z[track_masks[key]], gem_top_thresh))
    print(f"(genuinely crossed GEM top: {n_crossed_top} / {n_total} -- "
          "mostly just the primaries, informational only)\n")

    # Extraction cohort: same convention as the 3-GEM stack's "GEM1-extracted
    # cohort" (analyze_plane_crossings.py) -- genuine crossing of GEM bottom,
    # counted over ALL avalanche electrons (primaries + secondaries), not
    # gated on having crossed GEM top first.
    gem_bottom_thresh = dict(planes)["GEM bottom"]
    cohort = [key for key in keys if _crossed(z[track_masks[key]], gem_bottom_thresh)]
    print(f"GEM-extracted cohort (genuinely crossed GEM bottom): {len(cohort)} / {n_total} "
          f"({100 * len(cohort) / n_total:.1f}% of all avalanche electrons)\n")

    print("Funnel within the GEM-extracted cohort (genuine crossings only):")
    prev_count = len(cohort)
    prev_label = "GEM-extracted cohort"
    surviving = cohort
    for label, z_thresh in planes:
        if label in ("GEM top", "GEM bottom"):
            continue
        still_going = [key for key in surviving if _crossed(z[track_masks[key]], z_thresh)]
        step_pct = 100 * len(still_going) / prev_count if prev_count > 0 else float("nan")
        print(f"  {label:16s}: {len(still_going):4d} "
              f"({100 * len(still_going) / len(cohort):5.1f}% of cohort, "
              f"{step_pct:5.1f}% of {prev_label})")
        prev_count, prev_label, surviving = len(still_going), label, still_going

    if has_status:
        print("\nFinal fate of the GEM-extracted cohort (last recorded point + status):")
        fate_counts: dict[str, int] = {}
        for key in cohort:
            m = track_masks[key]
            idx = np.nonzero(m)[0]
            last = idx[-1]
            st = int(status[last])
            z_last = z[last]
            region = _birth_region(z_last)
            fate = f"{_status_name(st)} in {region}"
            fate_counts[fate] = fate_counts.get(fate, 0) + 1
        for fate, c in sorted(fate_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {fate:55s}: {c:4d} ({100 * c / len(cohort):5.1f}%)")


if __name__ == "__main__":
    main()
