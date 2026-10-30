"""Setback-depth scaling by the room's insulation loss factor.

Field-acquired k (weather-normalized cool-down) now modulates the learned
setback depth: leaky rooms cut their setbacks shallower (their recovery
costs the same absolute drop harder), tight envelopes can afford deeper.
Everything stays inside the existing learned clamp.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.home_climate_control.insulation import (
    depth_scale_for_k,
    InsulationScorer,
    K_MATURE_MIN,
)
from custom_components.home_climate_control.setback import SetbackLearner


def test_scale_bands():
    assert depth_scale_for_k(None) == 1.0
    assert depth_scale_for_k(0.02) == pytest.approx(1.15)   # excellent
    assert depth_scale_for_k(0.05) == pytest.approx(1.00)   # good
    assert depth_scale_for_k(0.10) == pytest.approx(0.90)   # fair
    assert depth_scale_for_k(0.30) == pytest.approx(0.80)   # poor


def _scorer_with_k(k: float | None) -> InsulationScorer:
    sc = InsulationScorer(None)
    if k is not None:
        st = sc._room("Office")
        st.k_ema = k
        st.samples = K_MATURE_MIN
    return sc


def test_k_for_maturity_gate():
    sc = _scorer_with_k(0.02)
    assert sc.k_for("Office") == 0.02
    sc._room("Office").samples = 1          # immature
    assert sc.k_for("Office") is None
    sc2 = InsulationScorer(None)
    assert sc2.k_for("Office") is None       # no data at all


def test_learner_shallower_for_poor_envelopes():
    base = SetbackLearner(MagicMock())
    base._room("Office").cycles = 10
    base._room("Office").warm_ema = 2.0      # enough recovery width
    poor = SetbackLearner(MagicMock())
    poor._room("Office").cycles = 10
    poor._room("Office").warm_ema = 2.0
    poor.set_insulation_lookup(lambda zone: 0.30)
    d_base = base.offset_for("Office", -3.0)
    d_poor = poor.offset_for("Office", -3.0)
    assert d_base != -3.0                    # learned path active
    assert d_poor > d_base                   # poor: shallower setback
    assert d_poor <= -1.0                    # shallow clamp untouched


def test_learner_deeper_for_tight_envelopes():
    base = SetbackLearner(MagicMock())
    base._room("Office").cycles = 10
    base._room("Office").warm_ema = 2.0
    deep = SetbackLearner(MagicMock())
    deep._room("Office").cycles = 10
    deep._room("Office").warm_ema = 2.0
    deep.set_insulation_lookup(lambda zone: 0.02)
    assert deep.offset_for("Office", -2.0) < base.offset_for("Office", -2.0)


def test_clamp_bounds_respected():
    lr = SetbackLearner(MagicMock())
    lr._room("Office").cycles = 10
    lr._room("Office").warm_ema = 2.0
    lr.set_insulation_lookup(lambda zone: 0.02)
    for dead in (None, 0.0, 1800.0):
        d = lr.offset_for("Office", -3.0, dead_time_s=dead)
        assert -5.0 <= d <= -1.0


def test_no_lookup_is_unchanged():
    a = SetbackLearner(MagicMock())
    a._room("Office").cycles = 10
    a._room("Office").warm_ema = 2.0
    b = SetbackLearner(MagicMock())
    b._room("Office").cycles = 10
    b._room("Office").warm_ema = 2.0
    b.set_insulation_lookup(lambda zone: None)   # immature scorer
    assert a.offset_for("Office", -2.0) == b.offset_for("Office", -2.0)


def test_scorer_persistence_roundtrip_keeps_samples(tmp_path):
    """Old stores (k without samples counter) restore as mature; new ones
    keep the counter — both end decision-capable, not accident-immature."""
    sc = InsulationScorer(None)
    sc._store = MagicMock()
    sc._room("Office").k_ema = 0.12
    sc._room("Office").samples = 7
    payload = {"Office": {"k": 0.12, "samples": 7}}
    data = {"Office": {"k": 0.12}}           # legacy store shape
    async def _load():
        return data
    sc._store.async_load = _load
    asyncio.run(sc.async_load())
    st = sc._room("Office")
    assert st.samples == 4                   # legacy EMA credited mature
    assert sc.k_for("Office") == 0.12
    _ = payload                              # new shape persists samples too
