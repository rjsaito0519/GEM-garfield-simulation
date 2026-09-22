"""Generate the Elmer solver input file (.sif) for the single-GEM electrostatics test.

Combines two inputs:
  - electrode potentials / material permittivities from
    geometry/build_single_gem_field_mesh.py's model info JSON.
  - body/boundary target IDs from mesh.names, which ElmerGrid writes *after*
    converting the Gmsh mesh. ElmerGrid renumbers boundary physical groups to
    a compact range starting at 1 (e.g. our Gmsh tags 4-7 became 1-4), so the
    original Gmsh physical group IDs are NOT valid Target Body/Boundary
    indices for the .sif -- mesh.names is the authoritative mapping.

This script must therefore run *after* ElmerGrid, not before it.

Usage:
    python3 write_sif.py
"""

import json
import os
import re

GEOMETRY_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "geometry", "output")
MESH_NAME = "single_gem_field"  # matches the .msh file name from build_single_gem_field_mesh.py


def write_dielectrics_dat(
    body_ids: dict[str, int], body_permittivities: dict[str, float], output_path: str
) -> None:
    """Write the "materials properties" file that ComponentElmer's 4th
    constructor argument (mplist) expects.

    Confirmed against Garfield++'s own source (ComponentElmer.cc): despite
    its common name "dielectrics.dat", the per-line material ID is actually
    *ignored* by the parser -- what matters is line *position*. Line 1 is
    the array size, and line (2 + i) fills array slot i with a permittivity.

    Element material indices in mesh.elements are Elmer's own body IDs
    (1-based, matching mesh.names), but ComponentElmer subtracts 1 from them
    right after reading ("int imat = ReadInteger(token, ...) - 1;") before
    using them as the array index -- so slot i corresponds to body ID i+1,
    NOT body ID i. Any code elsewhere that also references a material by
    index (e.g. ComponentElmer::SetMedium/DriftMedium in the macros under
    macros/) must use this same body-ID-minus-1 convention.
    """
    max_id = max(body_ids.values())
    permittivity_by_slot = [1.0] * max_id
    for name, body_id in body_ids.items():
        if name in body_permittivities:
            permittivity_by_slot[body_id - 1] = body_permittivities[name]

    with open(output_path, "w") as f:
        f.write(f"{len(permittivity_by_slot)}\n")
        for slot, eps in enumerate(permittivity_by_slot):
            f.write(f"{slot} {eps}\n")


def parse_mesh_names(mesh_names_path: str) -> tuple[dict[str, int], dict[str, int]]:
    """Parse ElmerGrid's mesh.names file into (body_ids, boundary_ids).

    The file has two sections ("names for bodies" / "names for boundaries"),
    each restarting its own 1-based numbering -- they must be kept separate,
    not merged into one {name: id} dict, or a boundary ID could accidentally
    be read as a body ID (or vice versa) by code further down the pipeline.
    """
    body_ids: dict[str, int] = {}
    boundary_ids: dict[str, int] = {}
    current_section = None
    with open(mesh_names_path) as f:
        for line in f:
            if "names for bodies" in line:
                current_section = body_ids
            elif "names for boundaries" in line:
                current_section = boundary_ids
            match = re.match(r"\$\s*(\w+)\s*=\s*(\d+)", line)
            if match and current_section is not None:
                current_section[match.group(1)] = int(match.group(2))
    return body_ids, boundary_ids

SIF_TEMPLATE = """\
Header
  Mesh DB "." "{mesh_name}"
End

Simulation
  Max Output Level = 5
  Coordinate System = Cartesian
  Coordinate Mapping(3) = 1 2 3
  Simulation Type = Steady State
  Steady State Max Iterations = 1
  Output Intervals = 1
  Output File = "{mesh_name}.result"
  Post File = "{mesh_name}.vtu"
End

Constants
  Permittivity of Vacuum = 8.8542e-12
End

Body 1
  Name = "Gas"
  Target Bodies(1) = {gas_id}
  Equation = 1
  Material = 1
End

Body 2
  Name = "Dielectric"
  Target Bodies(1) = {dielectric_id}
  Equation = 1
  Material = 2
End

Body 3
  Name = "Copper"
  Target Bodies(1) = {copper_id}
  Equation = 1
  Material = 3
End

Equation 1
  Name = "Electrostatics"
  Active Solvers(1) = 1
End

Solver 1
  Equation = Stat Elec Solver
  Procedure = "StatElecSolve" "StatElecSolver"
  Variable = Potential
  Variable Dofs = 1
  Calculate Electric Field = True
  Calculate Electric Energy = False
  Linear System Solver = Iterative
  Linear System Iterative Method = CG
  Linear System Preconditioning = ILU1
  Linear System Max Iterations = 2000
  Linear System Convergence Tolerance = 1.0e-10
  Steady State Convergence Tolerance = 1.0e-8
End

Material 1
  Name = "Gas"
  Relative Permittivity = 1.0
End

Material 2
  Name = "Dielectric"
  Relative Permittivity = {dielectric_permittivity}
End

Material 3
  Name = "Copper"
  Relative Permittivity = {copper_permittivity}
End

Boundary Condition 1
  Name = "TopCopperElectrode"
  Target Boundaries(1) = {top_copper_id}
  Potential = {top_copper_v}
End

Boundary Condition 2
  Name = "BottomCopperElectrode"
  Target Boundaries(1) = {bottom_copper_id}
  Potential = {bottom_copper_v}
End

Boundary Condition 3
  Name = "DriftPlaneElectrode"
  Target Boundaries(1) = {drift_plane_id}
  Potential = {drift_plane_v}
End

Boundary Condition 4
  Name = "TransferPlaneElectrode"
  Target Boundaries(1) = {transfer_plane_id}
  Potential = {transfer_plane_v}
End
"""


def write_sif(
    model_info: dict,
    body_ids: dict[str, int],
    boundary_ids: dict[str, int],
    output_path: str,
) -> None:
    potentials = model_info["electrode_potentials_v"]

    sif_text = SIF_TEMPLATE.format(
        mesh_name=MESH_NAME,
        gas_id=body_ids["Gas"],
        dielectric_id=body_ids["Dielectric"],
        copper_id=body_ids["Copper"],
        dielectric_permittivity=model_info["dielectric_relative_permittivity"],
        copper_permittivity=model_info["copper_relative_permittivity"],
        top_copper_id=boundary_ids["TopCopperElectrode"],
        top_copper_v=potentials["TopCopperElectrode"],
        bottom_copper_id=boundary_ids["BottomCopperElectrode"],
        bottom_copper_v=potentials["BottomCopperElectrode"],
        drift_plane_id=boundary_ids["DriftPlaneElectrode"],
        drift_plane_v=potentials["DriftPlaneElectrode"],
        transfer_plane_id=boundary_ids["TransferPlaneElectrode"],
        transfer_plane_v=potentials["TransferPlaneElectrode"],
    )
    with open(output_path, "w") as f:
        f.write(sif_text)


def main() -> None:
    model_info_path = os.path.join(GEOMETRY_OUTPUT_DIR, f"{MESH_NAME}_model_info.json")
    with open(model_info_path) as f:
        model_info = json.load(f)

    mesh_names_path = os.path.join(GEOMETRY_OUTPUT_DIR, MESH_NAME, "mesh.names")
    body_ids, boundary_ids = parse_mesh_names(mesh_names_path)

    dielectrics_path = os.path.join(GEOMETRY_OUTPUT_DIR, MESH_NAME, "dielectrics.dat")
    body_permittivities = {
        "Gas": 1.0,
        "Dielectric": model_info["dielectric_relative_permittivity"],
        "Copper": model_info["copper_relative_permittivity"],
    }
    write_dielectrics_dat(body_ids, body_permittivities, dielectrics_path)
    print(f"Wrote {dielectrics_path}")

    output_path = os.path.join(GEOMETRY_OUTPUT_DIR, f"{MESH_NAME}.sif")
    write_sif(model_info, body_ids, boundary_ids, output_path)
    print(f"Wrote {output_path}. Body IDs: {body_ids}, boundary IDs: {boundary_ids}")


if __name__ == "__main__":
    main()
