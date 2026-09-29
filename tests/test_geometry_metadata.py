"""Geometry/model-metadata test (geometry/single_gem_field_model.py) --
builds a minimal (single-cell, n_cells_x=n_cells_y=1) single-GEM geometry
through the real Gmsh/OCC API (no ElmerGrid/Elmer/Garfield++ involved) and
checks that geometry_info/electrode_potentials_v/physical_group_ids come
out with the expected keys and values.

Guards against two failure modes already seen for real in this project:
missing/incomplete geometry_info (macros/model_info.hh reads specific keys
from it and fails confusingly if one is absent), and stale hardcoded
values silently drifting out of sync with what was actually built (see
triple_gem_field_model.py's module docstring on why geometry_info records
the full simulation condition instead of being reconstructed from a fresh
default config).
"""

import dataclasses
import unittest

import gmsh

import _pathsetup  # noqa: F401
from gem_params import GEM_50UM
from single_gem_field_model import SingleGemTestConfig, build_single_gem_field_model


class TestSingleGemGeometryMetadata(unittest.TestCase):
    def setUp(self):
        gmsh.initialize()
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.add("test_single_gem_metadata")

    def tearDown(self):
        gmsh.finalize()

    def test_geometry_info_has_expected_keys_and_values(self):
        params = GEM_50UM
        test_config = dataclasses.replace(SingleGemTestConfig(), n_cells_x=1, n_cells_y=1)
        model = build_single_gem_field_model(params, test_config)

        expected_keys = {
            "pitch_cm", "half_extent_x_cm", "half_extent_y_cm",
            "z_domain_min_cm", "z_domain_max_cm", "n_cells_x", "n_cells_y",
            "z_gem_top_cm", "z_gem_bottom_cm", "copper_thickness_cm",
            "dielectric_thickness_cm", "hole_inner_radius_cm",
            "hole_outer_radius_cm", "gem_voltage_v", "drift_gap_cm",
            "drift_field_v_per_cm", "transfer_gap_cm", "transfer_field_v_per_cm",
        }
        self.assertEqual(set(model.geometry_info), expected_keys)

        self.assertAlmostEqual(model.geometry_info["pitch_cm"], params.pitch_cm)
        self.assertAlmostEqual(
            model.geometry_info["hole_inner_radius_cm"], params.hole_inner_radius_cm
        )
        self.assertAlmostEqual(
            model.geometry_info["hole_outer_radius_cm"], params.hole_outer_radius_cm
        )
        self.assertEqual(model.geometry_info["n_cells_x"], 1)
        self.assertEqual(model.geometry_info["n_cells_y"], 1)
        # A single unit cell's half-extent is exactly pitch/2 x pitch*sqrt(3)/2
        # -- see build_single_gem_field_model's half_extent_x/y_cm computation.
        self.assertAlmostEqual(model.geometry_info["half_extent_x_cm"], params.pitch_cm / 2.0)
        # Domain must be strictly larger than the GEM foil itself.
        self.assertLess(model.geometry_info["z_domain_min_cm"], model.geometry_info["z_gem_bottom_cm"])
        self.assertGreater(model.geometry_info["z_domain_max_cm"], model.geometry_info["z_gem_top_cm"])

    def test_electrode_potentials_and_physical_groups_present(self):
        params = GEM_50UM
        test_config = dataclasses.replace(SingleGemTestConfig(), n_cells_x=1, n_cells_y=1)
        model = build_single_gem_field_model(params, test_config)

        expected_electrodes = {
            "TopCopperElectrode", "BottomCopperElectrode",
            "DriftPlaneElectrode", "TransferPlaneElectrode",
        }
        self.assertEqual(set(model.electrode_potentials_v), expected_electrodes)
        # Bottom copper is the reference (0V); top copper is biased below it
        # by the GEM voltage -- see build_single_gem_field_model's electrical
        # reference comment.
        self.assertEqual(model.electrode_potentials_v["BottomCopperElectrode"], 0.0)
        self.assertAlmostEqual(
            model.electrode_potentials_v["TopCopperElectrode"], -test_config.gem_voltage_v
        )

        expected_groups = {
            "Gas", "Dielectric", "Copper", "TopCopperElectrode",
            "BottomCopperElectrode", "DielectricSurface",
            "DriftPlaneElectrode", "TransferPlaneElectrode",
        }
        self.assertEqual(set(model.physical_group_ids), expected_groups)
        # Every physical group tag must be a distinct positive Gmsh tag.
        tags = list(model.physical_group_ids.values())
        self.assertEqual(len(tags), len(set(tags)))
        self.assertTrue(all(t > 0 for t in tags))


if __name__ == "__main__":
    unittest.main()
