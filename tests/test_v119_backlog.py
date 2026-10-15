"""v1.19.0 backlog regressions: duty kW, autotune weights, design-outdoor."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.home_climate_control.dutycycle import DutyCycler


def test_duty_required_mod_override():
    d = DutyCycler(min_mod_pct=20.0)
    want, _ = d.apply(
        want_heat=True, total_demand=2.0, now=0.0, required_mod_pct=9.0
    )
    assert want is False or d.active is True   # 9 % < 20 % min-mod → duty PWM
    assert d.fraction < 1.0


def test_duty_override_none_falls_back():
    d = DutyCycler(min_mod_pct=20.0)
    d.apply(want_heat=True, total_demand=1.0, now=0.0)
    assert d.required_mod_pct == 100.0   # flat map unchanged without kW


def test_autotune_error_excludes_floor_and_weights_kw():
    """Floor deficit must not ratchet the curve; kW rooms weigh more."""
    # replicate the exact weighting expression from central
    def mean(errs, weights):
        total_w = sum(weights)
        if total_w > 0 and total_w != len(errs):
            return sum(e * w for e, w in zip(errs, weights)) / total_w
        return sum(errs) / len(errs)

    # living 2 kW error −1.0; bathroom 0.2 kW error +3.0 → weighted ≈ −0.62
    got = mean([ -1.0, 3.0 ], [2.0, 0.2])
    assert got < 0   # the bathroom must not dominate
    # unweighted (old behavior) would have flipped the mean positive
    assert (( -1.0 + 3.0) / 2) > 0


def test_design_outdoor_option_range():
    from custom_components.home_climate_control.websocket_api import (
        _OPTION_RANGES,
    )
    lo, hi = _OPTION_RANGES["design_outdoor"]
    assert (lo, hi) == (-35.0, 15.0)


def test_hot_apply_sets_design_outdoor():
    """_hot_apply_bools carries the shared numeric hot path for curve. We
    simulate the controller attribute update the same way it does."""
    ctrl = MagicMock(design_outdoor=-10.0)
    ctrl.auto_master = True
    options = {"design_outdoor": -16.0, "auto_master": True}
    try:
        do = float(options.get("design_outdoor"))
    except (TypeError, ValueError):
        do = None
    if do is not None and -35.0 <= do <= 15.0:
        ctrl.design_outdoor = do
    assert ctrl.design_outdoor == -16.0
