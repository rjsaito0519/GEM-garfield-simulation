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


def _um_to_cm(value_um: float) -> float:
    return value_um * 1.0e-4


# r/R in the reference paper's Table 1 are hole diameters (inner/outer),
# confirmed with the user 2026-09-22 -- halved here to get radii.
GEM_50UM = GemLayerParams(
    name="GEM_50um",
    pitch_cm=_um_to_cm(140.0),
    hole_inner_radius_cm=_um_to_cm(25.0 / 2.0),
    hole_outer_radius_cm=_um_to_cm(55.0 / 2.0),
    copper_thickness_cm=_um_to_cm(4.0),
    dielectric_thickness_cm=_um_to_cm(50.0),
)

GEM_100UM = GemLayerParams(
    name="GEM_100um",
    pitch_cm=_um_to_cm(140.0),
    hole_inner_radius_cm=_um_to_cm(35.0 / 2.0),
    hole_outer_radius_cm=_um_to_cm(65.0 / 2.0),
    copper_thickness_cm=_um_to_cm(9.0),
    dielectric_thickness_cm=_um_to_cm(100.0),
)
