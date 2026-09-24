"""Genuine collection efficiency for a single, standalone GEM foil test
(single_gem_field / single_gem100_field), for the standardized per-stage
efficiency table (GitHub issue #7 item 5).

"Collection efficiency" in the literature sense (e.g. Sauli's GEM papers)
means: of primary electrons drifting down uniformly from a wide area above
the GEM, what fraction actually funnel into a real hole opening, as opposed
to landing directly on the top copper. This only has a well-defined meaning
above an *isolated* GEM with a uniform upstream field -- not for GEM2/GEM3
inside the 3-GEM stack, whose "upstream" population is GEM1's own already
non-uniform avalanche output, not a uniform primary distribution (see
analyze_plane_crossings.py's "next-GEM collection" numbers for that
cascade-context question instead, a genuinely different quantity).

Requires export_avalanche_trajectories to have been run with a WIDE,
uniform-area injection radius (r = R*sqrt(U), fixed 2026-09-24, GitHub
issue #5 item 5) -- e.g. half the hole pitch, so injected primaries
symmetrically split between this hole and its nearest neighbors. The
project's usual near-axis injection radius (a few um, used for gain/
transmission diagnostics) is NOT wide enough to measure this; that
convention already pre-selects primaries born essentially on-axis.

Usage:
    python3 analyze_collection_efficiency.py <avalanche.root> [gem_type: 100|50]
"""

import sys

import numpy as np
import uproot

from analyze_plane_crossings import _crossed, _interpolated_xy_at_plane
from analyze_single_gem_plane_crossings import _gem_z_bounds
from gem_params import GEM_50UM, GEM_100UM
from gem_unit_cell import hole_centers_tiled

_GEM_PARAMS_BY_TYPE = {"100": GEM_100UM, "50": GEM_50UM}


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: analyze_collection_efficiency.py <avalanche.root> [gem_type: 100|50]")
        sys.exit(1)
    root_path = sys.argv[1]
    gem_type = sys.argv[2] if len(sys.argv) > 2 else "50"
    params = _GEM_PARAMS_BY_TYPE[gem_type]
    z_gem_top, z_gem_bottom = _gem_z_bounds(gem_type)

    with uproot.open(root_path) as f:
        tree = f["Trajectories"]
        data = tree.arrays(["event", "track", "x", "y", "z"], library="np")
        n_cells = 3
        injection_radius_cm = None
        z_injection = None
        if "RunInfo" in f:
            arr = f["RunInfo"].arrays(["key", "value"], library="np")
            run_info = dict(zip(arr["key"], arr["value"]))
            if "injection_radius_cm" in run_info:
                injection_radius_cm = float(run_info["injection_radius_cm"])
            if "z_injection_cm" in run_info:
                z_injection = float(run_info["z_injection_cm"])
    event, track, x, y, z = data["event"], data["track"], data["x"], data["y"], data["z"]

    if injection_radius_cm is None:
        print("WARNING: no RunInfo (or no injection_radius_cm in it) -- cannot confirm this "
              "file actually used a wide injection radius. Proceeding, but if the radius was "
              "the usual near-axis default (a few um), this result is meaningless -- see this "
              "script's own module docstring.\n")
    elif injection_radius_cm < params.hole_outer_radius_cm:
        print(f"WARNING: injection_radius_cm={injection_radius_cm * 1e4:.1f}um is narrower than "
              f"this GEM's own hole radius ({params.hole_outer_radius_cm * 1e4:.1f}um) -- this "
              "is a near-axis diagnostic run, not a genuine collection-efficiency measurement. "
              "Proceeding anyway.\n")

    hole_centers = hole_centers_tiled(params.pitch_cm, n_cells, n_cells)

    n_events = len(np.unique(event))
    n_collected = 0
    n_extracted = 0
    gains = []
    for ev in np.unique(event):
        m_ev = event == ev
        tracks_in_ev = np.unique(track[m_ev])
        # The primary is the one track whose first recorded point matches
        # the run's own injection height (falls back to "whichever track
        # starts highest" if z_injection is unknown, e.g. an older file).
        primary_track = None
        best_z0 = -np.inf
        for tr in tracks_in_ev:
            idx = np.nonzero(m_ev & (track == tr))[0]
            z0 = z[idx[0]]
            if z_injection is not None:
                if abs(z0 - z_injection) < 5.0e-4:
                    primary_track = tr
                    break
            elif z0 > best_z0:
                best_z0, primary_track = z0, tr
        if primary_track is None:
            continue

        idx = np.nonzero(m_ev & (track == primary_track))[0]
        xy = _interpolated_xy_at_plane(x[idx], y[idx], z[idx], z_gem_top)
        if xy is None:
            continue  # never reached the GEM top plane at all
        xc, yc = xy
        min_dist = min(np.hypot(xc - hx, yc - hy) for hx, hy in hole_centers)
        if min_dist >= params.hole_outer_radius_cm:
            continue  # landed on top copper, not a real hole opening

        n_collected += 1
        gains.append(len(tracks_in_ev))
        extracted = any(
            _crossed(z[np.nonzero(m_ev & (track == tr))[0]], z_gem_bottom)
            for tr in tracks_in_ev
        )
        if extracted:
            n_extracted += 1

    gains_arr = np.array(gains, dtype=float)
    print(f"{root_path}: {n_events} injected primaries (GEM_{gem_type}UM)")
    print(f"Collection efficiency (genuinely entered a real hole opening): "
          f"{n_collected}/{n_events} ({100 * n_collected / n_events:.1f}%)")
    if n_collected > 0:
        print(f"Local multiplication among collected (tracks/event, primary+secondaries): "
              f"mean={gains_arr.mean():.2f}, std={gains_arr.std():.2f}")
        print(f"Extraction efficiency (>=1 track genuinely crossed GEM bottom / collected): "
              f"{n_extracted}/{n_collected} ({100 * n_extracted / n_collected:.1f}%)")


if __name__ == "__main__":
    main()
