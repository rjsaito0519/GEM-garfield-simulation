"""Standalone single-GEM electrostatics test for GEM1's *actual* current
conditions in the 3-GEM stack (100 um GEM, ΔV=457.5V) -- as opposed to
build_single_gem_field_mesh.py, which uses the 50 um GEM's parameters
(305V) left over from the original Milestone-2 test.

Built to answer a specific debugging question (see docs/debugging_notes.md,
"Step 4" of the user-provided investigation plan, 2026-09-22/23): is GEM1's
near-zero electron transmission into the transfer gap a property of GEM1's
own hole geometry/field in isolation, or does it depend on the rest of the
3-GEM stack? This is a single, untiled hex unit cell (unlike the 3-GEM
stack's 3x3 tiling) -- some of its own StatusLeftDriftMedium losses will
include the single-cell domain-boundary-escape artifact (~16% in the
triple-stack run, see docs/debugging_notes.md), which must be accounted for
separately when interpreting the result, not conflated with genuine
hole-wall loss.

Usage:
    python3 build_single_gem100_field_mesh.py
Outputs (see docs/reference.md "出力ディレクトリ構成" for the full results/ layout):
    results/mesh/single_gem100_field.msh              - mesh (Gmsh v2.2 format, for ElmerGrid)
    results/json/single_gem100_field_model_info.json  - electrode potentials + permittivities + geometry
    results/img/single_gem100_field_mesh_full.png / _mesh_gem_zoom.png - mesh check plots
"""

import json
import os
import sys

from plot_utils import plot_mesh_cross_section

import gmsh
import numpy as np

from gem_params import GEM_100UM
from mesh_export import export_surface_groups_json
from single_gem_field_model import (
    COPPER_RELATIVE_PERMITTIVITY,
    DIELECTRIC_RELATIVE_PERMITTIVITY,
    SingleGemTestConfig,
    build_single_gem_field_model,
)

SURFACE_GROUPS_FOR_3D_VIEWER = [
    "TopCopperElectrode", "BottomCopperElectrode", "DielectricSurface",
    "DriftPlaneElectrode", "TransferPlaneElectrode",
]

# results/ is this project's single consolidated output tree -- see
# docs/reference.md "出力ディレクトリ構成" for what belongs in each subdir.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
MESH_DIR = os.path.join(RESULTS_DIR, "mesh")
JSON_DIR = os.path.join(RESULTS_DIR, "json")
IMG_DIR = os.path.join(RESULTS_DIR, "img")

# Optional CLI override for transfer_field_v_per_cm, for the diagnostic
# "does a stronger extraction field recover transmission" scan (see
# docs/debugging_notes.md, "Step 6" of the user-provided investigation
# plan) -- NOT meant to represent a real operating point, just to test
# field-strength sensitivity. Encoded into the output base name so each
# field value gets its own mesh/result dir instead of clobbering the
# baseline single_gem100_field.
_TRANSFER_FIELD_V_PER_CM = float(sys.argv[1]) if len(sys.argv) > 1 else 2000.0
BASE_NAME = (
    "single_gem100_field"
    if _TRANSFER_FIELD_V_PER_CM == 2000.0
    else f"single_gem100_field_tf{int(_TRANSFER_FIELD_V_PER_CM)}"
)

# Matches GEM1's actual conditions in TripleGemTestConfig
# (geometry/triple_gem_field_model.py): drift_gap/transfer_gap/fields
# identical, gem_voltage_v = 1.5 * 305.0 (the 100um-GEM voltage rule).
TEST_CONFIG = SingleGemTestConfig(
    drift_gap_cm=0.42,
    drift_field_v_per_cm=130.0,
    transfer_gap_cm=0.20,
    transfer_field_v_per_cm=_TRANSFER_FIELD_V_PER_CM,
    gem_voltage_v=1.5 * 305.0,
)


def main() -> None:
    for d in (MESH_DIR, JSON_DIR, IMG_DIR):
        os.makedirs(d, exist_ok=True)
    params = GEM_100UM

    gmsh.initialize()
    gmsh.model.add(BASE_NAME)
    field_model = build_single_gem_field_model(params, TEST_CONFIG)
    print(f"[1/3] Geometry built. Electrode potentials: {field_model.electrode_potentials_v}")
    print(f"      Physical group IDs: {field_model.physical_group_ids}")

    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 20)
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.0003)
    gmsh.option.setNumber("Mesh.MeshSizeMax", 0.02)
    gmsh.model.mesh.generate(3)

    surfaces_path = os.path.join(JSON_DIR, f"{BASE_NAME}_mesh_surfaces.json")
    surface_group_ids = {
        name: field_model.physical_group_ids[name] for name in SURFACE_GROUPS_FOR_3D_VIEWER
    }
    export_surface_groups_json(surface_group_ids, surfaces_path)
    print(f"      Surface mesh for 3D viewer written to {surfaces_path}")

    gmsh.model.mesh.setOrder(2)

    node_tags, node_coords_flat, _ = gmsh.model.mesh.getNodes()
    _, tet_element_tags, _ = gmsh.model.mesh.getElements(dim=3)
    n_tets = sum(len(tags) for tags in tet_element_tags)
    print(f"[2/3] Mesh generated: {len(node_tags)} nodes, {n_tets} tetrahedra")

    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    mesh_path = os.path.join(MESH_DIR, f"{BASE_NAME}.msh")
    gmsh.write(mesh_path)

    node_coords = np.array(node_coords_flat).reshape(-1, 3)

    full_range_path = os.path.join(IMG_DIR, f"{BASE_NAME}_mesh_full.png")
    plot_mesh_cross_section(
        node_coords, full_range_path, y_tolerance_cm=0.0005, equal_aspect=False
    )

    half_t_diel = params.dielectric_thickness_cm / 2.0
    z_gem_edge = half_t_diel + params.copper_thickness_cm
    zoom_path = os.path.join(IMG_DIR, f"{BASE_NAME}_mesh_gem_zoom.png")
    plot_mesh_cross_section(
        node_coords, zoom_path, y_tolerance_cm=0.0005,
        z_range_cm=(-z_gem_edge - 0.0005, z_gem_edge + 0.0005),
    )
    print(f"[3/3] Mesh written to {mesh_path}; plots: {full_range_path}, {zoom_path}")

    gmsh.finalize()

    model_info_path = os.path.join(JSON_DIR, f"{BASE_NAME}_model_info.json")
    with open(model_info_path, "w") as f:
        json.dump(
            {
                "physical_group_ids": field_model.physical_group_ids,
                "electrode_potentials_v": field_model.electrode_potentials_v,
                "dielectric_relative_permittivity": DIELECTRIC_RELATIVE_PERMITTIVITY,
                "copper_relative_permittivity": COPPER_RELATIVE_PERMITTIVITY,
                "geometry": field_model.geometry_info,
            },
            f,
            indent=2,
        )
    print(f"Model info (for the .sif writer) written to {model_info_path}")


if __name__ == "__main__":
    main()
