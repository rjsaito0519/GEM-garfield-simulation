"""Plane-crossing transmission analysis for the 3-GEM stack avalanche.

Endpoint-status-based transmission counting (see docs/debugging_notes.md,
plot_avalanche_endpoints.py) can undercount real GEM1 extraction: an
electron whose FINAL endpoint is "hit GEM2's hole wall" (status=-5) may
still have successfully cleared GEM1 and the full transfer gap first --
the endpoint status alone can't tell "died immediately in GEM1" apart from
"made it all the way to GEM2 and died there instead" (this is exactly what
the z_end histogram's second, smaller cluster at GEM2's own dielectric
band already hinted at).

This script instead uses the full per-point path
(macros/export_avalanche_trajectories.cpp's "Trajectories" ROOT tree) to
count, per (event,track) electron, whether its recorded path ever reaches
past a given z threshold -- independent of where/why it eventually
stopped. Reports, for every GEM's top/bottom plane across the whole stack
(not just GEM1->GEM2), both:
  - the fraction of all avalanche electrons that got that far, and
  - the step efficiency relative to the previous plane (e.g. GEM1
    extraction efficiency = N(cleared GEM1 bottom) / N(all electrons);
    GEM1->GEM2 transmission = N(reached GEM2 top) / N(cleared GEM1 bottom))
so a bottleneck at GEM2 or GEM3 specifically is visible too.

Usage:
    python3 analyze_plane_crossings.py <avalanche.root>
Input: the "Trajectories" tree written by macros/export_avalanche_trajectories
       (event,track,x,y,z,t,energy).
"""

import sys

import numpy as np
import uproot

from triple_gem_field_model import TripleGemTestConfig, _half_extent_cm, _layer_z_centers


def _stage_planes(config: TripleGemTestConfig) -> list[tuple[str, float]]:
    """[(label, z_threshold_cm), ...], ordered downstream (decreasing z),
    covering every GEM's bottom (extraction) and top (entry) plane across
    the whole stack -- not just GEM1/GEM2, so a bottleneck at GEM2 or GEM3
    shows up too, not just the GEM1->GEM2 step this was first written for."""
    z_centers = _layer_z_centers(config)
    planes = []
    for layer, zc in zip(config.layers, z_centers):
        half = _half_extent_cm(layer)
        planes.append((f"{layer.name} top", zc + half))
        planes.append((f"{layer.name} bottom", zc - half))
    planes.sort(key=lambda p: -p[1])
    return planes


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: analyze_plane_crossings.py <avalanche.root>")
        sys.exit(1)
    root_path = sys.argv[1]

    config = TripleGemTestConfig()
    planes = _stage_planes(config)

    with uproot.open(root_path) as f:
        data = f["Trajectories"].arrays(["event", "track", "z"], library="np")
    event, track, z = data["event"], data["track"], data["z"]
    keys = np.unique(np.stack([event, track], axis=1), axis=0)
    n_total = len(keys)
    if n_total == 0:
        print("No tracks found in the Trajectories tree.")
        return

    z_min_per_track = np.array([z[(event == ev) & (track == tr)].min() for ev, tr in keys])

    n_events = len(np.unique(event))
    print(f"{root_path}: {n_events} primary events, {n_total} avalanche electrons "
          "(unique event,track pairs)")
    prev_label, prev_count = "all avalanche electrons", n_total
    for label, z_thresh in planes:
        n_past = int(np.count_nonzero(z_min_per_track < z_thresh))
        step_pct = 100 * n_past / prev_count if prev_count > 0 else float("nan")
        print(f"  Crossed {label:16s} (z < {z_thresh * 1e4:8.1f} um): "
              f"{n_past:4d} ({100 * n_past / n_total:5.1f}% of all, "
              f"{step_pct:5.1f}% of {prev_label})")
        prev_label, prev_count = f"those past {label}", n_past


if __name__ == "__main__":
    main()
