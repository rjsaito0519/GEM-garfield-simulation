"""Elmer mesh.names parsing / material+electrode resolution tests
(elmer/write_sif.py) -- synthetic mesh.names text only, no ElmerGrid or
Elmer solver involved, so these run instantly.

Covers the normal case plus the two hard-failure cases write_sif.py is
specifically designed to catch instead of silently producing a
plausible-looking but physically wrong .sif: a missing electrode boundary
condition, and an unrecognized dielectric material.
"""

import os
import tempfile
import unittest

import _pathsetup  # noqa: F401
from write_sif import parse_mesh_names, resolve_body_permittivities, resolve_missing_electrodes

_MESH_NAMES_TEXT = """\
$ names for bodies $
$ Gas = 1 $
$ Dielectric = 2 $
$ Copper = 3 $
$ names for boundaries $
$ TopCopperElectrode = 1 $
$ BottomCopperElectrode = 2 $
$ DielectricSurface = 3 $
$ DriftPlaneElectrode = 4 $
$ TransferPlaneElectrode = 5 $
"""


class TestParseMeshNames(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".names")
        with os.fdopen(fd, "w") as f:
            f.write(_MESH_NAMES_TEXT)

    def tearDown(self):
        os.remove(self.path)

    def test_bodies_and_boundaries_parsed_into_separate_1_based_namespaces(self):
        body_ids, boundary_ids = parse_mesh_names(self.path)
        self.assertEqual(body_ids, {"Gas": 1, "Dielectric": 2, "Copper": 3})
        self.assertEqual(
            boundary_ids,
            {
                "TopCopperElectrode": 1, "BottomCopperElectrode": 2,
                "DielectricSurface": 3, "DriftPlaneElectrode": 4,
                "TransferPlaneElectrode": 5,
            },
        )


class TestResolveBodyPermittivities(unittest.TestCase):
    def setUp(self):
        self.model_info = {
            "dielectric_relative_permittivity": 3.5,
            "copper_relative_permittivity": 1.0e10,
        }

    def test_normal_case_resolves_every_known_body(self):
        body_ids = {"Gas": 1, "Dielectric": 2, "Copper": 3}
        result = resolve_body_permittivities(body_ids, self.model_info)
        self.assertEqual(result, {"Gas": 1.0, "Dielectric": 3.5, "Copper": 1.0e10})

    def test_unknown_material_is_a_hard_failure(self):
        body_ids = {"Gas": 1, "Glass": 2}
        with self.assertRaises(ValueError):
            resolve_body_permittivities(body_ids, self.model_info)


class TestResolveMissingElectrodes(unittest.TestCase):
    def test_all_electrodes_present_reports_none_missing(self):
        electrode_potentials_v = {"TopCopperElectrode": -100.0, "BottomCopperElectrode": 0.0}
        boundary_ids = {"TopCopperElectrode": 1, "BottomCopperElectrode": 2}
        self.assertEqual(resolve_missing_electrodes(electrode_potentials_v, boundary_ids), set())

    def test_electrode_missing_from_mesh_names_is_detected(self):
        electrode_potentials_v = {"TopCopperElectrode": -100.0, "BottomCopperElectrode": 0.0}
        boundary_ids = {"TopCopperElectrode": 1}  # BottomCopperElectrode absent
        self.assertEqual(
            resolve_missing_electrodes(electrode_potentials_v, boundary_ids),
            {"BottomCopperElectrode"},
        )


if __name__ == "__main__":
    unittest.main()
