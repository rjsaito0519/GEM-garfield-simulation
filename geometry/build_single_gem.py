"""Milestone 1: build and mesh a single 50 um GEM foil unit cell, and produce
check images so the geometry can be visually verified before anything is fed
into Elmer/Garfield++.

This intentionally stops at "one GEM foil, no gas gaps, no electric field yet" -
see README.md's status list for the next milestones.

Usage:
    python3 build_single_gem.py
Outputs (see docs/reference.md "出力ディレクトリ構成" for the full results/ layout):
    results/img/gem_50um_schematic.png          - intended hole cross-section, from parameters only
    results/img/gem_50um_mesh_cross_section.png - meshed hole cross-section, for comparison
    results/img/gem_50um_mesh_overview.png      - 3D overview of the meshed unit cell
    results/mesh/gem_50um_unit_cell.msh         - the mesh itself
"""

import os

import numpy as np

# NOTE: matplotlib (imported inside plot_utils) must be imported before gmsh.
# gmsh's native extension pulls in the system libstdc++ (via LD_LIBRARY_PATH,
# which lists /usr/lib64 first on this cluster); once that older libstdc++ is
# loaded into the process, matplotlib's compiled extension -- which needs a
# newer libstdc++ ABI -- fails to load. Importing matplotlib first makes it
# load its own (newer) bundled libstdc++ before gmsh gets a chance to.
from plot_utils import (
    plot_mesh_cross_section,
    plot_mesh_overview_3d,
    plot_parameter_schematic,
)

import gmsh

from gem_params import GEM_50UM
from gem_unit_cell import build_gem_layer

# results/ is this project's single consolidated output tree -- see
# docs/reference.md "出力ディレクトリ構成" for what belongs in each subdir.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
MESH_DIR = os.path.join(RESULTS_DIR, "mesh")
IMG_DIR = os.path.join(RESULTS_DIR, "img")


def main() -> None:
    for d in (MESH_DIR, IMG_DIR):
        os.makedirs(d, exist_ok=True)
    params = GEM_50UM

    # Step 1: sanity-check the input parameters on their own, before any meshing.
    schematic_path = os.path.join(IMG_DIR, "gem_50um_schematic.png")
    plot_parameter_schematic(params, schematic_path)
    print(f"[1/4] Parameter schematic written to {schematic_path}")

    # Step 2: build the solid geometry with the Gmsh OCC kernel.
    gmsh.initialize()
    gmsh.model.add("gem_50um_unit_cell")
    volumes = build_gem_layer(params)
    gmsh.model.addPhysicalGroup(
        3, [volumes["copper_top"], volumes["copper_bottom"]], name="Copper"
    )
    gmsh.model.addPhysicalGroup(3, [volumes["dielectric"]], name="Dielectric")
    print(f"[2/4] Geometry built: volumes = {volumes}")

    # Step 3: mesh it. MeshSizeFromCurvature adaptively refines near the
    # curved hole walls; Min/Max just bound how fine/coarse that is allowed
    # to get so the mesh stays a reasonable size for this first check.
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 20)
    gmsh.option.setNumber("Mesh.MeshSizeMin", 0.0003)
    gmsh.option.setNumber("Mesh.MeshSizeMax", 0.003)
    gmsh.model.mesh.generate(3)

    mesh_path = os.path.join(MESH_DIR, "gem_50um_unit_cell.msh")
    gmsh.write(mesh_path)

    node_tags, node_coords_flat, _ = gmsh.model.mesh.getNodes()
    node_coords = np.array(node_coords_flat).reshape(-1, 3)
    _, tet_element_tags, _ = gmsh.model.mesh.getElements(dim=3)
    n_tets = sum(len(tags) for tags in tet_element_tags)
    print(
        f"[3/4] Mesh generated: {len(node_tags)} nodes, {n_tets} tetrahedra, "
        f"written to {mesh_path}"
    )

    # Step 4: plot the actual mesh for a visual cross-check against the schematic.
    cross_section_path = os.path.join(IMG_DIR, "gem_50um_mesh_cross_section.png")
    plot_mesh_cross_section(node_coords, cross_section_path, y_tolerance_cm=0.0005)

    overview_path = os.path.join(IMG_DIR, "gem_50um_mesh_overview.png")
    plot_mesh_overview_3d(node_coords, overview_path)
    print(f"[4/4] Mesh check plots written to {cross_section_path} and {overview_path}")

    gmsh.finalize()


if __name__ == "__main__":
    main()
