"""Build the 3D solid geometry of one GEM foil as a periodic hexagonal unit cell.

This uses Gmsh's OpenCASCADE (OCC) kernel and boolean operations (cut) to carve
biconical holes out of a Cu / dielectric / Cu sandwich, instead of building every
point and line by hand. This keeps the geometry definition short and lets the same
code build any GEM layer (different hole size, thickness, ...) just by changing
the input parameters.

Unit cell convention (matches the classic hexagonal-hole GEM layout):
    A rectangle of width = pitch and depth = pitch * sqrt(3) contains one full hole
    at its center plus four quarter-holes at its corners, which together tile into
    a regular hexagonal hole pattern when the rectangle is repeated periodically.
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


def _cut_holes_from_block(block_tag: int, cutter_tags: list[int]) -> int:
    """Cut a list of tool solids out of one block and return the resulting volume tag."""
    out_dim_tags, _ = gmsh.model.occ.cut(
        [(3, block_tag)], [(3, tag) for tag in cutter_tags]
    )
    return out_dim_tags[0][1]


def build_copper_layer(
    params: GemLayerParams, z_bottom_cm: float, hole_centers: list[tuple[float, float]]
) -> int:
    """Build one Cu foil (straight cylindrical holes) spanning [z_bottom, z_bottom + t_copper]."""
    half_x = params.pitch_cm / 2.0
    half_y = params.pitch_cm * math.sqrt(3.0) / 2.0

    block = gmsh.model.occ.addBox(
        -half_x, -half_y, z_bottom_cm,
        params.pitch_cm, params.pitch_cm * math.sqrt(3.0), params.copper_thickness_cm,
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
    params: GemLayerParams, z_center_cm: float, hole_centers: list[tuple[float, float]]
) -> int:
    """Build the dielectric foil with a biconical (hourglass) hole through its thickness.

    The hole radius shrinks linearly from hole_outer_radius (at the Cu interfaces, top
    and bottom) down to hole_inner_radius at the mid-plane, matching the standard
    double-etched GEM hole profile.
    """
    half_x = params.pitch_cm / 2.0
    half_y = params.pitch_cm * math.sqrt(3.0) / 2.0
    half_t = params.dielectric_thickness_cm / 2.0
    z_bottom, z_top = z_center_cm - half_t, z_center_cm + half_t

    block = gmsh.model.occ.addBox(
        -half_x, -half_y, z_bottom,
        params.pitch_cm, params.pitch_cm * math.sqrt(3.0), params.dielectric_thickness_cm,
    )

    hole_cutters = []
    for x0, y0 in hole_centers:
        lower_cone = gmsh.model.occ.addCone(
            x0, y0, z_bottom, 0.0, 0.0, half_t,
            params.hole_outer_radius_cm, params.hole_inner_radius_cm,
        )
        upper_cone = gmsh.model.occ.addCone(
            x0, y0, z_center_cm, 0.0, 0.0, half_t,
            params.hole_inner_radius_cm, params.hole_outer_radius_cm,
        )
        hole_cutters += [lower_cone, upper_cone]

    return _cut_holes_from_block(block, hole_cutters)


def build_gem_layer(params: GemLayerParams, z_center_cm: float = 0.0) -> dict[str, int]:
    """Build one full GEM foil (Cu / dielectric / Cu) centered at z_center_cm.

    Returns a dict mapping a material label to the resulting Gmsh volume tag,
    e.g. {"copper_top": 1, "dielectric": 2, "copper_bottom": 3}.

    NOTE: this builds the *solid* foil only. The hole cavities are left empty
    (no volume at all) -- callers that need the gas amplification region
    solved (i.e. anyone doing an actual field/avalanche calculation, as
    opposed to just checking the foil shape) must also call
    build_hole_gas_volumes() and include its result in the model, or the
    mesh will have a literal gap running through the hole with no material.
    """
    centers = hole_centers(params.pitch_cm)
    half_t_diel = params.dielectric_thickness_cm / 2.0

    copper_top = build_copper_layer(
        params, z_bottom_cm=z_center_cm + half_t_diel, hole_centers=centers
    )
    dielectric = build_dielectric_layer(
        params, z_center_cm=z_center_cm, hole_centers=centers
    )
    copper_bottom = build_copper_layer(
        params,
        z_bottom_cm=z_center_cm - half_t_diel - params.copper_thickness_cm,
        hole_centers=centers,
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
    """
    half_t_diel = params.dielectric_thickness_cm / 2.0
    t_cu = params.copper_thickness_cm
    z_bottom_cu = z_center_cm - half_t_diel - t_cu
    z_top_cu = z_center_cm + half_t_diel
    half_x = params.pitch_cm / 2.0
    half_y = params.pitch_cm * math.sqrt(3.0) / 2.0
    foil_thickness = 2.0 * t_cu + params.dielectric_thickness_cm

    volumes = []
    for x0, y0 in hole_centers:
        bottom_cu = gmsh.model.occ.addCylinder(
            x0, y0, z_bottom_cu, 0.0, 0.0, t_cu, params.hole_outer_radius_cm
        )
        lower_cone = gmsh.model.occ.addCone(
            x0, y0, z_center_cm - half_t_diel, 0.0, 0.0, half_t_diel,
            params.hole_outer_radius_cm, params.hole_inner_radius_cm,
        )
        upper_cone = gmsh.model.occ.addCone(
            x0, y0, z_center_cm, 0.0, 0.0, half_t_diel,
            params.hole_inner_radius_cm, params.hole_outer_radius_cm,
        )
        top_cu = gmsh.model.occ.addCylinder(
            x0, y0, z_top_cu, 0.0, 0.0, t_cu, params.hole_outer_radius_cm
        )
        fused, _ = gmsh.model.occ.fuse(
            [(3, bottom_cu)], [(3, lower_cone), (3, upper_cone), (3, top_cu)]
        )
        # The 4 corner holes are only ever meant to be *quarter* holes (see
        # the module docstring): the cylinders/cones above are built as full
        # circles regardless of position, same as the cutting tools in
        # build_copper_layer/build_dielectric_layer. There, cutting FROM a
        # bounded block automatically clips the unused part away; here, since
        # this is an added solid rather than a subtraction tool, it must be
        # clipped explicitly or a corner hole's gas would stick out past the
        # unit cell into space that belongs to the neighboring cell.
        clip_box = gmsh.model.occ.addBox(
            -half_x, -half_y, z_bottom_cu, params.pitch_cm,
            params.pitch_cm * math.sqrt(3.0), foil_thickness,
        )
        clipped, _ = gmsh.model.occ.intersect(fused, [(3, clip_box)])
        volumes.append(clipped[0][1])
    return volumes
