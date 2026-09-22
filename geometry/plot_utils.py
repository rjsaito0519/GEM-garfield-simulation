"""Matplotlib-based sanity-check plots for the GEM geometry and mesh.

We use matplotlib instead of Gmsh's own screenshot feature (gmsh.write("*.png"))
because that feature needs a real graphical context (FLTK/OpenGL window), which is
not available on this headless cluster. Matplotlib's Agg backend renders PNGs
without any display, which is what these plots rely on.
"""

import matplotlib

matplotlib.use("Agg")  # noqa: E402  (must be set before importing pyplot)

import matplotlib.pyplot as plt
import numpy as np

from gem_params import GemLayerParams


def plot_parameter_schematic(params: GemLayerParams, output_path: str) -> None:
    """Draw the intended hole cross-section (side view) purely from the input
    parameters, before any meshing happens. This is a quick check that the
    numbers going into the geometry builder match the source paper's Fig. 6.
    """
    half_t_diel = params.dielectric_thickness_cm / 2.0
    r_in, r_out = params.hole_inner_radius_cm, params.hole_outer_radius_cm
    t_cu = params.copper_thickness_cm

    fig, ax = plt.subplots(figsize=(5, 5))

    # Copper layers: rectangles with a straight-walled hole of radius r_out.
    for z_bottom in (half_t_diel, -half_t_diel - t_cu):
        ax.add_patch(
            plt.Rectangle((-r_out - 0.001, z_bottom), 0.001, t_cu, color="#b87333")
        )
        ax.add_patch(
            plt.Rectangle((r_out, z_bottom), 0.001, t_cu, color="#b87333")
        )

    # Dielectric: hourglass-shaped hole outline, drawn as two trapezoid edges.
    diel_x = [r_out, r_in, r_out]
    diel_z = [half_t_diel, 0.0, -half_t_diel]
    ax.plot(diel_x, diel_z, color="#2e8b57", linewidth=2, label="dielectric hole edge")
    ax.plot([-x for x in diel_x], diel_z, color="#2e8b57", linewidth=2)
    ax.axhline(half_t_diel, color="#2e8b57", linestyle="--", linewidth=0.5)
    ax.axhline(-half_t_diel, color="#2e8b57", linestyle="--", linewidth=0.5)

    ax.annotate(
        f"r_inner = {r_in * 1e4:.1f} um", xy=(r_in, 0), xytext=(r_in + 0.0005, 0.0002),
        arrowprops=dict(arrowstyle="->"),
    )
    ax.annotate(
        f"r_outer = {r_out * 1e4:.1f} um", xy=(r_out, half_t_diel),
        xytext=(r_out + 0.0005, half_t_diel + 0.0005),
        arrowprops=dict(arrowstyle="->"),
    )

    ax.set_xlim(-params.pitch_cm / 2, params.pitch_cm / 2)
    ax.set_ylim(-half_t_diel - t_cu - 0.0005, half_t_diel + t_cu + 0.0005)
    ax.set_xlabel("x [cm]")
    ax.set_ylabel("z [cm]")
    ax.set_title(f"{params.name}: intended hole cross-section (x-z, y=0)")
    ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_mesh_cross_section(
    node_coords_cm: np.ndarray,
    output_path: str,
    y_tolerance_cm: float,
    z_range_cm: tuple[float, float] | None = None,
    equal_aspect: bool = True,
) -> None:
    """Scatter-plot mesh nodes near the y=0 plane, in the x-z view.

    This is compared by eye against plot_parameter_schematic's output: if the
    meshed hole shape does not match the intended hourglass profile, something
    is wrong in gem_unit_cell.py before we even get to Elmer/Garfield++.

    z_range_cm optionally restricts the plotted z window (e.g. zoom in on the
    GEM foil itself, ignoring the much larger gas gaps above/below it).
    equal_aspect should be turned off when the plotted region is much taller
    than it is wide (e.g. the full drift+GEM+transfer stack), since a 1:1
    aspect ratio there would squash the plot into an unreadable sliver.
    """
    x, y, z = node_coords_cm[:, 0], node_coords_cm[:, 1], node_coords_cm[:, 2]
    mask = np.abs(y) < y_tolerance_cm
    if z_range_cm is not None:
        mask &= (z >= z_range_cm[0]) & (z <= z_range_cm[1])

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(x[mask], z[mask], s=1, color="black")
    ax.set_xlabel("x [cm]")
    ax.set_ylabel("z [cm]")
    ax.set_title(f"Mesh nodes with |y| < {y_tolerance_cm * 1e4:.1f} um")
    if equal_aspect:
        ax.set_aspect("equal")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)


def plot_mesh_overview_3d(node_coords_cm: np.ndarray, output_path: str) -> None:
    """3D scatter of all mesh nodes, for a quick overall-shape sanity check."""
    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(projection="3d")
    ax.scatter(
        node_coords_cm[:, 0], node_coords_cm[:, 1], node_coords_cm[:, 2],
        s=0.5, alpha=0.3, color="black",
    )
    ax.set_xlabel("x [cm]")
    ax.set_ylabel("y [cm]")
    ax.set_zlabel("z [cm]")
    ax.set_title("Mesh node overview")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
