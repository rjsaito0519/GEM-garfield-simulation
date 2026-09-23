"""Build and mesh the full 3-GEM stack (drift -> GEM1 -> transfer1 -> GEM2
-> transfer2 -> GEM3 -> induction -> pad plane), ready for ElmerGrid/
ElmerSolver. Mirrors build_single_gem_field_mesh.py -- see that file's
docstring for why matplotlib must be imported before gmsh, why the mesh
needs second-order elements, etc.

Usage:
    python3 build_triple_gem_field_mesh.py
Outputs (see docs/reference.md "出力ディレクトリ構成" for the full results/ layout):
    results/mesh/triple_gem_field.msh              - mesh (Gmsh v2.2 format, for ElmerGrid)
    results/json/triple_gem_field_model_info.json  - electrode potentials + permittivities
    results/img/triple_gem_field_mesh_full.png     - mesh check plot (full z range)
"""

import json
import os

from plot_utils import plot_mesh_cross_section

import gmsh
import numpy as np

from mesh_export import export_surface_groups_json
from triple_gem_field_model import (
    COPPER_RELATIVE_PERMITTIVITY,
    DIELECTRIC_RELATIVE_PERMITTIVITY,
    TripleGemTestConfig,
    build_triple_gem_field_model,
)

# results/ is this project's single consolidated output tree -- see
# docs/reference.md "出力ディレクトリ構成" for what belongs in each subdir.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
MESH_DIR = os.path.join(RESULTS_DIR, "mesh")
JSON_DIR = os.path.join(RESULTS_DIR, "json")
IMG_DIR = os.path.join(RESULTS_DIR, "img")


def main() -> None:
    for d in (MESH_DIR, JSON_DIR, IMG_DIR):
        os.makedirs(d, exist_ok=True)
    config = TripleGemTestConfig()

    gmsh.initialize()
    gmsh.model.add("triple_gem_field")
    field_model = build_triple_gem_field_model(config)
    print(f"[1/3] Geometry built. Electrode potentials: {field_model.electrode_potentials_v}")

    surface_groups = {
        name: field_model.physical_group_ids[name]
        for name in field_model.physical_group_ids
        if name.endswith(("TopCopperElectrode", "BottomCopperElectrode", "DielectricSurface"))
        or name in ("DriftPlaneElectrode", "InductionPlaneElectrode")
    }

    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 20)
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.0003)
    gmsh.option.setNumber("Mesh.MeshSizeMax", 0.02)
    gmsh.model.mesh.generate(3)

    surfaces_path = os.path.join(JSON_DIR, "triple_gem_field_mesh_surfaces.json")
    export_surface_groups_json(surface_groups, surfaces_path)
    print(f"      Surface mesh for 3D viewer written to {surfaces_path}")

    gmsh.model.mesh.setOrder(2)

    node_tags, node_coords_flat, _ = gmsh.model.mesh.getNodes()
    _, tet_element_tags, _ = gmsh.model.mesh.getElements(dim=3)
    n_tets = sum(len(tags) for tags in tet_element_tags)
    print(f"[2/3] Mesh generated: {len(node_tags)} nodes, {n_tets} tetrahedra")

    gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    mesh_path = os.path.join(MESH_DIR, "triple_gem_field.msh")
    gmsh.write(mesh_path)

    node_coords = np.array(node_coords_flat).reshape(-1, 3)
    full_range_path = os.path.join(IMG_DIR, "triple_gem_field_mesh_full.png")
    plot_mesh_cross_section(node_coords, full_range_path, y_tolerance_cm=0.0005, equal_aspect=False)
    print(f"[3/3] Mesh written to {mesh_path}; plot: {full_range_path}")

    gmsh.finalize()

    model_info_path = os.path.join(JSON_DIR, "triple_gem_field_model_info.json")
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
