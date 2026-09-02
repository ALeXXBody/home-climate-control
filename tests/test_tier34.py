"""Tier 3/4 tests: solar gain, CO₂ guard, radiator metering, balancing."""

import pytest
from unittest.mock import MagicMock

from custom_components.home_climate_control.balancing import BalanceMonitor
from custom_components.home_climate_control.co2 import Co2Guard
from custom_components.home_climate_control.radiators import radiator_output_kw
from custom_components.home_climate_control.solar import SolarGain

class _Coord:
    """Minimal coordinator stub: only what ZoneClimateEntity touches."""
    curve_coeff = 1.2
    setbacks = None

    def register_zone(self, z):
        pass

    def rename_zone_learning(self, old, new):
        pass




# ── Tier 3: solar gain ────────────────────────────────────────────────────
def test_solar_gain_hysteresis():
    s = SolarGain()
    # dim indoor light — never activates
    for _ in range(10):
        s.update(300)
    assert not s.active
    # direct sun → EMA climbs above 5000
    for _ in range(30):
        s.update(7000)
    assert s.active
    # passing cloud — EMA drops but stays above LOW → still active
    for _ in range(3):
        s.update(3000)
    assert s.active
    # sustained shade → clears
    for _ in range(60):
        s.update(500)
    assert not s.active


def test_solar_offset_applies_to_zone_comfort_only():
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    zone_cfg = {
        "name": "Living",
        "setpoint": 21.0,
        "lux_sensor": "sensor.living_lux",
    }
    z = ZoneClimateEntity.__new__(ZoneClimateEntity)  # skip HA __init__
    ZoneClimateEntity.__init__(z, MagicMock(), _Coord(), MagicMock(), zone_cfg)
    z.hass = None  # handlers skip async_write_ha_state when hass is None
    z._current_temp = 20.0
    assert z.effective_setpoint() == pytest.approx(21.0)
    # sustained direct sun → comfort target shaved 0.5 °C
    for _ in range(30):
        z.on_lux_update(7000)
    assert z.solar.active
    assert z.effective_setpoint() == pytest.approx(20.5)
    # away preset: absolute default (16 °C); solar trim still applies
    z._preset = "away"
    z._target_temp = 16.0
    assert z.effective_setpoint() == pytest.approx(15.5)  # 16 default − 0.5 solar


# ── Tier 3: CO₂ guard ─────────────────────────────────────────────────────
def test_co2_hysteresis_and_bounds():
    g = Co2Guard()
    g.update(900)
    assert not g.needs_ventilation
    g.update(1150)
    assert g.needs_ventilation
    g.update(900)  # above LOW → stays flagged
    assert g.needs_ventilation
    g.update(750)
    assert not g.needs_ventilation
    # implausible readings ignored
    g.update(50000)
    g.update(-5)
    assert g.ppm is not None and g.ppm <= 10000


# ── Tier 4: radiator metering ─────────────────────────────────────────────
def test_radiator_output_formula():
    # 2 kW @ ΔT50, water avg 50, room 20 → ΔT=30 → 2×(0.6)^1.3 ≈ 1.02
    assert radiator_output_kw(2.0, 60, 40, 20) == pytest.approx(1.02, abs=0.02)
    # at rating point → nominal
    assert radiator_output_kw(1.5, 80, 60, 20) == pytest.approx(1.5, abs=0.01)
    # water colder than room → 0
    assert radiator_output_kw(2.0, 25, 22, 25) == 0.0
    assert radiator_output_kw(None, 60, 40, 20) is None
    assert radiator_output_kw(2.0, None, 40, 20) is None


# ── Tier 4: balancing ─────────────────────────────────────────────────────
def test_balancing_classification():
    b = BalanceMonitor()
    assert b.report()["state"] == "learning"
    for _ in range(15):
        b.sample(95, True)
    assert b.report()["state"] == "undersupplied"

    b2 = BalanceMonitor()
    for _ in range(15):
        b2.sample(8, False)
    assert b2.report()["state"] == "oversupplied"

    b3 = BalanceMonitor()
    for _ in range(15):
        b3.sample(50, True)
    assert b3.report()["state"] == "ok"


def test_zone_valve_feeds_balance():
    from custom_components.home_climate_control.zone import ZoneClimateEntity

    z = ZoneClimateEntity.__new__(ZoneClimateEntity)
    ZoneClimateEntity.__init__(z, MagicMock(), _Coord(), MagicMock(), {"name": "R"})
    z.hass = None  # handlers skip async_write_ha_state when hass is None
    z._current_temp = 18.0
    for _ in range(20):
        z.on_valve_update(96.0)
    assert z._valve_pct == 96.0
    assert z.balance.report()["state"] == "undersupplied"
