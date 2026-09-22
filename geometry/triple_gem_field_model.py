"""Geometry + physical groups for the full 3-GEM stack:
drift -> GEM1 -> transfer1 -> GEM2 -> transfer2 -> GEM3 -> induction -> pad plane.

Stacking order and voltages confirmed with the user 2026-09-22: **100 -> 50
-> 50 um from the drift side**, which differs from Kim et al. 2020's
published order (50 -> 50 -> 100 um from the drift side, see
single_gem_field_model.py). Per-GEM-type numbers -- hole geometry (from that
paper's Table 1) and the rule that the 100 um GEM gets 1.5x the 50 um GEM's
voltage -- are unchanged, just reassigned to the new stacking order.

The drift gap is kept at the same modest 4.2 mm placeholder used in the
single-GEM model, not HypTPC's real ~55 cm drift length: modeling the full
drift volume adds nothing to the near-GEM field/avalanche physics this
project cares about and would make the mesh far larger for no benefit (the
user's own call, 2026-09-22, "いったんはほどほどでいいのかも").

Copper is modeled the same way as in the single-GEM case: a real 3D volume
with a direct Dirichlet boundary condition on its full surface, not a
special high-permittivity material.
"""

import math
from dataclasses import dataclass

import gmsh

from gem_params import GEM_50UM, GEM_100UM, GemLayerParams
from gem_unit_cell import build_gem_layer, build_hole_gas_volumes, hole_centers_tiled

DIELECTRIC_RELATIVE_PERMITTIVITY = 3.5
COPPER_RELATIVE_PERMITTIVITY = 1.0
_Z_MATCH_TOLERANCE_CM = 1.0e-6


@dataclass(frozen=True)
class GemStackLayer:
    name: str
    params: GemLayerParams
    voltage_v: float  # potential drop from this GEM's top to its bottom


@dataclass(frozen=True)
class TripleGemTestConfig:
    drift_gap_cm: float = 0.42
    drift_field_v_per_cm: float = 130.0
    transfer_gap_cm: float = 0.20
    transfer_field_v_per_cm: float = 2000.0
    induction_gap_cm: float = 0.20
    induction_field_v_per_cm: float = 3100.0
    # Ordered drift-side (top) to pad-side (bottom).
    layers: tuple = (
        GemStackLayer("GEM1", GEM_100UM, 1.5 * 305.0),
        GemStackLayer("GEM2", GEM_50UM, 305.0),
        GemStackLayer("GEM3", GEM_50UM, 305.0),
    )
    # A single hole per layer has no neighboring hole for an electron that
    # diffuses sideways during a GEM avalanche to end up in -- found
    # 2026-09-22 that this makes essentially all secondary electrons hit the
    # hole wall instead of reaching the next GEM (see the project memory
    # notes). Tiling n_cells_x x n_cells_y real neighboring holes around the
    # one everything (gas gaps, electron injection) is centered on gives
    # them somewhere physically realistic to go. Must both be odd.
    n_cells_x: int = 3
    n_cells_y: int = 3


def _add_gas_box(
    half_extent_x_cm: float, half_extent_y_cm: float, z_bottom_cm: float, height_cm: float
) -> int:
    return gmsh.model.occ.addBox(
        -half_extent_x_cm, -half_extent_y_cm, z_bottom_cm,
        2.0 * half_extent_x_cm, 2.0 * half_extent_y_cm, height_cm,
    )


def _flat_boundary_surface(volume_tag: int, z_target_cm: float) -> int:
    """Same as single_gem_field_model.py's helper of the same name."""
    boundary = gmsh.model.getBoundary([(3, volume_tag)], oriented=False)
    for dim, tag in boundary:
        _, _, z_min, _, _, z_max = gmsh.model.occ.getBoundingBox(dim, tag)
        if abs(z_min - z_target_cm) < _Z_MATCH_TOLERANCE_CM and abs(z_max - z_target_cm) < _Z_MATCH_TOLERANCE_CM:
            return tag
    raise RuntimeError(f"No flat boundary surface found at z={z_target_cm} for volume {volume_tag}")


def _fragment_into_conformal_volumes(volume_tags: list[int]) -> list[int]:
    """Same as single_gem_field_model.py's helper of the same name."""
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


def _half_extent_cm(layer: GemStackLayer) -> float:
    """Distance from a GEM foil's z-center to the outer face of either
    copper layer (i.e. half the foil's total Cu+dielectric+Cu thickness)."""
    return layer.params.dielectric_thickness_cm / 2.0 + layer.params.copper_thickness_cm


def _layer_z_centers(config: TripleGemTestConfig) -> list[float]:
    """z-center of each GEM foil, built from the pad-plane side (last layer
    centered near z=0) upward, so each consecutive pair is separated by
    exactly one transfer gap."""
    n = len(config.layers)
    z_centers = [0.0] * n
    for i in range(n - 2, -1, -1):
        z_centers[i] = (
            z_centers[i + 1]
            + _half_extent_cm(config.layers[i + 1])
            + config.transfer_gap_cm
            + _half_extent_cm(config.layers[i])
        )
    return z_centers


def _electrode_potentials_v(config: TripleGemTestConfig) -> dict[str, float]:
    """Electrical reference: the induction plane (pad-plane side) is ground.
    Potential increases going downstream (toward the pad plane) and
    decreases going upstream (toward the cathode/drift side) -- the same
    convention as single_gem_field_model.py, extended across the whole
    stack instead of just one GEM foil.
    """
    n = len(config.layers)
    potentials: dict[str, float] = {"InductionPlaneElectrode": 0.0}
    v_bottom = potentials["InductionPlaneElectrode"] - config.induction_field_v_per_cm * config.induction_gap_cm
    for i in range(n - 1, -1, -1):
        layer = config.layers[i]
        v_top = v_bottom - layer.voltage_v
        potentials[f"{layer.name}_BottomCopperElectrode"] = v_bottom
        potentials[f"{layer.name}_TopCopperElectrode"] = v_top
        if i > 0:
            v_bottom = v_top - config.transfer_field_v_per_cm * config.transfer_gap_cm
    top_layer_name = config.layers[0].name
    potentials["DriftPlaneElectrode"] = (
        potentials[f"{top_layer_name}_TopCopperElectrode"]
        - config.drift_field_v_per_cm * config.drift_gap_cm
    )
    return potentials


@dataclass(frozen=True)
class TripleGemFieldModel:
    physical_group_ids: dict[str, int]
    electrode_potentials_v: dict[str, float]
    # Single source of truth for values (hole pitch, solved-domain extent)
    # that C++ macros need but must not re-hardcode -- see macros/model_info.hh.
    geometry_info: dict[str, float]


def build_triple_gem_field_model(config: TripleGemTestConfig) -> TripleGemFieldModel:
    """Build the full 3-GEM stack geometry in the current Gmsh model."""
    pitch_cm = config.layers[0].params.pitch_cm
    for layer in config.layers:
        if layer.params.pitch_cm != pitch_cm:
            raise ValueError("all GEM layers must share the same hex pitch")
    centers_xy = hole_centers_tiled(pitch_cm, config.n_cells_x, config.n_cells_y)
    half_extent_x_cm = config.n_cells_x * pitch_cm / 2.0
    half_extent_y_cm = config.n_cells_y * pitch_cm * math.sqrt(3.0) / 2.0
    z_centers = _layer_z_centers(config)

    volume_names: list[str] = []
    volume_tags: list[int] = []
    for layer, z_center in zip(config.layers, z_centers):
        vols = build_gem_layer(
            layer.params, z_center_cm=z_center, hole_centers_list=centers_xy,
            half_extent_x_cm=half_extent_x_cm, half_extent_y_cm=half_extent_y_cm,
        )
        volume_names += [f"{layer.name}_copper_top", f"{layer.name}_dielectric", f"{layer.name}_copper_bottom"]
        volume_tags += [vols["copper_top"], vols["dielectric"], vols["copper_bottom"]]

        hole_gas = build_hole_gas_volumes(
            layer.params, centers_xy, z_center_cm=z_center,
            half_extent_x_cm=half_extent_x_cm, half_extent_y_cm=half_extent_y_cm,
        )
        for i, tag in enumerate(hole_gas):
            volume_names.append(f"{layer.name}_hole_gas_{i}")
            volume_tags.append(tag)

    z_top_of_stack = z_centers[0] + _half_extent_cm(config.layers[0])
    z_bottom_of_stack = z_centers[-1] - _half_extent_cm(config.layers[-1])
    z_drift_plane = z_top_of_stack + config.drift_gap_cm
    z_induction_plane = z_bottom_of_stack - config.induction_gap_cm

    volume_names.append("drift_gas")
    volume_tags.append(_add_gas_box(half_extent_x_cm, half_extent_y_cm, z_top_of_stack, config.drift_gap_cm))
    for i in range(len(config.layers) - 1):
        z_bottom_of_transfer_gap = z_centers[i + 1] + _half_extent_cm(config.layers[i + 1])
        volume_names.append(f"transfer_gas_{i}")
        volume_tags.append(
            _add_gas_box(half_extent_x_cm, half_extent_y_cm, z_bottom_of_transfer_gap, config.transfer_gap_cm)
        )
    volume_names.append("induction_gas")
    volume_tags.append(
        _add_gas_box(half_extent_x_cm, half_extent_y_cm, z_induction_plane, config.induction_gap_cm)
    )

    new_tags = _fragment_into_conformal_volumes(volume_tags)
    volumes = dict(zip(volume_names, new_tags))
    gmsh.model.occ.synchronize()

    physical_group_ids: dict[str, int] = {}

    gas_volume_tags = [volumes["drift_gas"], volumes["induction_gas"]]
    gas_volume_tags += [volumes[f"transfer_gas_{i}"] for i in range(len(config.layers) - 1)]
    dielectric_volume_tags = []
    copper_volume_tags = []
    for layer in config.layers:
        dielectric_volume_tags.append(volumes[f"{layer.name}_dielectric"])
        copper_volume_tags += [volumes[f"{layer.name}_copper_top"], volumes[f"{layer.name}_copper_bottom"]]
        gas_volume_tags += [volumes[k] for k in volumes if k.startswith(f"{layer.name}_hole_gas_")]

    physical_group_ids["Gas"] = gmsh.model.addPhysicalGroup(3, gas_volume_tags, name="Gas")
    physical_group_ids["Dielectric"] = gmsh.model.addPhysicalGroup(3, dielectric_volume_tags, name="Dielectric")
    physical_group_ids["Copper"] = gmsh.model.addPhysicalGroup(3, copper_volume_tags, name="Copper")

    for layer in config.layers:
        top_boundary = gmsh.model.getBoundary([(3, volumes[f"{layer.name}_copper_top"])], oriented=False)
        bottom_boundary = gmsh.model.getBoundary([(3, volumes[f"{layer.name}_copper_bottom"])], oriented=False)
        dielectric_boundary = gmsh.model.getBoundary([(3, volumes[f"{layer.name}_dielectric"])], oriented=False)
        physical_group_ids[f"{layer.name}_TopCopperElectrode"] = gmsh.model.addPhysicalGroup(
            2, [tag for _, tag in top_boundary], name=f"{layer.name}_TopCopperElectrode"
        )
        physical_group_ids[f"{layer.name}_BottomCopperElectrode"] = gmsh.model.addPhysicalGroup(
            2, [tag for _, tag in bottom_boundary], name=f"{layer.name}_BottomCopperElectrode"
        )
        # Internal interface, no Elmer BC -- kept only for the 3D viewer, as
        # in single_gem_field_model.py.
        physical_group_ids[f"{layer.name}_DielectricSurface"] = gmsh.model.addPhysicalGroup(
            2, [tag for _, tag in dielectric_boundary], name=f"{layer.name}_DielectricSurface"
        )

    drift_plane_surface = _flat_boundary_surface(volumes["drift_gas"], z_drift_plane)
    induction_plane_surface = _flat_boundary_surface(volumes["induction_gas"], z_induction_plane)
    physical_group_ids["DriftPlaneElectrode"] = gmsh.model.addPhysicalGroup(
        2, [drift_plane_surface], name="DriftPlaneElectrode"
    )
    physical_group_ids["InductionPlaneElectrode"] = gmsh.model.addPhysicalGroup(
        2, [induction_plane_surface], name="InductionPlaneElectrode"
    )

    electrode_potentials_v = _electrode_potentials_v(config)
    geometry_info = {
        "pitch_cm": pitch_cm,
        "half_extent_x_cm": half_extent_x_cm,
        "half_extent_y_cm": half_extent_y_cm,
        "z_domain_min_cm": z_induction_plane,
        "z_domain_max_cm": z_drift_plane,
    }
    return TripleGemFieldModel(physical_group_ids, electrode_potentials_v, geometry_info)
