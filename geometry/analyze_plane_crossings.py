"""Plane-crossing transmission analysis for the 3-GEM stack avalanche --
v2, fixing a real methodology flaw in the first version (see below).

## The flaw this version fixes

The original version counted a track as having "crossed" a z-plane if
`z.min() < z_threshold` anywhere in its recorded path. That is NOT the
same as genuinely crossing the plane: a secondary electron *born* (created
by ionization) already below the plane -- e.g. a new electron created by
an avalanche happening inside GEM2's own hole -- trivially satisfies
`z.min() < z_threshold` without ever having travelled down through it.
This silently mixed "GEM1-origin electrons that made it to GEM2" together
with "electrons freshly created near/inside GEM2", inflating the apparent
GEM1->GEM2 transmission.

This version instead:
  - Detects a *genuine downward crossing*: consecutive recorded points
    (z_i, z_{i+1}) with z_i >= z_threshold and z_{i+1} < z_threshold.
  - Records each track's *birth region* (which z-band its first recorded
    point falls in), and reports plane-crossing counts as a funnel over
    the *GEM1-extracted cohort specifically* (electrons that genuinely
    crossed GEM1's bottom plane) rather than "any track currently below
    this z, regardless of where it came from".
  - Adds fine-grained planes through transfer gap 1 (25/50/75%, GEM2
    top-50um, GEM2 top-10um, GEM2 hole entrance) to localize *where*
    within the gap/GEM2 the cohort is actually lost.
  - Classifies the GEM1-extracted cohort's final fate using the
    "Trajectories" tree's own "status" branch (added alongside this
    script) plus each track's last recorded point, since gem_avalanche's
    separate "Endpoints" tree has no per-track index to join against.

Usage:
    python3 analyze_plane_crossings.py <avalanche.root>
Input: the "Trajectories" tree written by macros/export_avalanche_trajectories
       (event,track,x,y,z,t,energy,status) -- status was added alongside
       this script version; re-run export_avalanche_trajectories first if
       the ROOT file predates that.

Caveat (see docs/debugging_notes.md, "SetCollisionSteps"): points are only
recorded every `collisionSteps` real collisions (macro default 100), so a
crossing is detected between two *recorded* points, not at the exact true
crossing collision -- fine for "did it cross" and reasonable for
interpolated (x,y) at the crossing, coarse for exact timing. Re-run
export_avalanche_trajectories with a smaller collisionSteps for finer
resolution if needed.
"""

import dataclasses
import json
import sys

import numpy as np
import uproot

from gem_params import GemLayerParams
from gem_unit_cell import hole_centers_tiled
from triple_gem_field_model import (
    GemStackLayer,
    TripleGemTestConfig,
    _half_extent_cm,
    _layer_z_centers,
)

# GarfieldConstants.hh status codes seen in this project so far.
_STATUS_NAMES = {
    -1: "StatusLeftDriftArea (lateral sensor boundary)",
    -5: "StatusLeftDriftMedium (hit solid material)",
    -6: "StatusOutsideMesh",
    -7: "StatusAttached",
}


def _status_name(status: int) -> str:
    return _STATUS_NAMES.get(status, f"status={status}")


def _funnel_planes(config: TripleGemTestConfig) -> list[tuple[str, float]]:
    """[(label, z_threshold_cm), ...], ordered downstream, from GEM1's own
    top down through a fine breakdown of transfer gap 1 and GEM2, then the
    rest of the stack at coarser (per-GEM top/bottom) resolution."""
    z_centers = _layer_z_centers(config)
    gem1, gem2, gem3 = config.layers[0], config.layers[1], config.layers[2]
    z_gem1_top = z_centers[0] + _half_extent_cm(gem1)
    z_gem1_bottom = z_centers[0] - _half_extent_cm(gem1)
    z_gem2_top = z_centers[1] + _half_extent_cm(gem2)
    z_gem2_bottom = z_centers[1] - _half_extent_cm(gem2)
    z_gem3_top = z_centers[2] + _half_extent_cm(gem3)
    z_gem3_bottom = z_centers[2] - _half_extent_cm(gem3)

    gap = z_gem1_bottom - z_gem2_top  # transfer-gap-1 height (positive)
    planes = [
        ("GEM1 top", z_gem1_top),
        ("GEM1 bottom", z_gem1_bottom),
        ("T1 25%", z_gem1_bottom - 0.25 * gap),
        ("T1 50%", z_gem1_bottom - 0.50 * gap),
        ("T1 75%", z_gem1_bottom - 0.75 * gap),
        ("GEM2 top-50um", z_gem2_top + 50.0e-4),
        ("GEM2 top-10um", z_gem2_top + 10.0e-4),
        ("GEM2 top (hole entrance)", z_gem2_top),
        ("GEM2 bottom", z_gem2_bottom),
        ("GEM3 top", z_gem3_top),
        ("GEM3 bottom", z_gem3_bottom),
    ]
    return planes


def _birth_regions(config: TripleGemTestConfig) -> list[tuple[str, float, float]]:
    """[(label, z_lo, z_hi), ...] covering the whole stack, for classifying
    where a track's first recorded point (its "birth") falls."""
    z_centers = _layer_z_centers(config)
    gem1, gem2, gem3 = config.layers[0], config.layers[1], config.layers[2]
    z_gem1_top = z_centers[0] + _half_extent_cm(gem1)
    z_gem1_bottom = z_centers[0] - _half_extent_cm(gem1)
    z_gem2_top = z_centers[1] + _half_extent_cm(gem2)
    z_gem2_bottom = z_centers[1] - _half_extent_cm(gem2)
    z_gem3_top = z_centers[2] + _half_extent_cm(gem3)
    z_gem3_bottom = z_centers[2] - _half_extent_cm(gem3)
    return [
        ("drift/above GEM1", z_gem1_top, 10.0),
        ("GEM1", z_gem1_bottom, z_gem1_top),
        ("transfer gap 1", z_gem2_top, z_gem1_bottom),
        ("GEM2", z_gem2_bottom, z_gem2_top),
        ("transfer gap 2", z_gem3_top, z_gem2_bottom),
        ("GEM3", z_gem3_bottom, z_gem3_top),
        ("induction/below GEM3", -10.0, z_gem3_bottom),
    ]


def _classify_z(z_val: float, regions: list[tuple[str, float, float]]) -> str:
    for label, z_lo, z_hi in regions:
        if z_lo <= z_val <= z_hi:
            return label
    return "?"


def _crossed(z_arr: np.ndarray, z_thresh: float) -> bool:
    """Genuine downward crossing: some consecutive pair with the first
    point at/above the plane and the next point below it (not just "the
    track's minimum z happens to be below" -- see module docstring)."""
    if len(z_arr) < 2:
        return False
    above = z_arr[:-1] >= z_thresh
    below = z_arr[1:] < z_thresh
    return bool(np.any(above & below))


def _interpolated_xy_at_plane(
    x_arr: np.ndarray, y_arr: np.ndarray, z_arr: np.ndarray, z_thresh: float
) -> tuple[float, float] | None:
    """(x, y) linearly interpolated at the first genuine downward crossing
    of z_thresh, or None if there isn't one."""
    if len(z_arr) < 2:
        return None
    above = z_arr[:-1] >= z_thresh
    below = z_arr[1:] < z_thresh
    idx = np.nonzero(above & below)[0]
    if len(idx) == 0:
        return None
    i = idx[0]
    z0, z1 = z_arr[i], z_arr[i + 1]
    frac = (z0 - z_thresh) / (z0 - z1) if z0 != z1 else 0.0
    x = x_arr[i] + frac * (x_arr[i + 1] - x_arr[i])
    y = y_arr[i] + frac * (y_arr[i + 1] - y_arr[i])
    return x, y


def _load_config_from_run_info(root_path: str) -> TripleGemTestConfig | None:
    """Reconstruct the TripleGemTestConfig actually used for this run, read
    from the "RunInfo" tree's "model_info_json" entry (see macros/run_info.hh,
    GitHub issue #6 items 1-2) instead of assuming today's default
    TripleGemTestConfig() still matches whatever produced this file.

    Returns None if the file has no "RunInfo" tree (predates that addition
    -- caller should fall back to the default config with a clear warning,
    not silently assume they match).

    A batch-merged file (batch/run_avalanche_batch.py's hadd) has one
    "RunInfo" tree per merged part, all with the same model_info_json (only
    per-job fields like rng_seed/n_events differ) -- using the first
    occurrence is correct and deliberate, not an oversight.
    """
    with uproot.open(root_path) as f:
        if "RunInfo" not in f:
            return None
        arr = f["RunInfo"].arrays(["key", "value"], library="np")
    model_info_json_values = [v for k, v in zip(arr["key"], arr["value"]) if k == "model_info_json"]
    if not model_info_json_values:
        return None
    model_info = json.loads(model_info_json_values[0])
    g = model_info["geometry"]
    if "layers" not in g:
        # model_info.json predates the per-layer geometry_info extension
        # (2026-09-24) -- not enough metadata here to reconstruct a full
        # TripleGemTestConfig (only pitch/half-extent/z-domain are
        # guaranteed present in an older file). Caller falls back to the
        # default-config path with its own warning.
        return None

    layers = tuple(
        GemStackLayer(
            name=layer["name"],
            params=GemLayerParams(
                # geometry_info["layers"] only records the stack position's
                # name ("GEM1"/"GEM2"/"GEM3"), not the underlying
                # GemLayerParams.name ("GEM_100um"/"GEM_50um") -- cosmetic
                # only, params.name isn't read by any z-position/pitch/
                # radius calculation downstream (verified 2026-09-24).
                name=layer["name"],
                pitch_cm=g["pitch_cm"],
                hole_inner_radius_cm=layer["hole_inner_radius_cm"],
                hole_outer_radius_cm=layer["hole_outer_radius_cm"],
                copper_thickness_cm=layer["copper_thickness_cm"],
                dielectric_thickness_cm=layer["dielectric_thickness_cm"],
                dielectric_relative_permittivity=layer["dielectric_relative_permittivity"],
            ),
            voltage_v=layer["voltage_v"],
        )
        for layer in g["layers"]
    )
    return TripleGemTestConfig(
        drift_gap_cm=g["drift_gap_cm"],
        drift_field_v_per_cm=g["drift_field_v_per_cm"],
        transfer_gap_cm=g["transfer_gap_cm"],
        transfer_field_v_per_cm=g["transfer_field_v_per_cm"],
        induction_gap_cm=g["induction_gap_cm"],
        induction_field_v_per_cm=g["induction_field_v_per_cm"],
        layers=layers,
        n_cells_x=g["n_cells_x"],
        n_cells_y=g["n_cells_y"],
    )


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: analyze_plane_crossings.py <avalanche.root> [n_cells]")
        sys.exit(1)
    root_path = sys.argv[1]
    # n_cells: only used as a fallback when root_path predates the RunInfo
    # tree (see _load_config_from_run_info) -- must match the n_cells_x/y
    # the ROOT file's geometry was actually built with in that case (see
    # build_triple_gem_field_mesh.py's optional 2nd CLI arg); only affects
    # the GEM2 hole-entrance (x,y) check below, not the z-plane thresholds.
    n_cells = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    config = _load_config_from_run_info(root_path)
    if config is not None:
        print("Geometry config: read from this file's own RunInfo tree "
              "(matches the actual simulation conditions).\n")
    else:
        config = dataclasses.replace(TripleGemTestConfig(), n_cells_x=n_cells, n_cells_y=n_cells)
        print("WARNING: this file has no RunInfo tree (predates GitHub issue #6 "
              "item 1) -- falling back to today's default TripleGemTestConfig() "
              "(with n_cells overridden from the CLI). This is NOT verified to "
              "match the actual conditions this file was produced with; "
              "re-run export_avalanche_trajectories to get a RunInfo tree if "
              "that matters here.\n")
    planes = _funnel_planes(config)
    birth_regions = _birth_regions(config)
    z_centers = _layer_z_centers(config)
    gem2 = config.layers[1]
    gem2_hole_centers = hole_centers_tiled(gem2.params.pitch_cm, config.n_cells_x, config.n_cells_y)
    gem2_hole_r = gem2.params.hole_outer_radius_cm  # widest point, at the Cu face (top)

    with uproot.open(root_path) as f:
        tree = f["Trajectories"]
        has_status = "status" in tree.keys()
        branches = ["event", "track", "x", "y", "z"] + (["status"] if has_status else [])
        data = tree.arrays(branches, library="np")
    event, track, x, y, z = data["event"], data["track"], data["x"], data["y"], data["z"]
    status = data["status"] if has_status else None
    if not has_status:
        print("NOTE: no 'status' branch in this file (predates the status "
              "branch addition) -- endpoint-fate classification skipped. "
              "Re-run export_avalanche_trajectories to get one.\n")

    keys = [tuple(k) for k in np.unique(np.stack([event, track], axis=1), axis=0)]
    n_total = len(keys)
    if n_total == 0:
        print("No tracks found in the Trajectories tree.")
        return
    n_events = len(np.unique(event))
    print(f"{root_path}: {n_events} primary events, {n_total} avalanche electrons "
          "(unique event,track pairs)\n")

    # --- Birth region breakdown -----------------------------------------
    birth_counts: dict[str, int] = {}
    track_masks = {}  # (ev,tr) -> boolean mask into the flat arrays, cached
    track_z_birth = {}
    track_birth_label = {}
    track_r_birth_cm = {}  # sqrt(x_birth^2 + y_birth^2), for the radial-extraction test below
    for ev, tr in keys:
        m = (event == ev) & (track == tr)
        track_masks[(ev, tr)] = m
        z_birth = z[m][0]
        track_z_birth[(ev, tr)] = z_birth
        label = _classify_z(z_birth, birth_regions)
        birth_counts[label] = birth_counts.get(label, 0) + 1
        track_birth_label[(ev, tr)] = label
        track_r_birth_cm[(ev, tr)] = float(np.hypot(x[m][0], y[m][0]))
    print("Birth region (first recorded point of each track):")
    for label, _, _ in birth_regions:
        c = birth_counts.get(label, 0)
        print(f"  {label:22s}: {c:4d} ({100 * c / n_total:5.1f}%)")
    print()

    # --- GEM1-extracted cohort funnel (genuine crossings only) ----------
    gem1_bottom_thresh = dict(planes)["GEM1 bottom"]
    cohort = [key for key in keys if _crossed(z[track_masks[key]], gem1_bottom_thresh)]
    print(f"GEM1-extracted cohort (genuinely crossed GEM1 bottom): {len(cohort)} "
          f"/ {n_total} ({100 * len(cohort) / n_total:.1f}% of all avalanche electrons)\n")

    print("Funnel within the GEM1-extracted cohort (genuine crossings only):")
    prev_count = len(cohort)
    prev_label = "GEM1-extracted cohort"
    surviving = cohort
    surviving_by_label = {"GEM1-extracted cohort": cohort}  # for the event-level breakdown below
    for label, z_thresh in planes:
        if label in ("GEM1 top", "GEM1 bottom"):
            continue  # already the cohort definition itself
        still_going = [key for key in surviving if _crossed(z[track_masks[key]], z_thresh)]
        step_pct = 100 * len(still_going) / prev_count if prev_count > 0 else float("nan")
        print(f"  {label:26s}: {len(still_going):4d} "
              f"({100 * len(still_going) / len(cohort):5.1f}% of cohort, "
              f"{step_pct:5.1f}% of {prev_label})")
        surviving_by_label[label] = still_going
        prev_count, prev_label, surviving = len(still_going), label, still_going

    # --- GEM2 hole-entrance check (z AND x,y within a real hole) --------
    z_gem2_top = dict(planes)["GEM2 top (hole entrance)"]
    reached_gem2_top = [key for key in cohort if _crossed(z[track_masks[key]], z_gem2_top)]
    entered_gem2_hole = []
    for key in reached_gem2_top:
        m = track_masks[key]
        xy = _interpolated_xy_at_plane(x[m], y[m], z[m], z_gem2_top)
        if xy is None:
            continue
        xc, yc = xy
        min_dist = min(np.hypot(xc - hx, yc - hy) for hx, hy in gem2_hole_centers)
        if min_dist < gem2_hole_r:
            entered_gem2_hole.append(key)
    n_hole_entrance = len(entered_gem2_hole)
    print(f"\n  Of those {len(reached_gem2_top)} reaching GEM2's top plane, "
          f"{n_hole_entrance} are within a real GEM2 hole opening "
          f"(r<{gem2_hole_r * 1e4:.1f}um of some tiled hole center) "
          f"({100 * n_hole_entrance / max(1, len(reached_gem2_top)):.1f}%)")

    # --- Event-level breakdown of the key funnel stages -------------------
    # Per-primary-event counts (not per-electron), because secondary
    # electrons within one primary event are correlated (they share the
    # same avalanche history), not independent Bernoulli trials -- treating
    # all N electrons across all events as N independent samples understates
    # the true uncertainty. Reporting per-event counts here is what a future
    # event-level bootstrap over uncertainty would resample from (see
    # docs/debugging_notes.md, "統計を増やす").
    event_stage_keys = {
        "N_GEM1_out": cohort,
        "N_transfer_mid": surviving_by_label.get("T1 75%", []),
        "N_GEM2_arrive": surviving_by_label.get("GEM2 top-10um", []),
        "N_GEM2_enter": entered_gem2_hole,
    }
    print("\nPer-event breakdown of the key funnel stages "
          "(for future event-level bootstrap uncertainty estimates):")
    header = f"  {'event':>6s}" + "".join(f"  {name:>15s}" for name in event_stage_keys)
    print(header)
    for ev in sorted(np.unique(event).tolist()):
        row = f"  {ev:6d}"
        for name, stage_keys in event_stage_keys.items():
            n = sum(1 for k in stage_keys if k[0] == ev)
            row += f"  {n:15d}"
        print(row)

    # --- P(extraction | r_birth) for GEM1-born electrons -----------------
    # Direct test of the "off-axis secondaries land where field lines are
    # already wall-directed" hypothesis (see docs/debugging_notes.md):
    # r_birth is each track's birth-point distance from its own hole axis
    # (nearest tiled GEM1 hole center, not from the domain origin -- avalanche
    # secondaries are produced across all 25 tiled GEM1 holes, not just the
    # central one), binned against whether that track genuinely crossed
    # GEM1's bottom plane.
    gem1 = config.layers[0]
    gem1_hole_centers = hole_centers_tiled(gem1.params.pitch_cm, config.n_cells_x, config.n_cells_y)
    cohort_set = set(cohort)
    gem1_born = [key for key in keys if track_birth_label[key] == "GEM1"]
    r_bins_um = [0.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, float("inf")]
    bin_born = [0] * (len(r_bins_um) - 1)
    bin_extracted = [0] * (len(r_bins_um) - 1)
    for key in gem1_born:
        m = track_masks[key]
        x_birth, y_birth = x[m][0], y[m][0]
        r_hole_um = min(np.hypot(x_birth - hx, y_birth - hy) for hx, hy in gem1_hole_centers) * 1e4
        for bi in range(len(r_bins_um) - 1):
            if r_bins_um[bi] <= r_hole_um < r_bins_um[bi + 1]:
                bin_born[bi] += 1
                if key in cohort_set:
                    bin_extracted[bi] += 1
                break
    print(f"\nP(crossed GEM1 bottom | r_birth) for {len(gem1_born)} electrons born inside "
          "GEM1 (r_birth = distance from the nearest tiled GEM1 hole center):")
    for bi in range(len(r_bins_um) - 1):
        lo, hi = r_bins_um[bi], r_bins_um[bi + 1]
        hi_str = f"{hi:5.1f}" if hi != float("inf") else "  inf"
        n_born, n_ext = bin_born[bi], bin_extracted[bi]
        pct = 100 * n_ext / n_born if n_born > 0 else float("nan")
        print(f"  r_birth in [{lo:5.1f}, {hi_str}) um: {n_ext:4d} / {n_born:4d} extracted "
              f"({pct:5.1f}%)")

    # --- Final-fate classification of the GEM1-extracted cohort ---------
    if has_status:
        print("\nFinal fate of the GEM1-extracted cohort (last recorded point + status):")
        fate_counts: dict[str, int] = {}
        for key in cohort:
            m = track_masks[key]
            idx = np.nonzero(m)[0]
            last = idx[-1]
            st = int(status[last])
            z_last = z[last]
            region = _classify_z(z_last, birth_regions)
            fate = f"{_status_name(st)} in {region}"
            fate_counts[fate] = fate_counts.get(fate, 0) + 1
        for fate, c in sorted(fate_counts.items(), key=lambda kv: -kv[1]):
            print(f"  {fate:55s}: {c:4d} ({100 * c / len(cohort):5.1f}%)")


if __name__ == "__main__":
    main()
