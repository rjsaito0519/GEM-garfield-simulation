"""RunInfo tree schema / multi-tree-aggregation tests
(geometry/analyze_plane_crossings.py's _run_info_trees / read_run_info /
read_run_info_arrays) -- synthetic ROOT files only, no Garfield++ run
involved.

Confirms the key set macros/run_info.hh's WriteRunInfo actually writes
(see macros/export_avalanche_trajectories.cpp's WriteRunInfo call) round-
trips correctly, and guards against the multi-tree-name bug this project
hit for real: a merged batch file can have BOTH "RunInfoTrajectories" (new
parts) and the legacy "RunInfo" name (parts from before a mid-batch binary
rebuild) side by side, since hadd doesn't merge differently-named trees --
reading only one silently drops the other's rows from any aggregate sum.
"""

import os
import tempfile
import unittest

import uproot

import _pathsetup  # noqa: F401
from analyze_plane_crossings import read_run_info, read_run_info_arrays

# The key set macros/export_avalanche_trajectories.cpp's WriteRunInfo call
# actually writes (see its RunInfoTrajectories entries) -- kept here as a
# literal list so a future accidental key rename/removal there shows up as
# a test failure, not just a silent gap in what analysis code can rely on.
_EXPECTED_KEYS = {
    "executable", "git_commit_hash", "mesh_dir", "geometry_type", "gas_file",
    "gas_temperature_k", "gas_pressure_torr", "gas_material_index",
    "penning_transfer_enabled", "penning_r", "penning_lambda_cm", "git_dirty",
    "n_events", "event_offset", "collision_steps", "z_sensor_min_cm",
    "z_sensor_max_cm", "z_injection_cm", "x_half_cm", "y_half_cm", "e0_ev",
    "injection_radius_cm", "injection_direction", "avalanche_size_limit",
    "n_events_at_avalanche_size_limit", "rng_seed", "model_info_json",
}


def _write_run_info_tree(f, tree_name: str, entries: dict[str, str]) -> None:
    f.mktree(tree_name, {"key": str, "value": str})
    f[tree_name].extend({"key": list(entries.keys()), "value": list(entries.values())})


class TestRunInfoSchema(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".root")
        os.close(fd)

    def tearDown(self):
        os.remove(self.path)

    def test_all_expected_keys_round_trip(self):
        entries = {k: f"value_{i}" for i, k in enumerate(_EXPECTED_KEYS)}
        with uproot.recreate(self.path) as f:
            _write_run_info_tree(f, "RunInfoTrajectories", entries)
        with uproot.open(self.path) as f:
            run_info = read_run_info(f)
        self.assertEqual(set(run_info), _EXPECTED_KEYS)

    def test_aggregates_rows_across_both_tree_names_in_one_merged_file(self):
        """Regression test: a batch merge that spans a mid-batch macro
        rebuild can legitimately have RunInfoTrajectories AND RunInfo as
        two sibling trees in the same file (hadd keeps differently-named
        trees separate, it doesn't merge them)."""
        with uproot.recreate(self.path) as f:
            _write_run_info_tree(f, "RunInfoTrajectories", {
                "avalanche_size_limit": "2000", "n_events": "30",
            })
            _write_run_info_tree(f, "RunInfo", {
                "avalanche_size_limit": "2000", "n_events": "20",
            })
        with uproot.open(self.path) as f:
            arr = read_run_info_arrays(f)
        n_events_rows = [v for k, v in zip(arr["key"], arr["value"]) if k == "n_events"]
        self.assertEqual(sorted(n_events_rows), ["20", "30"])

    def test_no_run_info_tree_returns_none(self):
        with uproot.recreate(self.path) as f:
            f.mktree("Trajectories", {"event": "int64"})
        with uproot.open(self.path) as f:
            self.assertIsNone(read_run_info_arrays(f))
            self.assertEqual(read_run_info(f), {})


if __name__ == "__main__":
    unittest.main()
