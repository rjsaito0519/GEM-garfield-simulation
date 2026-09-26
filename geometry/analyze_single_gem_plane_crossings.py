"""Single-GEM100 transfer-field scan (2 vs 10 kV/cm) analyzed with the
genuine-plane-crossing metric from analyze_plane_crossings.py (see
docs/debugging_notes.md, "transfer電場scan（2 kV/cm → 10 kV/cm）").

Classifying a track's fate purely from its final endpoint status/position
(the Endpoints tree) can look like "genuine hole-wall loss stays 100%
inside the GEM foil's own z-band, 0 electrons reach the transfer gap, even
at 5x transfer field" without actually telling you whether any electron
ever genuinely crossed a plane on its way down -- see
analyze_plane_crossings.py's module docstring for why that distinction
matters. This script applies the same genuine per-segment plane-crossing
definition used for the 3-GEM stack to the "Trajectories" tree written by
macros/export_avalanche_trajectories (status branch required).

Unlike the 3-GEM stack analysis, there is no second GEM downstream here --
this measures "does GEM1 (in isolation) let electrons out into the transfer
gap at all", cross-checked against the r_birth-binned extraction rate
already established for the full stack.

Usage:
    python3 analyze_single_gem_plane_crossings.py <avalanche.root> [gem_type: 100|50]
    gem_type selects the GEM foil thickness whose z-bounds to use (default
    100, i.e. GEM1's type); pass 50 when analyzing a GEM2/GEM3-type
    (single_gem_field, GEM_50UM) standalone run.
"""

import json
import sys

import numpy as np
import uproot

from analyze_plane_crossings import (
    _crossed, _interpolated_xy_at_plane, _status_name, read_run_info, require_trajectories_tree,
)
from gem_params import GEM_50UM, GEM_100UM

# Single-GEM foil z-boundaries (see single_gem_field_model.py:
# z_gem_top/z_gem_bottom, GEM centered at z=0). Which GEM type's thickness
# to use is a CLI arg (default 100um, i.e. GEM1's type) since this script
# is also used for the 50um GEM2/GEM3 type -- see docs/debugging_notes.md.
_GEM_PARAMS_BY_TYPE = {"100": GEM_100UM, "50": GEM_50UM}


def _gem_z_bounds(gem_type: str) -> tuple[float, float]:
    params = _GEM_PARAMS_BY_TYPE[gem_type]
    half_t_diel_cm = params.dielectric_thickness_cm / 2.0
    z_top = half_t_diel_cm + params.copper_thickness_cm
    return z_top, -z_top

# Transfer-gap diagnostic planes: fractions of the way from GEM bottom to
# the sensor's transfer-side boundary (SingleGemTestConfig.transfer_gap_cm
# = 0.20 cm = 2000um for GEM1's real operating point -- see
# build_single_gem100_field_mesh.py). Matches the fine-grained breakdown
# used for transfer gap 1 in the 3-GEM stack.
_TRANSFER_GAP_CM = 0.20
_TRANSFER_FRACTIONS = [0.10, 0.25, 0.50, 0.75, 0.90]


def _birth_region(z_val: float, z_gem_top: float, z_gem_bottom: float) -> str:
    if z_val > z_gem_top:
        return "drift (above GEM)"
    if z_val >= z_gem_bottom:
        return "GEM"
    return "transfer gap"


def _load_geometry_from_run_info(root_path: str) -> tuple[float, float, float] | None:
    """(z_gem_top_cm, z_gem_bottom_cm, transfer_gap_cm), read from this
    file's own run-info tree's "model_info_json" entry via read_run_info()
    (see macros/run_info.hh) instead of assuming a CLI-selected
    GEM_50UM/GEM_100UM catalog value and a hardcoded _TRANSFER_GAP_CM still
    match whatever this file was actually built with (e.g. a non-default
    transfer-field diagnostic run, see this file's own module docstring).
    Returns None if unavailable (no run-info tree, or an older
    model_info.json missing these fields) -- caller falls back to the
    CLI/hardcoded path with its own warning.
    """
    with uproot.open(root_path) as f:
        run_info = read_run_info(f)
    if not run_info or "model_info_json" not in run_info:
        return None
    g = json.loads(run_info["model_info_json"])["geometry"]
    if "z_gem_top_cm" not in g or "z_gem_bottom_cm" not in g or "transfer_gap_cm" not in g:
        return None
    return g["z_gem_top_cm"], g["z_gem_bottom_cm"], g["transfer_gap_cm"]


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: analyze_single_gem_plane_crossings.py <avalanche.root> [gem_type: 100|50]")
        sys.exit(1)
    root_path = sys.argv[1]
    gem_type = sys.argv[2] if len(sys.argv) > 2 else "100"

    geometry_from_run_info = _load_geometry_from_run_info(root_path)
    if geometry_from_run_info is not None:
        z_gem_top, z_gem_bottom, transfer_gap_cm = geometry_from_run_info
        print("Geometry: read from this file's own RunInfo tree "
              "(matches the actual simulation conditions).\n")
    else:
        z_gem_top, z_gem_bottom = _gem_z_bounds(gem_type)
        transfer_gap_cm = _TRANSFER_GAP_CM
        print(f"WARNING: this file has no usable RunInfo geometry (produced by an "
              f"older macro build, or predates the geometry_info layer extension) -- "
              f"falling back to GEM_{gem_type}UM's catalog thickness and the "
              f"hardcoded default transfer_gap_cm={_TRANSFER_GAP_CM}. This is NOT "
              f"verified to match the actual conditions this file was produced "
              f"with (e.g. a non-default transfer-field scan); re-run "
              f"export_avalanche_trajectories to get a RunInfo tree if that "
              f"matters here.\n")

    planes = [("GEM top", z_gem_top), ("GEM bottom", z_gem_bottom)]
    for frac in _TRANSFER_FRACTIONS:
        planes.append((f"transfer {int(frac * 100)}%", z_gem_bottom - frac * transfer_gap_cm))

    with uproot.open(root_path) as f:
        tree = require_trajectories_tree(f, root_path, ["event", "track", "x", "y", "z"])
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
        label = _birth_region(z[m][0], z_gem_top, z_gem_bottom)
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
    # max(1, ...) not len(cohort) directly: an empty cohort (genuinely zero
    # GEM-bottom crossings) is exactly the pathological case described in
    # this script's own module docstring -- would otherwise raise
    # ZeroDivisionError here instead of printing the funnel as all zeros.
    cohort_denom = max(1, len(cohort))
    prev_count = len(cohort)
    prev_label = "GEM-extracted cohort"
    surviving = cohort
    for label, z_thresh in planes:
        if label in ("GEM top", "GEM bottom"):
            continue
        still_going = [key for key in surviving if _crossed(z[track_masks[key]], z_thresh)]
        step_pct = 100 * len(still_going) / prev_count if prev_count > 0 else float("nan")
        print(f"  {label:16s}: {len(still_going):4d} "
              f"({100 * len(still_going) / cohort_denom:5.1f}% of cohort, "
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
            region = _birth_region(z_last, z_gem_top, z_gem_bottom)
            fate = f"{_status_name(st)} in {region}"
            fate_counts[fate] = fate_counts.get(fate, 0) + 1
        for fate, c in sorted(fate_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {fate:55s}: {c:4d} ({100 * c / cohort_denom:5.1f}%)")


if __name__ == "__main__":
    main()
