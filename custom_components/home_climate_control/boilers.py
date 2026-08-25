"""Boiler manufacturer/model catalog for Home Climate Control.

The OpenTherm bus only carries an 8-bit *slave MemberID* (ID 3, low byte)
which encodes the MANUFACTURER — no model string ever crosses the wire.
The model is therefore chosen manually from a dropdown; the manufacturer is
auto-detected from the member ID when the boiler announces itself.

Member-ID table sources:
  - SAT project "Boiler compatibility list" (github.com/Alexwijn/SAT
    discussion #21) and its comment thread
  - Laxilef/OTGateway issue reports (Viessmann = 33 confirmed)
  - community compatibility lists

Images: the panel looks up `www/boilers/<make>_<model>.<ext>` first, then
`www/boilers/<make>.<ext>`, then falls back to `generic.svg`.  Every model
in BOILER_CATALOG has a dedicated product photo; brand SVGs are used as
fallback for makes without a manual model selection.
"""

from __future__ import annotations

# MemberID -> manufacturer display name (SAT-verified codes)
MEMBER_ID_TO_MAKE: dict[int, str] = {
    4: "Geminox",
    6: "Ideal",
    9: "Ferroli",
    11: "Remeha / De Dietrich",
    24: "Vaillant",
    27: "Immergas / Sime / Baxi",
    29: "Itho Daalderop",
    33: "Viessmann",
    41: "Radiant",
    131: "Nefit",
    173: "Intergas",
}

# Manufacturer -> known OpenTherm-capable models (dropdown options).
BOILER_CATALOG: dict[str, list[str]] = {
    "Baxi": ["Luna Dua-Tec", "Luna Comfort HT 1.280", "ECO4s"],
    "Ferroli": ["BlueHelix Pro", "BlueHelix Tech RRT"],
    "Geminox": ["THC"],
    "Ideal": [
        "Logic ESP1",
        "Logic Combi ESP1 35",
        "Logic Heat",
        "Vogue Max",
    ],
    "Immergas": ["Victrix Omnia", "Victrix Omnia 25", "Victrix Superior"],
    "Intergas": ["HRE", "Xtreme", "ECO RF", "Xclusive", "Rapid"],
    "Itho Daalderop": ["Base Cube"],
    "Nefit": ["Pro-Line HRC"],
    "Radiant": ["R2K"],
    "Remeha": ["Avanta CW5", "Calenta", "Elga Ace"],
    "Sime": ["Vera HE"],
    "Vaillant": ["VHR Solide Plus"],
    "Viessmann": [
        "Vitodens 100-W B1KF",
        "Vitodens 100-W",
        "Vitodens 200-W",
    ],
}

# Aliases seen on the bus that share a member ID
_MEMBER_ALIASES = {
    11: "Remeha / De Dietrich",
}


def make_for_member(member_id: int | None) -> str | None:
    """Manufacturer display name for a slave MemberID, or None."""
    if member_id is None or member_id == 0:
        return None
    return MEMBER_ID_TO_MAKE.get(int(member_id))


def models_for_make(make: str | None) -> list[str]:
    if not make:
        return []
    return BOILER_CATALOG.get(make, [])


def catalog_payload() -> dict:
    """Payload served to the panel dropdowns."""
    return {
        "makes": sorted(BOILER_CATALOG.keys()),
        "models": BOILER_CATALOG,
        "member_map": {str(k): v for k, v in MEMBER_ID_TO_MAKE.items()},
    }
