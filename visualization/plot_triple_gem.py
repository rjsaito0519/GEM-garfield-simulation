"""PyVista-based 3D viewer: 3-GEM stack geometry + an electric-field slice,
overlaid in one interactive scene. Exports a self-contained HTML file
(client-side vtk.js rendering via trame/wslink --
no server-side GPU/X needed to *view* it, only to build it, and even
building it works fine off-screen since PyVista never actually rasterizes
for this export path).

Inputs (already produced by the existing Gmsh/Elmer/Garfield++ pipeline,
not regenerated here; see docs/reference.md "出力ディレクトリ構成"):
  - results/json/<baseName>_mesh_surfaces.json (geometry/mesh_export.py):
    {"vertices": [[x,y,z], ...], "groups": {name: [i,j,k, i,j,k, ...]}}
  - results/json/<baseName>_field_slice_full.json (macros/export_field_samples.cpp):
    {"nx", "ny", "nz", "samples": [{x,y,z,ex,ey,ez,v,status}, ...]}
    with ny == 1 (a y=0 plane slice) -- see that macro's docstring.
  - results/root/<baseName>_avalanche.root, tree "Trajectories"
    (macros/export_avalanche_trajectories.cpp), optional: branches
    event,track,x,y,z,t,energy -- one entry per recorded drift-line point.
    Skipped if the file/tree doesn't exist (run export_avalanche_trajectories
    first to get one).
  - results/json/<baseName>_field_vectors_full.json (macros/export_field_samples.cpp):
    same {"nx","ny","nz","samples"} schema as the slice file, but a genuine
    3D grid (ny > 1) -- used to seed E-field streamlines through the hole.

Usage:
    python3 plot_triple_gem.py [baseName] [output.html]
    baseName defaults to "triple_gem_field"; output defaults to
    results/html/<baseName>_overview.html.

Environment note: the `vtk` pip package must be pinned to 9.3.x, not the
newest 9.7.x -- a real trame_vtk/vtk 9.7 incompatibility (TypeError:
unhashable type 'VTKAOSArray_vtkFloatArray' inside trame_vtk's scene
serializer) breaks HTML export; `pip install "vtk==9.3.1"` (after
installing pyvista, so the pin takes effect) fixes it.
"""

import json
import os
import sys

import numpy as np
import pyvista as pv
import uproot

# results/ is this project's single consolidated output tree -- see
# docs/reference.md "出力ディレクトリ構成" for what belongs in each subdir.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
JSON_DIR = os.path.join(RESULTS_DIR, "json")
ROOT_DIR = os.path.join(RESULTS_DIR, "root")
HTML_DIR = os.path.join(RESULTS_DIR, "html")

# Group-name suffix -> (color, opacity). DielectricSurface is checked before
# the *CopperElectrode suffixes since e.g. "GEM1_DielectricSurface" would
# also match a naive "Electrode" substring check otherwise.
_GROUP_STYLE = [
    ("DielectricSurface", "#d4af37", 1.0),      # polyimide: gold/khaki
    ("TopCopperElectrode", "#b87333", 1.0),      # copper
    ("BottomCopperElectrode", "#b87333", 1.0),   # copper
    ("DriftPlaneElectrode", "#cccccc", 0.12),    # gas-box end cap: just context
    ("InductionPlaneElectrode", "#cccccc", 0.12),
    ("TransferPlaneElectrode", "#cccccc", 0.12),  # single-GEM test model only
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


def load_field_vector_grid(vectors_json_path: str) -> pv.StructuredGrid:
    """The full 3D field-vector grid (see export_field_samples.cpp) as a
    PyVista StructuredGrid with an "E" vector point-data array, for seeding
    streamlines. Coarser than the slice grid (it has to stay a manageable
    size as a real 3D array, not a 2D plane) so streamlines through a
    narrow GEM hole will only be approximately resolved."""
    with open(vectors_json_path) as f:
        data = json.load(f)
    nx, ny, nz = data["nx"], data["ny"], data["nz"]
    samples = data["samples"]
    x = np.array([s["x"] for s in samples]).reshape(nx, ny, nz)
    y = np.array([s["y"] for s in samples]).reshape(nx, ny, nz)
    z = np.array([s["z"] for s in samples]).reshape(nx, ny, nz)
    ex = np.array([s["ex"] for s in samples]).reshape(nx, ny, nz)
    ey = np.array([s["ey"] for s in samples]).reshape(nx, ny, nz)
    ez = np.array([s["ez"] for s in samples]).reshape(nx, ny, nz)

    grid = pv.StructuredGrid(x, y, z)
    vectors = np.stack(
        [ex.reshape(-1, order="F"), ey.reshape(-1, order="F"), ez.reshape(-1, order="F")],
        axis=1,
    )
    grid["E"] = vectors
    return grid


def compute_streamlines(
    vector_grid: pv.StructuredGrid, z_seed_cm: float, seed_radius_cm: float, n_seeds: int = 12
) -> pv.PolyData:
    """Seed a ring of points at z_seed_cm around the hole axis (x=y=0) and
    trace E-field lines through the grid in both directions -- z_seed_cm
    should be just above a GEM foil's hole, in the drift/transfer gas,
    where the field is still fairly uniform and every seed should funnel
    into the same hole."""
    theta = np.linspace(0, 2 * np.pi, n_seeds, endpoint=False)
    seeds = pv.PolyData(np.stack(
        [seed_radius_cm * np.cos(theta), seed_radius_cm * np.sin(theta),
         np.full(n_seeds, z_seed_cm)],
        axis=1,
    ))
    return vector_grid.streamlines_from_source(
        seeds, vectors="E", integration_direction="both", max_length=100.0,
    )


def load_trajectories(root_path: str, max_points: int = 15_000) -> pv.PolyData | None:
    """All (event,track) drift lines in one PolyData (one VTK "lines" cell
    per track), colored by kinetic energy [eV] -- much cheaper to render
    than adding each track as its own actor when there can be 50+ per event
    (see export_avalanche_trajectories.cpp's "Trajectories" tree).

    Downsampled to roughly max_points total points (per-track stride, always
    keeping each track's first/last point so line topology stays intact).
    Without this, a several-hundred-event run produces an HTML file tens
    of MB in size (client-side vtk.js embeds every point), which is both
    slow to open in a browser and too large to publish as a shareable
    artifact.
    """
    with uproot.open(root_path) as f:
        arrays = f["Trajectories"].arrays(
            ["event", "track", "x", "y", "z", "energy"], library="np"
        )
    event, track = arrays["event"], arrays["track"]
    keys = np.unique(np.stack([event, track], axis=1), axis=0)
    n_total_raw = len(event)
    stride = max(1, n_total_raw // max_points) if max_points > 0 else 1

    points_chunks, energy_chunks, line_cells = [], [], []
    offset = 0
    for ev, tr in keys:
        idx = np.nonzero((event == ev) & (track == tr))[0]
        if idx.size < 2:
            continue  # a single-point "path" can't be drawn as a line
        if idx.size > 2 and stride > 1:
            kept = idx[::stride]
            if kept[-1] != idx[-1]:
                kept = np.append(kept, idx[-1])  # keep the true endpoint
            idx = kept
        points_chunks.append(
            np.stack([arrays["x"][idx], arrays["y"][idx], arrays["z"][idx]], axis=1)
        )
        energy_chunks.append(arrays["energy"][idx])
        line_cells.append(np.concatenate([[idx.size], np.arange(offset, offset + idx.size)]))
        offset += idx.size

    if not points_chunks:
        return None
    poly = pv.PolyData(np.vstack(points_chunks), lines=np.concatenate(line_cells))
    poly["energy [eV]"] = np.concatenate(energy_chunks)
    return poly


def build_plotter(
    mesh_groups: dict[str, pv.PolyData],
    field_slice: pv.StructuredGrid,
    trajectories: pv.PolyData | None = None,
    streamlines: pv.PolyData | None = None,
) -> pv.Plotter:
    pl = pv.Plotter(off_screen=True)
    for name, mesh in mesh_groups.items():
        color, opacity = _style_for_group(name)
        pl.add_mesh(mesh, color=color, opacity=opacity, show_edges=False, label=name)
    pl.add_mesh(
        field_slice, scalars="log10(|E|) [V/cm]", cmap="turbo", opacity=0.6,
        show_scalar_bar=True,
    )
    if trajectories is not None:
        pl.add_mesh(
            trajectories, scalars="energy [eV]", cmap="plasma", line_width=3,
            render_lines_as_tubes=True, show_scalar_bar=True,
        )
    if streamlines is not None and streamlines.n_points > 0:
        pl.add_mesh(streamlines, color="cyan", line_width=2, render_lines_as_tubes=True)
    pl.add_axes()
    pl.camera_position = "xz"
    return pl


def _has_tree(root_path: str, tree_name: str) -> bool:
    if not os.path.exists(root_path):
        return False
    with uproot.open(root_path) as f:
        return tree_name in f


def main() -> None:
    base_name = sys.argv[1] if len(sys.argv) > 1 else "triple_gem_field"
    os.makedirs(HTML_DIR, exist_ok=True)
    default_out = os.path.join(HTML_DIR, f"{base_name}_overview.html")
    out_path = sys.argv[2] if len(sys.argv) > 2 else default_out

    surfaces_path = os.path.join(JSON_DIR, f"{base_name}_mesh_surfaces.json")
    slice_path = os.path.join(JSON_DIR, f"{base_name}_field_slice_full.json")
    vectors_path = os.path.join(JSON_DIR, f"{base_name}_field_vectors_full.json")
    trajectories_path = os.path.join(ROOT_DIR, f"{base_name}_avalanche.root")
    model_info_path = os.path.join(JSON_DIR, f"{base_name}_model_info.json")

    mesh_groups = load_geometry_meshes(surfaces_path)
    print(f"Loaded {len(mesh_groups)} geometry groups from {surfaces_path}")
    field_slice = load_field_slice(slice_path)
    print(f"Loaded field slice ({field_slice.n_points} points) from {slice_path}")

    trajectories = None
    if _has_tree(trajectories_path, "Trajectories"):
        trajectories = load_trajectories(trajectories_path)
        n_pts = trajectories.n_points if trajectories is not None else 0
        print(f"Loaded avalanche trajectories ({n_pts} points) from {trajectories_path}")
    else:
        print(f"No \"Trajectories\" tree at {trajectories_path} -- skipping "
              "(run export_avalanche_trajectories first to include one)")

    streamlines = None
    if os.path.exists(vectors_path) and os.path.exists(model_info_path):
        with open(model_info_path) as f:
            geo = json.load(f)["geometry"]
        vector_grid = load_field_vector_grid(vectors_path)
        # Seed just below the domain's top (the topmost GEM's hole opening
        # in the drift/transfer gas), on a small ring well inside the
        # nominal hole radius so every seed funnels into the same hole.
        z_seed = geo["z_domain_max_cm"] - 0.01 * (geo["z_domain_max_cm"] - geo["z_domain_min_cm"])
        seed_radius = geo["pitch_cm"] / 12.0
        streamlines = compute_streamlines(vector_grid, z_seed, seed_radius)
        print(f"Computed {streamlines.n_points} streamline points from {vectors_path} "
              f"(seeded at z={z_seed:.4f} cm, r={seed_radius:.5f} cm)")
    else:
        print(f"No field-vector grid/model info for {base_name} -- skipping streamlines")

    pl = build_plotter(mesh_groups, field_slice, trajectories, streamlines)
    pl.trame.export_html(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
