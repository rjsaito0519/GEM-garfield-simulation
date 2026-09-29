"""Batch merge validation tests (batch/run_avalanche_batch.py's
_validate_part) -- synthetic part ROOT files only (uproot.recreate, no
real bsub/Garfield++ run involved), so these run in well under a second.

Covers the cross-checks that are supposed to catch a part file that
doesn't actually belong in a given merge: event_offset/n_events mismatch
(wrong events merged in), avalanche_size_limit/geometry_type mismatch
(part run under different conditions), a malformed rng_seed, and a part
whose RunInfo tree is missing entirely (older macro build / failed run).
"""

import os
import tempfile
import unittest

import uproot

import _pathsetup  # noqa: F401
from run_avalanche_batch import _validate_part

_BASE_RUN_INFO = {
    "geometry_type": "triple_gem_field",
    "n_events": "10",
    "event_offset": "0",
    "avalanche_size_limit": "2000",
    "rng_seed": "123456",
}


def _write_part(path: str, run_info: dict[str, str] | None) -> None:
    with uproot.recreate(path) as f:
        if run_info is not None:
            f.mktree("RunInfoTrajectories", {"key": str, "value": str})
            f["RunInfoTrajectories"].extend({
                "key": list(run_info.keys()),
                "value": list(run_info.values()),
            })


def _job(path: str, **overrides) -> dict:
    job = {
        "part_root_path": path,
        "offset": 0,
        "n_events": 10,
        "avalanche_size_limit": 2000,
        "geometry_type": "triple_gem_field",
    }
    job.update(overrides)
    return job


class TestValidatePart(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".root")
        os.close(fd)

    def tearDown(self):
        os.remove(self.path)

    def test_consistent_part_has_no_problems(self):
        _write_part(self.path, _BASE_RUN_INFO)
        self.assertEqual(_validate_part(_job(self.path)), [])

    def test_missing_run_info_tree_is_a_problem(self):
        _write_part(self.path, None)
        problems = _validate_part(_job(self.path))
        self.assertEqual(len(problems), 1)
        self.assertIn("no RunInfo tree", problems[0])

    def test_event_offset_mismatch_detected(self):
        _write_part(self.path, _BASE_RUN_INFO)
        problems = _validate_part(_job(self.path, offset=5))
        self.assertTrue(any("event_offset" in p for p in problems))

    def test_n_events_mismatch_detected(self):
        _write_part(self.path, _BASE_RUN_INFO)
        problems = _validate_part(_job(self.path, n_events=999))
        self.assertTrue(any("n_events" in p for p in problems))

    def test_avalanche_size_limit_mismatch_detected(self):
        _write_part(self.path, _BASE_RUN_INFO)
        problems = _validate_part(_job(self.path, avalanche_size_limit=50000))
        self.assertTrue(any("avalanche_size_limit" in p for p in problems))

    def test_geometry_type_mismatch_detected(self):
        _write_part(self.path, _BASE_RUN_INFO)
        problems = _validate_part(_job(self.path, geometry_type="single_gem_field"))
        self.assertTrue(any("geometry_type" in p for p in problems))

    def test_malformed_seed_detected(self):
        run_info = dict(_BASE_RUN_INFO, rng_seed="auto (process-default)")
        _write_part(self.path, run_info)
        problems = _validate_part(_job(self.path))
        self.assertTrue(any("rng_seed" in p for p in problems))

    def test_seed_mismatch_from_a_retry_is_not_flagged(self):
        """_validate_part deliberately does not check rng_seed against the
        job's own expected seed -- see its docstring: a --retry-indices
        invocation without the original --base-seed legitimately computes
        a different, still-valid seed for an untouched part."""
        run_info = dict(_BASE_RUN_INFO, rng_seed="987654")
        _write_part(self.path, run_info)
        self.assertEqual(_validate_part(_job(self.path)), [])


if __name__ == "__main__":
    unittest.main()
