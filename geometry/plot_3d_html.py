"""Write standalone, self-contained HTML files with interactive (mouse-
rotatable, zoomable) 3D plots of the single-GEM geometry/field, using
plotly. Unlike the matplotlib PNGs from plot_3d_matplotlib.py, these need no
X11 forwarding on this end at all -- just copy the .html file to your own
laptop (e.g. `scp`) and open it in any browser. plotly.js is embedded
directly in the file (~a few MB each), so it also works fully offline.

Usage:
    python3 plot_3d_html.py
Outputs (see docs/reference.md "出力ディレクトリ構成" for the full results/ layout):
    results/html/gem_geometry_3d.html
    results/html/gem_field_vectors_3d.html   (has a dropdown to switch full/zoom)
    results/html/gem_field_slice_3d.html     (has a dropdown to switch full/zoom)
"""

import json
import os

import numpy as np
import plotly.graph_objects as go

# results/ is this project's single consolidated output tree -- see
# docs/reference.md "出力ディレクトリ構成" for what belongs in each subdir.
_RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "results")
JSON_DIR = os.path.join(_RESULTS_DIR, "json")
HTML_DIR = os.path.join(_RESULTS_DIR, "html")
CM_TO_UM = 1.0e4

GROUP_COLORS = {
    "TopCopperElectrode": "#a85a2a",
    "BottomCopperElectrode": "#a85a2a",
    "DielectricSurface": "#17827a",
    "DriftPlaneElectrode": "#999999",
    "TransferPlaneElectrode": "#999999",
}
GROUP_OPACITY = {
    "DriftPlaneElectrode": 0.12,
    "TransferPlaneElectrode": 0.12,
}


def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def write_geometry_html(output_path: str) -> None:
    mesh = _load_json(os.path.join(JSON_DIR, "single_gem_field_mesh_surfaces.json"))
    vertices = np.array(mesh["vertices"]) * CM_TO_UM

    traces = []
    for name, faces in mesh["groups"].items():
        if not faces:
            continue
        faces = np.array(faces)
        traces.append(go.Mesh3d(
            x=vertices[:, 0], y=vertices[:, 1], z=vertices[:, 2],
            i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
            color=GROUP_COLORS.get(name, "#3a6ea5"),
            opacity=GROUP_OPACITY.get(name, 1.0),
            flatshading=True,
            name=name,
        ))

    fig = go.Figure(data=traces)
    fig.update_layout(
        title="GEM foil geometry (Cu + dielectric)",
        scene=dict(aspectmode="cube",
                   xaxis_title="x [um]", yaxis_title="y [um]", zaxis_title="z [um]"),
    )
    fig.write_html(output_path)
    print(f"Wrote {output_path}")


def _vector_trace(samples: list, sizeref: float) -> go.Cone:
    """Plotly's Cone trace has no separate "color by this scalar" input --
    it always colors by norm(u, v, w). To show direction with a *uniform*
    visual scale while still coloring by the (hugely varying, ~130 to
    ~90000 V/cm) field magnitude, u/v/w are set to the unit direction
    scaled by log10(magnitude): the norm Plotly computes for coloring then
    equals log10|E| exactly, and cone length varies (mildly, since log
    compresses the range) with it too, which reads fine visually.
    """
    filtered = [
        s for s in samples
        if s["status"] != -6 and (s["ex"] ** 2 + s["ey"] ** 2 + s["ez"] ** 2) > 0
    ]
    x = [s["x"] * CM_TO_UM for s in filtered]
    y = [s["y"] * CM_TO_UM for s in filtered]
    z = [s["z"] * CM_TO_UM for s in filtered]
    mags = [np.sqrt(s["ex"] ** 2 + s["ey"] ** 2 + s["ez"] ** 2) for s in filtered]
    log_mags = [np.log10(m) for m in mags]
    u = [s["ex"] / m * lm for s, m, lm in zip(filtered, mags, log_mags)]
    v = [s["ey"] / m * lm for s, m, lm in zip(filtered, mags, log_mags)]
    w = [s["ez"] / m * lm for s, m, lm in zip(filtered, mags, log_mags)]
    return go.Cone(
        x=x, y=y, z=z, u=u, v=v, w=w,
        anchor="tail", sizemode="scaled", sizeref=sizeref,
        colorscale="Turbo",
        colorbar=dict(title="log10|E|"),
    )


def write_vectors_html(output_path: str) -> None:
    full = _load_json(os.path.join(JSON_DIR, "field_vectors_full.json"))
    zoom = _load_json(os.path.join(JSON_DIR, "field_vectors_zoom.json"))

    # sizeref is tuned by eye for this grid spacing; if arrows look too
    # big/small after opening the file, adjust these numbers and rerun.
    trace_full = _vector_trace(full["samples"], sizeref=5)
    trace_zoom = _vector_trace(zoom["samples"], sizeref=2)
    trace_zoom.visible = False

    fig = go.Figure(data=[trace_full, trace_zoom])
    fig.update_layout(
        title="E field direction (color = log10|E| [V/cm])",
        scene=dict(aspectmode="cube",
                   xaxis_title="x [um]", yaxis_title="y [um]", zaxis_title="z [um]"),
        updatemenus=[dict(
            type="buttons", direction="right", x=0.5, y=1.08, xanchor="center",
            buttons=[
                dict(label="Full range", method="update", args=[{"visible": [True, False]}]),
                dict(label="Hole zoom", method="update", args=[{"visible": [False, True]}]),
            ],
        )],
    )
    fig.write_html(output_path)
    print(f"Wrote {output_path}")


def _slice_trace(data: dict, visible: bool) -> go.Surface:
    nx, nz = data["nx"], data["nz"]
    samples = data["samples"]
    X = np.zeros((nx, nz))
    Y = np.zeros((nx, nz))
    Z = np.zeros((nx, nz))
    V = np.full((nx, nz), np.nan)
    for ix in range(nx):
        for iz in range(nz):
            s = samples[ix * nz + iz]
            X[ix, iz] = s["x"] * CM_TO_UM
            Y[ix, iz] = s["y"] * CM_TO_UM
            Z[ix, iz] = s["z"] * CM_TO_UM
            if s["status"] != -6:
                V[ix, iz] = s["v"]
    return go.Surface(
        x=X, y=Y, z=Z, surfacecolor=V,
        colorscale="RdBu", reversescale=True,
        colorbar=dict(title="V [Volt]"),
        visible=visible,
    )


def write_slice_html(output_path: str) -> None:
    full = _load_json(os.path.join(JSON_DIR, "field_slice_full.json"))
    zoom = _load_json(os.path.join(JSON_DIR, "field_slice_zoom.json"))

    trace_full = _slice_trace(full, visible=True)
    trace_zoom = _slice_trace(zoom, visible=False)

    fig = go.Figure(data=[trace_full, trace_zoom])
    fig.update_layout(
        title="Potential on the y=0 slice",
        scene=dict(aspectmode="cube",
                   xaxis_title="x [um]", yaxis_title="y [um]", zaxis_title="z [um]"),
        updatemenus=[dict(
            type="buttons", direction="right", x=0.5, y=1.08, xanchor="center",
            buttons=[
                dict(label="Full range", method="update", args=[{"visible": [True, False]}]),
                dict(label="Hole zoom", method="update", args=[{"visible": [False, True]}]),
            ],
        )],
    )
    fig.write_html(output_path)
    print(f"Wrote {output_path}")


def main() -> None:
    os.makedirs(HTML_DIR, exist_ok=True)
    write_geometry_html(os.path.join(HTML_DIR, "gem_geometry_3d.html"))
    write_vectors_html(os.path.join(HTML_DIR, "gem_field_vectors_3d.html"))
    write_slice_html(os.path.join(HTML_DIR, "gem_field_slice_3d.html"))


if __name__ == "__main__":
    main()
