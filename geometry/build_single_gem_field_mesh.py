"""Milestone 2 (geometry step): mesh a single GEM foil plus its drift/transfer
gas gaps, ready to be handed to ElmerGrid/ElmerSolver.

Usage:
    python3 build_single_gem_field_mesh.py
Outputs (under geometry/output/):
    single_gem_field.msh              - mesh (Gmsh v2.2 format, for ElmerGrid)
    single_gem_field_model_info.json  - electrode potentials + permittivities, for the .sif writer
    single_gem_field_mesh_full.png / _mesh_gem_zoom.png - mesh check plots
"""

import json
import os

# matplotlib (via plot_utils) must be imported before gmsh -- see
# env_gmsh_matplotlib_libstdcxx memory note / build_single_gem.py for why.
from plot_utils import plot_mesh_cross_section

import gmsh
import numpy as np

from gem_params import GEM_50UM
from mesh_export import export_surface_groups_json
from single_gem_field_model import (
    COPPER_RELATIVE_PERMITTIVITY,
    DIELECTRIC_RELATIVE_PERMITTIVITY,
    SingleGemTestConfig,
    build_single_gem_field_model,
)

# Surface groups to export for the interactive 3D viewer (macros/output/field_viewer.html).
SURFACE_GROUPS_FOR_3D_VIEWER = [
    "TopCopperElectrode", "BottomCopperElectrode", "DielectricSurface",
    "DriftPlaneElectrode", "TransferPlaneElectrode",
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    params = GEM_50UM
    test_config = SingleGemTestConfig()

    gmsh.initialize()
    gmsh.model.add("single_gem_field")
    field_model = build_single_gem_field_model(params, test_config)
    print(f"[1/3] Geometry built. Electrode potentials: {field_model.electrode_potentials_v}")
    print(f"      Physical group IDs: {field_model.physical_group_ids}")

    # Same adaptive sizing idea as build_single_gem.py, but with a larger
    # MeshSizeMax since the drift/transfer gas gaps are much bigger than the
    # GEM hole itself: curvature-based refinement keeps the hole region fine
    # while the bulk gas volume is allowed to use coarser elements.
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 20)
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.0003)
    gmsh.option.setNumber("Mesh.MeshSizeMax", 0.02)
    gmsh.model.mesh.generate(3)

    # Export flat (first-order) surface triangles for the 3D viewer *before*
    # upgrading to second-order elements below -- Elmer/Garfield++ need
    # 10-node tets, but this export wants plain 3-node triangles.
    surfaces_path = os.path.join(OUTPUT_DIR, "single_gem_field_mesh_surfaces.json")
    surface_group_ids = {
        name: field_model.physical_group_ids[name] for name in SURFACE_GROUPS_FOR_3D_VIEWER
    }
    export_surface_groups_json(surface_group_ids, surfaces_path)
    print(f"      Surface mesh for 3D viewer written to {surfaces_path}")

    # Garfield++'s ComponentElmer expects second-order (10-node) tetrahedra,
    # matching Elmer's usual workflow (see GEM_Garfield/README.md: "gmsh
    # [SCRIPT_NAME].geo -3 -order 2"). Without this it fails with "Read 4
    # node indices for element0 (expected 10)".
    gmsh.model.mesh.setOrder(2)

    node_tags, node_coords_flat, _ = gmsh.model.mesh.getNodes()
    _, tet_element_tags, _ = gmsh.model.mesh.getElements(dim=3)
    n_tets = sum(len(tags) for tags in tet_element_tags)
    print(f"[2/3] Mesh generated: {len(node_tags)} nodes, {n_tets} tetrahedra")

    # ElmerGrid expects the older Gmsh v2.2 ASCII format.
    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    mesh_path = os.path.join(OUTPUT_DIR, "single_gem_field.msh")
    gmsh.write(mesh_path)

    node_coords = np.array(node_coords_flat).reshape(-1, 3)

    full_range_path = os.path.join(OUTPUT_DIR, "single_gem_field_mesh_full.png")
    plot_mesh_cross_section(
        node_coords, full_range_path, y_tolerance_cm=0.0005, equal_aspect=False
    )

    half_t_diel = params.dielectric_thickness_cm / 2.0
    z_gem_edge = half_t_diel + params.copper_thickness_cm
    zoom_path = os.path.join(OUTPUT_DIR, "single_gem_field_mesh_gem_zoom.png")
    plot_mesh_cross_section(
        node_coords, zoom_path, y_tolerance_cm=0.0005,
        z_range_cm=(-z_gem_edge - 0.0005, z_gem_edge + 0.0005),
    )
    print(f"[3/3] Mesh written to {mesh_path}; plots: {full_range_path}, {zoom_path}")

    gmsh.finalize()

    model_info_path = os.path.join(OUTPUT_DIR, "single_gem_field_model_info.json")
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
