"""Physical parameters of a single GEM foil layer.

Source: S.H. Kim et al., "Development of a time projection chamber for
J-PARC hadron physics program", J. Phys.: Conf. Ser. 1498 (2020) 012023,
Table 1 and Fig. 5/6 (HypTPC, used by J-PARC E42/E45/E72).

All lengths are in cm, matching the convention used throughout this
project's Gmsh/Elmer pipeline.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class GemLayerParams:
    """Geometry of one GEM foil: Cu - dielectric (biconical hole) - Cu."""

    name: str
    pitch_cm: float          # hexagonal hole pitch
    hole_inner_radius_cm: float  # narrowest radius of the hole, at the mid-plane of the dielectric
    hole_outer_radius_cm: float  # radius of the hole at the Cu/dielectric interfaces (== Cu hole radius here)
    copper_thickness_cm: float
    dielectric_thickness_cm: float
    # Relative permittivity of this layer's own dielectric insulator.
    # GEM_50UM and GEM_100UM below use physically *different* materials
    # (Table 1: Polyimide (PI) for the 50um GEM, Liquid Crystal Polymer
    # (LCP) for the 100um GEM -- see docs/debugging_notes.md, "2026-09-24:
    # GEM孔形状の文献確認"), but this project has no separately-sourced PI
    # vs. LCP permittivity value yet, so both are currently set to the same
    # textbook insulator value (3.5) -- a deliberate placeholder, not a
    # claim that PI and LCP have identical permittivity. This field exists
    # per layer (instead of one shared module-level constant) so a future
    # systematic study can set them independently per GEM type without a
    # structural change. Single-GEM meshes (single_gem_field_model.py) use
    # this value directly for their one dielectric body; the 3-GEM stack
    # (triple_gem_field_model.py) still merges all layers' dielectric
    # volumes into one shared Elmer material body, so it can only use one
    # shared value today (see that file's stack_dielectric_relative_permittivity
    # for the consistency check this implies) -- fully separating per-layer
    # values there would require splitting that physical group into one per
    # layer, a geometry change.
    dielectric_relative_permittivity: float


def _um_to_cm(value_um: float) -> float:
    return value_um * 1.0e-4


# r/R in the reference paper's Table 1 are hole diameters (inner/outer),
# not radii -- halved here to get the radii this dataclass stores.
GEM_50UM = GemLayerParams(
    name="GEM_50um",
    pitch_cm=_um_to_cm(140.0),
    hole_inner_radius_cm=_um_to_cm(25.0 / 2.0),
    hole_outer_radius_cm=_um_to_cm(55.0 / 2.0),
    copper_thickness_cm=_um_to_cm(4.0),
    dielectric_thickness_cm=_um_to_cm(50.0),
    dielectric_relative_permittivity=3.5,  # Polyimide (PI) -- see field doc above
)

GEM_100UM = GemLayerParams(
    name="GEM_100um",
    pitch_cm=_um_to_cm(140.0),
    hole_inner_radius_cm=_um_to_cm(35.0 / 2.0),
    hole_outer_radius_cm=_um_to_cm(65.0 / 2.0),
    copper_thickness_cm=_um_to_cm(9.0),
    dielectric_thickness_cm=_um_to_cm(100.0),
    dielectric_relative_permittivity=3.5,  # Liquid Crystal Polymer (LCP) -- see field doc above
)
