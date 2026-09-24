"""Geometry + physical groups for a standalone single-GEM electrostatics test.

This wraps one GEM foil (from gem_unit_cell.py) with a drift-side gas gap above
and a transfer-side gas gap below, using the real HypTPC operating conditions
for GEM1's position in the stack (see SingleGemTestConfig below): this lets us
validate the field map for one GEM foil before building the full 3-layer stack.

Copper is modeled as a real 3D volume (not a special high-permittivity
material): every exposed copper surface gets the same fixed-potential
(Dirichlet) boundary condition, which is the standard, numerically well
behaved way to represent a conductor in an electrostatics FEM solve.
"""

import math
from dataclasses import dataclass

import gmsh

from gem_params import GemLayerParams
from gem_unit_cell import build_gem_layer, build_hole_gas_volumes, hole_centers_tiled

# Relative permittivity of the GEM's dielectric (polyimide), a standard
# textbook value also used by the reference repository (PER_INSULATOR).
DIELECTRIC_RELATIVE_PERMITTIVITY = 3.5

# Copper's permittivity value is irrelevant to the solution: every exposed
# copper surface gets a Dirichlet boundary condition (see module docstring),
# so nothing about the copper interior's material properties can affect the
# field solved outside it. Kept at 1 purely as a placeholder.
COPPER_RELATIVE_PERMITTIVITY = 1.0

# Surfaces further than this from the nominal z of a target plane are not
# considered part of that plane, when picking out the top/bottom boundary
# faces below. Must be well below the smallest gap/thickness in the model.
_Z_MATCH_TOLERANCE_CM = 1.0e-6


@dataclass(frozen=True)
class SingleGemTestConfig:
    """Electrical operating point for a standalone single-GEM test.

    Reproduces the real conditions at GEM1's position in the HypTPC stack
    (Kim et al. 2020): drift field above, transfer field (toward GEM2) below.
    """

    drift_gap_cm: float = 0.42       # gating wires -> GEM1, Fig. 5
    drift_field_v_per_cm: float = 130.0
    transfer_gap_cm: float = 0.20    # GEM1 -> GEM2, Fig. 5
    transfer_field_v_per_cm: float = 2000.0
    gem_voltage_v: float = 305.0     # potential difference across the GEM foil
    # A single hole has no neighboring hole for an electron that diffuses
    # sideways during a GEM avalanche to end up in, which makes the single
    # cell's own lateral (x/y) domain boundary a large, confounding loss
    # channel (found 2026-09-23 while re-evaluating the transfer-field scan
    # -- see docs/debugging_notes.md -- most "died in transfer gap" tracks
    # sat right at this single cell's edge). Tiling n_cells_x x n_cells_y
    # real neighboring holes around the one everything is centered on, same
    # as triple_gem_field_model.py's TripleGemTestConfig, gives diffusing
    # electrons somewhere physically realistic to go instead. Must both be
    # odd (tiling centered on one cell).
    n_cells_x: int = 3
    n_cells_y: int = 3


def _flat_boundary_surface(volume_tag: int, z_target_cm: float) -> int:
    """Find the single flat surface of a volume's boundary lying at z_target_cm.

    Used to pick out the outer drift-plane / transfer-plane faces of a gas
    box, as opposed to its side walls or its interface with the GEM foil.
    """
    boundary = gmsh.model.getBoundary([(3, volume_tag)], oriented=False)
    for dim, tag in boundary:
        _, _, z_min, _, _, z_max = gmsh.model.occ.getBoundingBox(dim, tag)
        if abs(z_min - z_target_cm) < _Z_MATCH_TOLERANCE_CM and abs(z_max - z_target_cm) < _Z_MATCH_TOLERANCE_CM:
            return tag
    raise RuntimeError(f"No flat boundary surface found at z={z_target_cm} for volume {volume_tag}")


def _add_gas_box(
    half_extent_x_cm: float, half_extent_y_cm: float, z_bottom_cm: float, height_cm: float
) -> int:
    return gmsh.model.occ.addBox(
        -half_extent_x_cm, -half_extent_y_cm, z_bottom_cm,
        2.0 * half_extent_x_cm, 2.0 * half_extent_y_cm, height_cm,
    )


def _fragment_into_conformal_volumes(volume_tags: list[int]) -> list[int]:
    """Boolean-fragment a list of mutually-touching volumes so they share
    conformal geometry (and therefore a conformal mesh) at their interfaces.

    Without this, each volume gets meshed independently and adjacent volumes
    end up with unrelated, non-matching nodes on their shared faces -- Elmer
    then sees several disconnected mesh pieces instead of one solvable domain
    (this is exactly what happened the first time: ElmerGrid reported "5
    separate pieces" and a "non-conforming" mesh). Fragmenting first fixes it.

    Returns the (possibly renumbered) tags in the same order as volume_tags;
    since none of our volumes overlap in their interior, each one maps to
    exactly one output volume.
    """
    dim_tags = [(3, tag) for tag in volume_tags]
    _, output_map = gmsh.model.occ.fragment(dim_tags, dim_tags)
    new_tags = []
    for original_tag, mapped in zip(volume_tags, output_map):
        if len(mapped) != 1:
            raise RuntimeError(
                f"Expected volume {original_tag} to map to exactly one volume "
                f"after fragment, got {mapped}"
            )
        new_tags.append(mapped[0][1])
    return new_tags


@dataclass(frozen=True)
class SingleGemFieldModel:
    """Everything the Elmer .sif writer needs: which physical group ID is
    which body/boundary, and what potential each electrode should be held at.
    """

    physical_group_ids: dict[str, int]     # name -> Gmsh physical group tag
    electrode_potentials_v: dict[str, float]  # electrode name -> potential [V]
    # Single source of truth for values (hole pitch, solved-domain extent)
    # that C++ macros need but must not re-hardcode -- see model_info.hh.
    geometry_info: dict[str, float]


def build_single_gem_field_model(
    gem_params: GemLayerParams, test_config: SingleGemTestConfig
) -> SingleGemFieldModel:
    """Build the full single-GEM electrostatics geometry in the current Gmsh model."""
    half_t_diel = gem_params.dielectric_thickness_cm / 2.0
    z_gem_top = half_t_diel + gem_params.copper_thickness_cm  # top of copper_top
    z_gem_bottom = -half_t_diel - gem_params.copper_thickness_cm  # bottom of copper_bottom
    z_drift_plane = z_gem_top + test_config.drift_gap_cm
    z_transfer_plane = z_gem_bottom - test_config.transfer_gap_cm

    centers = hole_centers_tiled(gem_params.pitch_cm, test_config.n_cells_x, test_config.n_cells_y)
    half_extent_x_cm = test_config.n_cells_x * gem_params.pitch_cm / 2.0
    half_extent_y_cm = test_config.n_cells_y * gem_params.pitch_cm * math.sqrt(3.0) / 2.0
    gem_volumes = build_gem_layer(
        gem_params, z_center_cm=0.0, hole_centers_list=centers,
        half_extent_x_cm=half_extent_x_cm, half_extent_y_cm=half_extent_y_cm,
    )
    drift_gas = _add_gas_box(half_extent_x_cm, half_extent_y_cm, z_gem_top, test_config.drift_gap_cm)
    transfer_gas = _add_gas_box(
        half_extent_x_cm, half_extent_y_cm, z_transfer_plane, test_config.transfer_gap_cm
    )
    # Fills the hole cavities (see build_hole_gas_volumes' docstring): without
    # this, the hole -- the actual gas-amplification region -- is a literal
    # gap in the mesh, with no material solved there at all.
    hole_gas = build_hole_gas_volumes(
        gem_params, centers, z_center_cm=0.0,
        half_extent_x_cm=half_extent_x_cm, half_extent_y_cm=half_extent_y_cm,
    )

    volume_names = (
        ["copper_top", "dielectric", "copper_bottom", "drift_gas", "transfer_gas"]
        + [f"hole_gas_{i}" for i in range(len(hole_gas))]
    )
    volume_tags_before = [
        gem_volumes["copper_top"], gem_volumes["dielectric"], gem_volumes["copper_bottom"],
        drift_gas, transfer_gas,
    ] + hole_gas
    volume_tags_after = _fragment_into_conformal_volumes(volume_tags_before)
    volumes = dict(zip(volume_names, volume_tags_after))
    gem_volumes = {
        "copper_top": volumes["copper_top"],
        "dielectric": volumes["dielectric"],
        "copper_bottom": volumes["copper_bottom"],
    }
    drift_gas, transfer_gas = volumes["drift_gas"], volumes["transfer_gas"]
    hole_gas = [volumes[f"hole_gas_{i}"] for i in range(len(hole_gas))]
    gmsh.model.occ.synchronize()

    # Electrical reference: bottom copper (facing the pad plane / anode side)
    # is ground. Potential increases going "downstream" toward the pad plane
    # and decreases going "upstream" toward the cathode/drift side, matching
    # a standard TPC bias scheme (cathode at large negative HV, pads near 0V).
    v_bottom_copper = 0.0
    v_top_copper = v_bottom_copper - test_config.gem_voltage_v
    v_drift_plane = v_top_copper - test_config.drift_field_v_per_cm * test_config.drift_gap_cm
    v_transfer_plane = v_bottom_copper + test_config.transfer_field_v_per_cm * test_config.transfer_gap_cm

    top_copper_boundary = gmsh.model.getBoundary([(3, gem_volumes["copper_top"])], oriented=False)
    bottom_copper_boundary = gmsh.model.getBoundary([(3, gem_volumes["copper_bottom"])], oriented=False)
    dielectric_boundary = gmsh.model.getBoundary([(3, gem_volumes["dielectric"])], oriented=False)
    drift_plane_surface = _flat_boundary_surface(drift_gas, z_drift_plane)
    transfer_plane_surface = _flat_boundary_surface(transfer_gas, z_transfer_plane)

    physical_group_ids = {
        "Gas": gmsh.model.addPhysicalGroup(3, [drift_gas, transfer_gas] + hole_gas, name="Gas"),
        "Dielectric": gmsh.model.addPhysicalGroup(3, [gem_volumes["dielectric"]], name="Dielectric"),
        "Copper": gmsh.model.addPhysicalGroup(
            3, [gem_volumes["copper_top"], gem_volumes["copper_bottom"]], name="Copper"
        ),
        "TopCopperElectrode": gmsh.model.addPhysicalGroup(
            2, [tag for _, tag in top_copper_boundary], name="TopCopperElectrode"
        ),
        "BottomCopperElectrode": gmsh.model.addPhysicalGroup(
            2, [tag for _, tag in bottom_copper_boundary], name="BottomCopperElectrode"
        ),
        # Not used as an Elmer boundary condition (it's an internal interface,
        # left with the natural/default BC) -- only kept so the 3D geometry
        # viewer (geometry/export_mesh_surfaces.py) can render the dielectric's
        # hourglass hole surface on its own, separately from the copper.
        "DielectricSurface": gmsh.model.addPhysicalGroup(
            2, [tag for _, tag in dielectric_boundary], name="DielectricSurface"
        ),
        "DriftPlaneElectrode": gmsh.model.addPhysicalGroup(
            2, [drift_plane_surface], name="DriftPlaneElectrode"
        ),
        "TransferPlaneElectrode": gmsh.model.addPhysicalGroup(
            2, [transfer_plane_surface], name="TransferPlaneElectrode"
        ),
    }
    electrode_potentials_v = {
        "TopCopperElectrode": v_top_copper,
        "BottomCopperElectrode": v_bottom_copper,
        "DriftPlaneElectrode": v_drift_plane,
        "TransferPlaneElectrode": v_transfer_plane,
    }
    # Beyond what C++/model_info.hh actually consume (pitch/half-extent/
    # z-domain, unchanged above), also record the full simulation condition
    # so analysis scripts can read it back rather than reconstructing a
    # fresh SingleGemTestConfig() (see GitHub issue #4/#6, 2026-09-24).
    geometry_info = {
        "pitch_cm": gem_params.pitch_cm,
        "half_extent_x_cm": half_extent_x_cm,
        "half_extent_y_cm": half_extent_y_cm,
        "z_domain_min_cm": z_transfer_plane,
        "z_domain_max_cm": z_drift_plane,
        "n_cells_x": test_config.n_cells_x,
        "n_cells_y": test_config.n_cells_y,
        "z_gem_top_cm": z_gem_top,
        "z_gem_bottom_cm": z_gem_bottom,
        "copper_thickness_cm": gem_params.copper_thickness_cm,
        "dielectric_thickness_cm": gem_params.dielectric_thickness_cm,
        "hole_inner_radius_cm": gem_params.hole_inner_radius_cm,
        "hole_outer_radius_cm": gem_params.hole_outer_radius_cm,
        "gem_voltage_v": test_config.gem_voltage_v,
        "drift_gap_cm": test_config.drift_gap_cm,
        "drift_field_v_per_cm": test_config.drift_field_v_per_cm,
        "transfer_gap_cm": test_config.transfer_gap_cm,
        "transfer_field_v_per_cm": test_config.transfer_field_v_per_cm,
    }
    return SingleGemFieldModel(physical_group_ids, electrode_potentials_v, geometry_info)
