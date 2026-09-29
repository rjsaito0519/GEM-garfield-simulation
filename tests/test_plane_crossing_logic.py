"""Toy-trajectory tests for the genuine-downward-crossing logic shared by
analyze_plane_crossings.py / analyze_single_gem_plane_crossings.py --
Garfield++ is not involved at all here, only hand-built (x,y,z) arrays, so
these run in well under a second and don't need Elmer/Garfield/Gmsh.

Guards against regressing back to a naive "z.min() < plane" test, which
this project already hit once for real (see analyze_plane_crossings.py's
own module docstring: that mixes genuine crossings with electrons freshly
born below the plane).
"""

import unittest

import numpy as np

import _pathsetup  # noqa: F401
from analyze_plane_crossings import _crossed, _classify_z, _interpolated_xy_at_plane
from gem_unit_cell import hole_centers_tiled


class TestCrossed(unittest.TestCase):
    def test_case_a_crosses_from_above_to_below(self):
        z = np.array([1.0, 0.5, -0.5, -1.0])
        self.assertTrue(_crossed(z, 0.0))

    def test_case_b_born_already_below_plane_no_crossing(self):
        z = np.array([-0.5, -0.6, -0.7])
        self.assertFalse(_crossed(z, 0.0))

    def test_case_c_crosses_down_then_back_up_still_counts_once(self):
        z = np.array([1.0, -0.5, 0.5, 1.0])
        self.assertTrue(_crossed(z, 0.0))

    def test_single_point_track_never_crosses(self):
        z = np.array([1.0])
        self.assertFalse(_crossed(z, 0.0))

    def test_stays_above_plane_never_crosses(self):
        z = np.array([2.0, 1.5, 1.0])
        self.assertFalse(_crossed(z, 0.0))


class TestClassifyZ(unittest.TestCase):
    def test_classifies_into_matching_region(self):
        regions = [("upper", 0.0, 1.0), ("lower", -1.0, 0.0)]
        self.assertEqual(_classify_z(0.5, regions), "upper")
        self.assertEqual(_classify_z(-0.5, regions), "lower")

    def test_outside_all_regions_is_unknown(self):
        regions = [("upper", 0.0, 1.0)]
        self.assertEqual(_classify_z(5.0, regions), "?")


class TestInterpolatedXYAtPlane(unittest.TestCase):
    def test_interpolates_at_exact_crossing_fraction(self):
        x = np.array([0.0, 2.0])
        y = np.array([0.0, 4.0])
        z = np.array([1.0, -1.0])  # crosses z=0 exactly halfway
        xy = _interpolated_xy_at_plane(x, y, z, 0.0)
        self.assertIsNotNone(xy)
        self.assertAlmostEqual(xy[0], 1.0)
        self.assertAlmostEqual(xy[1], 2.0)

    def test_no_crossing_returns_none(self):
        x = np.array([0.0, 1.0])
        y = np.array([0.0, 1.0])
        z = np.array([1.0, 0.5])  # never goes below 0
        self.assertIsNone(_interpolated_xy_at_plane(x, y, z, 0.0))


class TestHoleApertureVsCopper(unittest.TestCase):
    """Case D/E from issue #17 item 3: whether an (x,y) crossing point
    falls inside a real hole opening or on the surrounding Cu -- the same
    min-distance-to-nearest-hole-center check used inline in both
    analyze_plane_crossings.py (GEM2 hole-entrance classification) and
    analyze_collection_efficiency.py (collection-efficiency cohort), not
    its own standalone function, so this test recomputes that one-line
    formula directly against gem_unit_cell.hole_centers_tiled()'s real
    output rather than importing a helper that doesn't exist.
    """

    def setUp(self):
        self.pitch_cm = 0.014
        self.hole_r_cm = 0.0025
        self.centers = hole_centers_tiled(self.pitch_cm, 3, 3)

    def _enters_hole(self, x, y):
        min_dist = min(np.hypot(x - hx, y - hy) for hx, hy in self.centers)
        return min_dist < self.hole_r_cm

    def test_case_d_on_axis_of_a_hole_enters(self):
        hx, hy = self.centers[0]
        self.assertTrue(self._enters_hole(hx, hy))

    def test_case_e_far_from_every_hole_center_hits_copper(self):
        hx, hy = self.centers[0]
        self.assertFalse(self._enters_hole(hx + self.pitch_cm / 2.0, hy))


if __name__ == "__main__":
    unittest.main()
