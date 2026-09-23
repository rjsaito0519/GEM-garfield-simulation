"""PyVista-based 3D viewer: 3-GEM stack geometry + an electric-field slice,
overlaid in one interactive scene (see GitHub issue #3). Exports a
self-contained HTML file (client-side vtk.js rendering via trame/wslink --
no server-side GPU/X needed to *view* it, only to build it, and even
building it works fine off-screen since PyVista never actually rasterizes
for this export path).

Inputs (already produced by the existing Gmsh/Elmer/Garfield++ pipeline,
not regenerated here):
  - geometry/output/<baseName>_mesh_surfaces.json (geometry/mesh_export.py):
    {"vertices": [[x,y,z], ...], "groups": {name: [i,j,k, i,j,k, ...]}}
  - macros/output/<baseName>_field_slice_full.json (macros/export_field_samples.cpp):
    {"nx", "ny", "nz", "samples": [{x,y,z,ex,ey,ez,v,status}, ...]}
    with ny == 1 (a y=0 plane slice) -- see that macro's docstring.

Usage:
    ~/.conda/envs/work/bin/python3 plot_triple_gem.py [baseName] [output.html]
    baseName defaults to "triple_gem_field"; output defaults to
    visualization/output/<baseName>_overview.html.

Environment note: this project's default `python3` (the envfs-cached copy
of the `work` conda env, see README.md "実行環境") lags behind newly
pip-installed packages until `~/local/bin/envfs.sh repack work` is rerun --
use `~/.conda/envs/work/bin/python3` directly (the real env) until then.
Also: this environment's `vtk` pip wheel must be 9.3.x, not the newest
9.7.x -- a real trame_vtk/vtk 9.7 incompatibility (TypeError: unhashable
type 'VTKAOSArray_vtkFloatArray' inside trame_vtk's scene serializer) broke
HTML export; downgrading to vtk==9.3.1 fixed it (2026-09-23).
"""

import json
import os
import sys

import numpy as np
import pyvista as pv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOMETRY_OUTPUT_DIR = os.path.join(REPO_ROOT, "geometry", "output")
MACROS_OUTPUT_DIR = os.path.join(REPO_ROOT, "macros", "output")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# Group-name suffix -> (color, opacity). DielectricSurface is checked before
# the *CopperElectrode suffixes since e.g. "GEM1_DielectricSurface" would
# also match a naive "Electrode" substring check otherwise.
_GROUP_STYLE = [
    ("DielectricSurface", "#d4af37", 1.0),      # polyimide: gold/khaki
    ("TopCopperElectrode", "#b87333", 1.0),      # copper
    ("BottomCopperElectrode", "#b87333", 1.0),   # copper
    ("DriftPlaneElectrode", "#cccccc", 0.12),    # gas-box end cap: just context
    ("InductionPlaneElectrode", "#cccccc", 0.12),
]


def _style_for_group(name: str) -> tuple[str, float]:
    for suffix, color, opacity in _GROUP_STYLE:
        if name.endswith(suffix):
            return color, opacity
    return "#999999", 0.3  # fallback for any unrecognized group


def load_geometry_meshes(surfaces_json_path: str) -> dict[str, pv.PolyData]:
    """One pv.PolyData per named physical group (see mesh_export.py's schema)."""
    with open(surfaces_json_path) as f:
        data = json.load(f)
    vertices = np.array(data["vertices"])
    meshes = {}
    for name, flat_indices in data["groups"].items():
        if not flat_indices:
            continue
        tri = np.array(flat_indices, dtype=np.int64).reshape(-1, 3)
        # VTK's flat face format: [3, i, j, k, 3, i, j, k, ...] (3 = triangle
        # vertex count, must precede each face).
        faces = np.hstack([np.full((tri.shape[0], 1), 3, dtype=np.int64), tri]).ravel()
        meshes[name] = pv.PolyData(vertices, faces)
    return meshes


def load_field_slice(slice_json_path: str) -> pv.StructuredGrid:
    """The y=0 field slice (see export_field_samples.cpp) as a PyVista
    StructuredGrid with a log10(|E|) [V/cm] point-data array."""
    with open(slice_json_path) as f:
        data = json.load(f)
    nx, ny, nz = data["nx"], data["ny"], data["nz"]
    if ny != 1:
        raise ValueError(f"Expected a y=0 slice (ny=1), got ny={ny}")
    samples = data["samples"]
    x = np.array([s["x"] for s in samples]).reshape(nx, nz)
    z = np.array([s["z"] for s in samples]).reshape(nx, nz)
    ex = np.array([s["ex"] for s in samples]).reshape(nx, nz)
    ey = np.array([s["ey"] for s in samples]).reshape(nx, nz)
    ez = np.array([s["ez"] for s in samples]).reshape(nx, nz)
    e_mag = np.sqrt(ex**2 + ey**2 + ez**2)
    # Points with status < 0 (outside the mesh / not an active drift medium,
    # e.g. inside solid Cu/dielectric) still get a nominal E value from
    # ComponentElmer -- clip to a small floor before log10 so those don't
    # produce -inf, but they are mostly hidden behind the geometry meshes
    # anyway since this slice sits exactly at y=0 through the hole axis.
    log10_e = np.log10(np.clip(e_mag, 1.0, None))

    x3 = x[:, np.newaxis, :]
    y3 = np.zeros_like(x3)
    z3 = z[:, np.newaxis, :]
    grid = pv.StructuredGrid(x3, y3, z3)
    grid["log10(|E|) [V/cm]"] = log10_e.reshape(-1, order="F")
    return grid


def build_plotter(mesh_groups: dict[str, pv.PolyData], field_slice: pv.StructuredGrid) -> pv.Plotter:
    pl = pv.Plotter(off_screen=True)
    for name, mesh in mesh_groups.items():
        color, opacity = _style_for_group(name)
        pl.add_mesh(mesh, color=color, opacity=opacity, show_edges=False, label=name)
    pl.add_mesh(
        field_slice, scalars="log10(|E|) [V/cm]", cmap="turbo", opacity=0.6,
        show_scalar_bar=True,
    )
    pl.add_axes()
    pl.camera_position = "xz"
    return pl


def main() -> None:
    base_name = sys.argv[1] if len(sys.argv) > 1 else "triple_gem_field"
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    default_out = os.path.join(OUTPUT_DIR, f"{base_name}_overview.html")
    out_path = sys.argv[2] if len(sys.argv) > 2 else default_out

    surfaces_path = os.path.join(GEOMETRY_OUTPUT_DIR, f"{base_name}_mesh_surfaces.json")
    # NOTE: export_field_samples.cpp does NOT prefix its output files with
    # baseName (unlike everything else in this pipeline) -- it always
    # writes plain "field_slice_full.json" etc. into whatever output dir
    # was passed on its command line. Re-running it for a different model
    # overwrites the previous one; there is no way here to tell which model
    # macros/output/field_slice_full.json currently belongs to except by
    # re-running export_field_samples for base_name right before this.
    slice_path = os.path.join(MACROS_OUTPUT_DIR, "field_slice_full.json")

    mesh_groups = load_geometry_meshes(surfaces_path)
    print(f"Loaded {len(mesh_groups)} geometry groups from {surfaces_path}")
    field_slice = load_field_slice(slice_path)
    print(f"Loaded field slice ({field_slice.n_points} points) from {slice_path}")

    pl = build_plotter(mesh_groups, field_slice)
    pl.trame.export_html(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
