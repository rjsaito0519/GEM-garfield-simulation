"""Generate the Elmer solver input file (.sif) for an electrostatics test
(single-GEM or the full 3-GEM stack -- this script is geometry-agnostic).

Combines two inputs:
  - electrode potentials / material permittivities from the geometry
    script's "<mesh_name>_model_info.json".
  - body/boundary target IDs from mesh.names, which ElmerGrid writes *after*
    converting the Gmsh mesh. ElmerGrid renumbers boundary physical groups to
    a compact range starting at 1 (e.g. our Gmsh tags 4-7 became 1-4), so the
    original Gmsh physical group IDs are NOT valid Target Body/Boundary
    indices for the .sif -- mesh.names is the authoritative mapping.

This script must therefore run *after* ElmerGrid, not before it.

Usage:
    python3 write_sif.py <mesh_name>   # e.g. single_gem_field or triple_gem_field
"""

import json
import os
import re
import sys

# results/ is this project's single consolidated output tree -- see
# docs/reference.md "出力ディレクトリ構成" for what belongs in each subdir.
# mesh.names/dielectrics.dat/.sif live in the ElmerGrid-created MESH_DIR
# subdirectory; model_info.json is a sibling under JSON_DIR, not the same
# directory (unlike this project's original geometry/output/ layout).
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
MESH_DIR = os.path.join(REPO_ROOT, "results", "mesh")
JSON_DIR = os.path.join(REPO_ROOT, "results", "json")


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


_SOLVER_BLOCK = """\
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
"""


def build_sif_text(
    mesh_name: str,
    body_ids: dict[str, int],
    boundary_ids: dict[str, int],
    body_permittivities: dict[str, float],
    electrode_potentials_v: dict[str, float],
) -> str:
    """Build the .sif text from whatever bodies/boundaries are present --
    works for the single-GEM model (3 bodies, 4 electrodes) and the 3-GEM
    stack (3 bodies, 8 electrodes) alike, without hardcoding either shape.
    """
    blocks = [
        f'Header\n  Mesh DB "." "{mesh_name}"\nEnd\n',
        f'Simulation\n'
        f'  Max Output Level = 5\n'
        f'  Coordinate System = Cartesian\n'
        f'  Coordinate Mapping(3) = 1 2 3\n'
        f'  Simulation Type = Steady State\n'
        f'  Steady State Max Iterations = 1\n'
        f'  Output Intervals = 1\n'
        f'  Output File = "{mesh_name}.result"\n'
        f'  Post File = "{mesh_name}.vtu"\n'
        f'End\n',
        'Constants\n  Permittivity of Vacuum = 8.8542e-12\nEnd\n',
    ]

    # Bodies/materials: one pair per body, in mesh.names' own ID order so
    # "Material N" always lines up with "Body N".
    body_names = sorted(body_ids, key=lambda name: body_ids[name])
    for i, name in enumerate(body_names, start=1):
        blocks.append(
            f'Body {i}\n'
            f'  Name = "{name}"\n'
            f'  Target Bodies(1) = {body_ids[name]}\n'
            f'  Equation = 1\n'
            f'  Material = {i}\n'
            f'End\n'
        )

    blocks.append('Equation 1\n  Name = "Electrostatics"\n  Active Solvers(1) = 1\nEnd\n')
    blocks.append(_SOLVER_BLOCK)

    for i, name in enumerate(body_names, start=1):
        eps = body_permittivities.get(name, 1.0)
        blocks.append(f'Material {i}\n  Name = "{name}"\n  Relative Permittivity = {eps}\nEnd\n')

    # Boundaries: only the ones with a defined potential are real
    # electrodes; e.g. "*_DielectricSurface" boundaries exist for the 3D
    # viewer only and are intentionally left with Elmer's natural BC.
    electrode_names = sorted(
        (name for name in boundary_ids if name in electrode_potentials_v),
        key=lambda name: boundary_ids[name],
    )
    for i, name in enumerate(electrode_names, start=1):
        blocks.append(
            f'Boundary Condition {i}\n'
            f'  Name = "{name}"\n'
            f'  Target Boundaries(1) = {boundary_ids[name]}\n'
            f'  Potential = {electrode_potentials_v[name]}\n'
            f'End\n'
        )

    return "\n".join(blocks)


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python3 write_sif.py <mesh_name>  (e.g. single_gem_field, triple_gem_field)")
        sys.exit(1)
    mesh_name = sys.argv[1]

    model_info_path = os.path.join(JSON_DIR, f"{mesh_name}_model_info.json")
    with open(model_info_path) as f:
        model_info = json.load(f)

    mesh_names_path = os.path.join(MESH_DIR, mesh_name, "mesh.names")
    body_ids, boundary_ids = parse_mesh_names(mesh_names_path)

    dielectrics_path = os.path.join(MESH_DIR, mesh_name, "dielectrics.dat")
    body_permittivities = {
        "Gas": 1.0,
        "Dielectric": model_info["dielectric_relative_permittivity"],
        "Copper": model_info["copper_relative_permittivity"],
    }
    write_dielectrics_dat(body_ids, body_permittivities, dielectrics_path)
    print(f"Wrote {dielectrics_path}")

    sif_text = build_sif_text(
        mesh_name, body_ids, boundary_ids, body_permittivities, model_info["electrode_potentials_v"]
    )
    output_path = os.path.join(MESH_DIR, f"{mesh_name}.sif")
    with open(output_path, "w") as f:
        f.write(sif_text)
    print(f"Wrote {output_path}. Body IDs: {body_ids}, boundary IDs: {boundary_ids}")


if __name__ == "__main__":
    main()
