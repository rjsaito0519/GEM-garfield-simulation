"""Quick 3D checks of the single-GEM geometry/field using matplotlib only --
no browser needed. Reuses the JSON data already written by
build_single_gem_field_mesh.py (geometry/output/) and
export_field_samples (macros/output/), so run those first.

Usage:
    python3 plot_3d_matplotlib.py geometry [--show]
    python3 plot_3d_matplotlib.py vectors [--zoom] [--show]
    python3 plot_3d_matplotlib.py slice [--zoom] [--show]

Without --show, each command saves a PNG under geometry/output/ and exits --
safe to run over SSH with no display. With --show, it opens an interactive
matplotlib window instead (needs a working display, e.g. X11 forwarding, or
run the same functions directly in a Jupyter cell for inline interactivity).
"""

import argparse
import json
import os

import matplotlib

matplotlib.use("Agg")  # overridden to an interactive backend below if --show
import matplotlib.pyplot as plt
import numpy as np
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

GEOMETRY_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
MACROS_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "macros", "output")
CM_TO_UM = 1.0e4

GROUP_COLORS = {
    "TopCopperElectrode": "#a85a2a",
    "BottomCopperElectrode": "#a85a2a",
    "DielectricSurface": "#17827a",
    "DriftPlaneElectrode": "#999999",
    "TransferPlaneElectrode": "#999999",
}
GROUP_ALPHA = {
    "DriftPlaneElectrode": 0.12,
    "TransferPlaneElectrode": 0.12,
}


def _finish(fig, output_path: str, show: bool) -> None:
    if show:
        plt.show()
    else:
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
        print(f"Wrote {output_path}")


def plot_geometry_3d(show: bool = False) -> None:
    """Render the GEM foil as real triangulated surfaces (Cu + dielectric)."""
    with open(os.path.join(GEOMETRY_OUTPUT_DIR, "single_gem_field_mesh_surfaces.json")) as f:
        mesh = json.load(f)
    vertices = np.array(mesh["vertices"]) * CM_TO_UM

    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(projection="3d")
    for name, faces in mesh["groups"].items():
        if not faces:
            continue
        triangles = vertices[np.array(faces)]  # (n_faces, 3, 3)
        poly = Poly3DCollection(
            triangles,
            facecolor=GROUP_COLORS.get(name, "#3a6ea5"),
            alpha=GROUP_ALPHA.get(name, 0.95),
            edgecolor="none",
        )
        ax.add_collection3d(poly)

    # Crop x/y to just around the central hole: the dielectric surface spans
    # the whole unit cell (+-70 um), so a wide view is dominated by that one
    # flat sheet and the copper (a thin ring right at the hole edge) is easy
    # to miss. NOTE: matplotlib does not depth-sort separate Poly3DCollections
    # perfectly, so copper can still occasionally render behind the
    # dielectric depending on view_init -- rotate with --show if it looks
    # like only one color is visible.
    zoom_xy = 40.0
    ax.set_xlim(-zoom_xy, zoom_xy)
    ax.set_ylim(-zoom_xy, zoom_xy)
    # Without this, the z-axis auto-scales to include the (very transparent,
    # alpha=0.12) drift/transfer context planes far above/below the foil,
    # which squashes the actual 9-um-thick foil into an indistinguishably
    # thin band.
    ax.set_zlim(-15, 15)
    ax.view_init(elev=22, azim=-60)
    ax.set_xlabel("x [um]")
    ax.set_ylabel("y [um]")
    ax.set_zlabel("z [um]")
    ax.set_title("GEM foil: Cu (copper) + dielectric hole surfaces")
    fig.tight_layout()
    _finish(fig, os.path.join(GEOMETRY_OUTPUT_DIR, "mpl_geometry_3d.png"), show)


def plot_vectors_3d(zoom: bool = False, show: bool = False) -> None:
    """3D quiver plot of the E field: arrow direction + log-magnitude color."""
    name = "field_vectors_zoom.json" if zoom else "field_vectors_full.json"
    with open(os.path.join(MACROS_OUTPUT_DIR, name)) as f:
        data = json.load(f)
    # status != -6 excludes points outside the meshed domain; the magnitude
    # check separately excludes points *inside* solid copper, where E is
    # genuinely ~0 (copper is equipotential) and a unit direction vector is
    # undefined.
    samples = [
        s for s in data["samples"]
        if s["status"] != -6 and (s["ex"] ** 2 + s["ey"] ** 2 + s["ez"] ** 2) > 0
    ]

    x = np.array([s["x"] for s in samples]) * CM_TO_UM
    y = np.array([s["y"] for s in samples]) * CM_TO_UM
    z = np.array([s["z"] for s in samples]) * CM_TO_UM
    e = np.array([[s["ex"], s["ey"], s["ez"]] for s in samples])
    magnitude = np.linalg.norm(e, axis=1)
    direction = e / magnitude[:, None]
    log_mag = np.log10(magnitude)

    cmap = plt.get_cmap("turbo")
    norm = plt.Normalize(vmin=log_mag.min(), vmax=log_mag.max())
    colors = cmap(norm(log_mag))

    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(projection="3d")
    length = 8.0 if zoom else 14.0
    ax.quiver(x, y, z, direction[:, 0], direction[:, 1], direction[:, 2],
              length=length, color=colors, normalize=True)
    ax.set_xlabel("x [um]")
    ax.set_ylabel("y [um]")
    ax.set_zlabel("z [um]")
    ax.set_title(f"E field direction (color = log10|E| [V/cm]), {'zoom' if zoom else 'full'}")
    fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=0.6, label="log10|E|")
    fig.tight_layout()
    suffix = "zoom" if zoom else "full"
    _finish(fig, os.path.join(GEOMETRY_OUTPUT_DIR, f"mpl_vectors_3d_{suffix}.png"), show)


def plot_slice_3d(zoom: bool = False, show: bool = False) -> None:
    """The y=0 potential slice as a flat colored surface positioned in 3D."""
    name = "field_slice_zoom.json" if zoom else "field_slice_full.json"
    with open(os.path.join(MACROS_OUTPUT_DIR, name)) as f:
        data = json.load(f)
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

    cmap = plt.get_cmap("RdBu_r")
    finite = V[np.isfinite(V)]
    norm = plt.Normalize(vmin=finite.min(), vmax=finite.max())
    facecolors = cmap(norm(np.nan_to_num(V, nan=finite.mean())))

    fig = plt.figure(figsize=(7, 7))
    ax = fig.add_subplot(projection="3d")
    ax.plot_surface(X, Y, Z, facecolors=facecolors, rstride=1, cstride=1,
                     linewidth=0, antialiased=False, shade=False)
    ax.set_xlabel("x [um]")
    ax.set_ylabel("y [um]")
    ax.set_zlabel("z [um]")
    ax.set_title(f"Potential on the y=0 slice [V], {'zoom' if zoom else 'full'}")
    fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), ax=ax, shrink=0.6, label="V [Volt]")
    fig.tight_layout()
    suffix = "zoom" if zoom else "full"
    _finish(fig, os.path.join(GEOMETRY_OUTPUT_DIR, f"mpl_slice_3d_{suffix}.png"), show)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("view", choices=["geometry", "vectors", "slice"])
    parser.add_argument("--zoom", action="store_true", help="use the near-hole dataset")
    parser.add_argument("--show", action="store_true", help="open an interactive window instead of saving a PNG")
    args = parser.parse_args()

    if args.show:
        matplotlib.use("TkAgg")  # needs a display (e.g. X11 forwarding)

    if args.view == "geometry":
        plot_geometry_3d(show=args.show)
    elif args.view == "vectors":
        plot_vectors_3d(zoom=args.zoom, show=args.show)
    elif args.view == "slice":
        plot_slice_3d(zoom=args.zoom, show=args.show)


if __name__ == "__main__":
    main()
