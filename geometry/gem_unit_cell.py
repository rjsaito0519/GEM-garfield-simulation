"""Build the 3D solid geometry of one or more GEM foil unit cells.

This uses Gmsh's OpenCASCADE (OCC) kernel and boolean operations (cut) to carve
biconical holes out of a Cu / dielectric / Cu sandwich, instead of building every
point and line by hand. This keeps the geometry definition short and lets the same
code build any GEM layer (different hole size, thickness, ...) just by changing
the input parameters.

Unit cell convention (matches the classic hexagonal-hole GEM layout):
    A rectangle of width = pitch and depth = pitch * sqrt(3) contains one full hole
    at its center plus four quarter-holes at its corners, which together tile into
    a regular hexagonal hole pattern when the rectangle is repeated periodically.

Tiling multiple cells (hole_centers_tiled) exists because a *single* cell has
no neighboring holes: an electron that diffuses sideways during a GEM
avalanche has nowhere to go but a solid wall, which makes essentially 100%
of secondary electrons hit the hole wall in a single-cell model instead of
passing through toward the next GEM. A few real neighboring holes give
those electrons somewhere physically realistic to end up.
"""

import math

import gmsh

from gem_params import GemLayerParams


def hole_centers(pitch_cm: float) -> list[tuple[float, float]]:
    """Positions of the 5 holes (4 corners + 1 center) of one unit cell."""
    half_x = pitch_cm / 2.0
    half_y = pitch_cm * math.sqrt(3.0) / 2.0
    return [
        (-half_x, -half_y),
        (half_x, -half_y),
        (half_x, half_y),
        (-half_x, half_y),
        (0.0, 0.0),
    ]


def hole_centers_tiled(pitch_cm: float, n_cells_x: int, n_cells_y: int) -> list[tuple[float, float]]:
    """Hole positions for an n_cells_x by n_cells_y tiling of the base unit
    cell, with the shared corner holes between adjacent cells deduplicated.

    n_cells_x/y must be odd, so the tiling is symmetric around the single
    center cell (the one anything else -- gas gaps, electron injection --
    is built/placed in).
    """
    if n_cells_x % 2 == 0 or n_cells_y % 2 == 0:
        raise ValueError("n_cells_x and n_cells_y must be odd (tiling is centered on one cell)")

    base = hole_centers(pitch_cm)
    step_x = pitch_cm
    step_y = pitch_cm * math.sqrt(3.0)

    unique_points: dict[tuple[int, int], tuple[float, float]] = {}
    tolerance_cm = 1.0e-9
    for i in range(-(n_cells_x // 2), n_cells_x // 2 + 1):
        for j in range(-(n_cells_y // 2), n_cells_y // 2 + 1):
            for x0, y0 in base:
                x, y = x0 + i * step_x, y0 + j * step_y
                key = (round(x / tolerance_cm), round(y / tolerance_cm))
                unique_points[key] = (x, y)
    return list(unique_points.values())


def _cone_or_cylinder(
    x0: float, y0: float, z0: float, height: float, r1: float, r2: float
) -> int:
    """gmsh.model.occ.addCone(), except when r1 == r2: OCC's addCone
    rejects a cone with two identical radii ("cone with two identic
    radii") since that's degenerate -- geometrically just a cylinder, so
    build one directly instead. This also makes inner_radius == outer_radius
    a valid input (a straight cylindrical hole), the r1 == r2 limit of the
    usual biconical taper -- useful for hole-taper sensitivity studies
    (see docs/debugging_notes.md)."""
    if abs(r1 - r2) < 1.0e-9:
        return gmsh.model.occ.addCylinder(x0, y0, z0, 0.0, 0.0, height, r1)
    return gmsh.model.occ.addCone(x0, y0, z0, 0.0, 0.0, height, r1, r2)


def _cut_holes_from_block(block_tag: int, cutter_tags: list[int]) -> int:
    """Cut a list of tool solids out of one block and return the resulting volume tag."""
    out_dim_tags, _ = gmsh.model.occ.cut(
        [(3, block_tag)], [(3, tag) for tag in cutter_tags]
    )
    return out_dim_tags[0][1]


def build_copper_layer(
    params: GemLayerParams,
    z_bottom_cm: float,
    hole_centers: list[tuple[float, float]],
    half_extent_x_cm: float | None = None,
    half_extent_y_cm: float | None = None,
) -> int:
    """Build one Cu foil (straight cylindrical holes) spanning [z_bottom, z_bottom + t_copper].

    half_extent_x/y_cm size the foil's own rectangular footprint; they
    default to one unit cell (pitch/2, pitch*sqrt(3)/2) but must be passed
    explicitly (matching hole_centers) when building a multi-cell tiling.
    """
    half_x = half_extent_x_cm if half_extent_x_cm is not None else params.pitch_cm / 2.0
    half_y = half_extent_y_cm if half_extent_y_cm is not None else params.pitch_cm * math.sqrt(3.0) / 2.0

    block = gmsh.model.occ.addBox(
        -half_x, -half_y, z_bottom_cm,
        2.0 * half_x, 2.0 * half_y, params.copper_thickness_cm,
    )
    hole_cutters = [
        gmsh.model.occ.addCylinder(
            x0, y0, z_bottom_cm, 0.0, 0.0, params.copper_thickness_cm,
            params.hole_outer_radius_cm,
        )
        for x0, y0 in hole_centers
    ]
    return _cut_holes_from_block(block, hole_cutters)


def build_dielectric_layer(
    params: GemLayerParams,
    z_center_cm: float,
    hole_centers: list[tuple[float, float]],
    half_extent_x_cm: float | None = None,
    half_extent_y_cm: float | None = None,
) -> int:
    """Build the dielectric foil with a biconical (hourglass) hole through its thickness.

    The hole radius shrinks linearly from hole_outer_radius (at the Cu interfaces, top
    and bottom) down to hole_inner_radius at the mid-plane, matching the standard
    double-etched GEM hole profile. See build_copper_layer for half_extent_x/y_cm.
    """
    half_x = half_extent_x_cm if half_extent_x_cm is not None else params.pitch_cm / 2.0
    half_y = half_extent_y_cm if half_extent_y_cm is not None else params.pitch_cm * math.sqrt(3.0) / 2.0
    half_t = params.dielectric_thickness_cm / 2.0
    z_bottom, z_top = z_center_cm - half_t, z_center_cm + half_t

    block = gmsh.model.occ.addBox(
        -half_x, -half_y, z_bottom,
        2.0 * half_x, 2.0 * half_y, params.dielectric_thickness_cm,
    )

    hole_cutters = []
    for x0, y0 in hole_centers:
        lower_cone = _cone_or_cylinder(
            x0, y0, z_bottom, half_t,
            params.hole_outer_radius_cm, params.hole_inner_radius_cm,
        )
        upper_cone = _cone_or_cylinder(
            x0, y0, z_center_cm, half_t,
            params.hole_inner_radius_cm, params.hole_outer_radius_cm,
        )
        hole_cutters += [lower_cone, upper_cone]

    return _cut_holes_from_block(block, hole_cutters)


def build_gem_layer(
    params: GemLayerParams,
    z_center_cm: float = 0.0,
    hole_centers_list: list[tuple[float, float]] | None = None,
    half_extent_x_cm: float | None = None,
    half_extent_y_cm: float | None = None,
) -> dict[str, int]:
    """Build one full GEM foil (Cu / dielectric / Cu) centered at z_center_cm.

    Defaults to a single unit cell (hole_centers(params.pitch_cm)); pass
    hole_centers_list=hole_centers_tiled(...) plus matching half_extent_x/y_cm
    to build a multi-cell tiling instead.

    Returns a dict mapping a material label to the resulting Gmsh volume tag,
    e.g. {"copper_top": 1, "dielectric": 2, "copper_bottom": 3}.

    NOTE: this builds the *solid* foil only. The hole cavities are left empty
    (no volume at all) -- callers that need the gas amplification region
    solved (i.e. anyone doing an actual field/avalanche calculation, as
    opposed to just checking the foil shape) must also call
    build_hole_gas_volumes() and include its result in the model, or the
    mesh will have a literal gap running through the hole with no material.
    """
    centers = hole_centers_list if hole_centers_list is not None else hole_centers(params.pitch_cm)
    half_t_diel = params.dielectric_thickness_cm / 2.0

    copper_top = build_copper_layer(
        params, z_bottom_cm=z_center_cm + half_t_diel, hole_centers=centers,
        half_extent_x_cm=half_extent_x_cm, half_extent_y_cm=half_extent_y_cm,
    )
    dielectric = build_dielectric_layer(
        params, z_center_cm=z_center_cm, hole_centers=centers,
        half_extent_x_cm=half_extent_x_cm, half_extent_y_cm=half_extent_y_cm,
    )
    copper_bottom = build_copper_layer(
        params,
        z_bottom_cm=z_center_cm - half_t_diel - params.copper_thickness_cm,
        hole_centers=centers,
        half_extent_x_cm=half_extent_x_cm, half_extent_y_cm=half_extent_y_cm,
    )

    gmsh.model.occ.synchronize()
    return {
        "copper_top": copper_top,
        "dielectric": dielectric,
        "copper_bottom": copper_bottom,
    }


def build_hole_gas_volumes(
    params: GemLayerParams,
    hole_centers: list[tuple[float, float]],
    z_center_cm: float = 0.0,
    half_extent_x_cm: float | None = None,
    half_extent_y_cm: float | None = None,
) -> list[int]:
    """Build one solid gas volume per hole, filling the cavity through the
    full foil thickness (both Cu layers + the dielectric's biconical neck).

    This is the same spindle shape used to *cut* the holes in
    build_copper_layer/build_dielectric_layer, built again here as an actual
    solid instead of a subtraction tool -- Gmsh consumes cutting tools, so
    the shape can't just be reused, only reconstructed. Without this, the
    hole is empty space with no material: Gmsh's mesher silently skips it
    ("Found void region" in its log) rather than erroring, so the gap is
    easy to miss -- but it means the single most important region for GEM
    gas amplification would be missing from the field solve entirely.

    See build_copper_layer for half_extent_x/y_cm (defaults to one cell).
    """
    half_t_diel = params.dielectric_thickness_cm / 2.0
    t_cu = params.copper_thickness_cm
    z_bottom_cu = z_center_cm - half_t_diel - t_cu
    z_top_cu = z_center_cm + half_t_diel
    half_x = half_extent_x_cm if half_extent_x_cm is not None else params.pitch_cm / 2.0
    half_y = half_extent_y_cm if half_extent_y_cm is not None else params.pitch_cm * math.sqrt(3.0) / 2.0
    foil_thickness = 2.0 * t_cu + params.dielectric_thickness_cm

    volumes = []
    for x0, y0 in hole_centers:
        bottom_cu = gmsh.model.occ.addCylinder(
            x0, y0, z_bottom_cu, 0.0, 0.0, t_cu, params.hole_outer_radius_cm
        )
        lower_cone = _cone_or_cylinder(
            x0, y0, z_center_cm - half_t_diel, half_t_diel,
            params.hole_outer_radius_cm, params.hole_inner_radius_cm,
        )
        upper_cone = _cone_or_cylinder(
            x0, y0, z_center_cm, half_t_diel,
            params.hole_inner_radius_cm, params.hole_outer_radius_cm,
        )
        top_cu = gmsh.model.occ.addCylinder(
            x0, y0, z_top_cu, 0.0, 0.0, t_cu, params.hole_outer_radius_cm
        )
        fused, _ = gmsh.model.occ.fuse(
            [(3, bottom_cu)], [(3, lower_cone), (3, upper_cone), (3, top_cu)]
        )
        # Holes at/near the tiled footprint's edge are only meant to be
        # partial holes there (see the module docstring): the cylinders/
        # cones above are built as full circles regardless of position,
        # same as the cutting tools in build_copper_layer/
        # build_dielectric_layer. There, cutting FROM a bounded block
        # automatically clips the unused part away; here, since this is an
        # added solid rather than a subtraction tool, it must be clipped
        # explicitly or an edge hole's gas would stick out past the tiled
        # footprint into space that belongs to the next (unbuilt) neighbor.
        clip_box = gmsh.model.occ.addBox(
            -half_x, -half_y, z_bottom_cu, 2.0 * half_x, 2.0 * half_y, foil_thickness,
        )
        clipped, _ = gmsh.model.occ.intersect(fused, [(3, clip_box)])
        volumes.append(clipped[0][1])
    return volumes
