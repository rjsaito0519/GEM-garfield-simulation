"""Per-event avalanche size (GetAvalancheSize()'s "ne": total electrons
recorded in the avalanche tree, including ones later absorbed) and
avalanche_size_limit truncation, for GitHub issue #12 items 1-2
(avalanche_size_limit / collisionSteps convergence).

This is deliberately a different quantity from the "Local multiplication"
number analyze_collection_efficiency.py prints (tracks/event among only the
subset of primaries that entered a real hole opening) and from anything
plane-crossing-geometry-based (analyze_plane_crossings.py): both of those
are properties of electron *drift trajectories*, which avalanche_size_limit
and collisionSteps do not directly act on. avalanche_size_limit caps the
avalanche tree itself (Garfield++'s AvalancheMicroscopic drops, without
recording, any electron still queued once the cap is hit -- see
docs/pipeline_gotchas.md), so its effect shows up here, in the size/shape of
that tree, not in GEM1 extraction geometry.

A merged batch file's RunInfoTrajectories tree already carries one
"n_events_at_avalanche_size_limit" row per part job (summing these across
parts gives the ground-truth truncated-event count for the whole file, this
script cross-checks that ground truth against a per-event reconstruction:
an event is flagged truncated here if its own track count reaches the run's
avalanche_size_limit).

Usage:
    python3 analyze_avalanche_size.py <avalanche.root>
"""

import sys

import numpy as np
import uproot

from analyze_plane_crossings import require_trajectories_tree


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: analyze_avalanche_size.py <avalanche.root>")
        sys.exit(1)
    root_path = sys.argv[1]

    with uproot.open(root_path) as f:
        tree = require_trajectories_tree(f, root_path, ["event", "track"])
        data = tree.arrays(["event", "track"], library="np")

        avalanche_size_limit = None
        n_at_limit_from_run_info = None
        if "RunInfoTrajectories" in f:
            arr = f["RunInfoTrajectories"].arrays(["key", "value"], library="np")
            keys, values = arr["key"], arr["value"]
            limits = [float(v) for k, v in zip(keys, values) if k == "avalanche_size_limit"]
            at_limit = [int(v) for k, v in zip(keys, values) if k == "n_events_at_avalanche_size_limit"]
            if limits:
                if len(set(limits)) > 1:
                    print(f"WARNING: {root_path} merges parts with DIFFERENT avalanche_size_limit "
                          f"values {sorted(set(limits))} -- this file mixes runs from different "
                          "batch invocations, treat per-event numbers below with caution.\n")
                avalanche_size_limit = limits[0]
            if at_limit:
                n_at_limit_from_run_info = sum(at_limit)

    event, track = data["event"], data["track"]
    events = np.unique(event)
    n_tracks_per_event = np.array([len(np.unique(track[event == ev])) for ev in events])

    print(f"{root_path}: {len(events)} events"
          + (f", avalanche_size_limit={avalanche_size_limit:.0f}" if avalanche_size_limit else
             " (no avalanche_size_limit found in RunInfoTrajectories)"))
    print(f"Avalanche size (tracks/event, includes the primary): "
          f"mean={n_tracks_per_event.mean():.1f}, median={np.median(n_tracks_per_event):.1f}, "
          f"min={n_tracks_per_event.min()}, max={n_tracks_per_event.max()}")

    if avalanche_size_limit is not None:
        truncated = n_tracks_per_event >= avalanche_size_limit
        n_truncated = int(truncated.sum())
        print(f"Events reaching avalanche_size_limit (per-event track count >= limit): "
              f"{n_truncated}/{len(events)} ({100 * n_truncated / len(events):.1f}%)")
        if n_at_limit_from_run_info is not None:
            match = "matches" if n_truncated == n_at_limit_from_run_info else "DOES NOT MATCH"
            print(f"RunInfoTrajectories' own n_events_at_avalanche_size_limit sum: "
                  f"{n_at_limit_from_run_info} -- {match} the per-event reconstruction above.")
        if n_truncated > 0:
            kept = n_tracks_per_event[~truncated]
            if len(kept) > 0:
                print(f"Avalanche size among the {len(kept)} non-truncated events only: "
                      f"mean={kept.mean():.1f}, median={np.median(kept):.1f}, max={kept.max()}")
            else:
                print("Every event in this file was truncated -- no non-truncated events "
                      "to compare against.")


if __name__ == "__main__":
    main()
