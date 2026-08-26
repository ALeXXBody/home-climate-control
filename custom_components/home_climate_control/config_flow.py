"""Config flow for Home Climate Control."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    BACKEND_DEMO,
    BACKEND_HCS,
    CONF_BACKEND,
    CONF_NODE_ID,
    CONF_OUTDOOR_SENSOR,
    CONF_ZONE_NAME,
    CONF_ZONE_TEMP_SENSOR,
    CONF_ZONE_TRV_CLIMATES,
    CONF_ZONE_FLOOR,
    CONF_ZONE_HEAT_CONTROL,
    HEAT_CONTROL_SMART,
    HEAT_CONTROL_MANUAL,
    CONF_ZONE_WINDOW_SENSORS,
    CONF_ZONES,
    CURVE_COEFF_MAX,
    CURVE_COEFF_MIN,
    DEFAULT_BOILER_MIN_MODULATION,
    DEFAULT_CURVE_COEFF,
    DEFAULT_MAX_FLOW_TEMP,
    DEFAULT_MIN_FLOW_TEMP,
    DEMO_DEFAULT_OUTDOOR,
    DEMO_DEFAULT_ROOMS,
    DEMO_UNIQUE_ID,
    DOMAIN,
    MAX_FLOW_TEMP_LIMIT,
    MIN_FLOW_TEMP_LIMIT,
    NAME,
)

CONF_MIN_FLOW = "min_flow_temp"
CONF_MAX_FLOW = "max_flow_temp"
CONF_CURVE = "curve_coeff"
CONF_AUTOTUNE = "autotune_curve"
CONF_LEARN_SETBACKS = "learn_setbacks"
CONF_GAS_POWER_KW = "rated_heat_input_kw"
CONF_GAS_MIN_KW = "min_heat_input_kw"
CONF_GAS_NOMOD = "nomod_duty_factor"
CONF_GAS_CALIB = "gas_calibration"
CONF_GAS_PRICE = "gas_price_per_kwh"
CONF_MIN_MOD = "boiler_min_modulation"
CONF_DUTY_EN = "duty_cycle_enabled"


class HomeClimateControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Climate Control."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._zones: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose backend: Home Climate System device or demo."""
        if user_input is not None:
            backend = user_input[CONF_BACKEND]
            self._data[CONF_BACKEND] = backend
            if backend == BACKEND_DEMO:
                return await self.async_step_demo()
            return await self.async_step_hcs()

        schema = vol.Schema(
            {
                vol.Required(CONF_BACKEND, default=BACKEND_HCS): vol.In(
                    {
                        BACKEND_HCS: "Home Climate System device (ESP32/ESP8266)",
                        BACKEND_DEMO: "Demo (no hardware — for testing)",
                    }
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_demo(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """One-click demo system with simulated boiler and rooms."""
        await self.async_set_unique_id(DEMO_UNIQUE_ID)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            zones = []
            for name, start_temp, setpoint in DEMO_DEFAULT_ROOMS:
                zones.append(
                    {
                        CONF_ZONE_NAME: name,
                        CONF_ZONE_TEMP_SENSOR: None,
                        CONF_ZONE_WINDOW_SENSORS: [],
                        CONF_ZONE_TRV_CLIMATES: [],
                        "setpoint": setpoint,
                        "demo_start_temp": start_temp,
                    }
                )
            title = user_input.get(CONF_NAME, f"{NAME} (Demo)")
            return self.async_create_entry(
                title=title,
                data={
                    CONF_BACKEND: BACKEND_DEMO,
                    CONF_NAME: title,
                    "demo_outdoor": DEMO_DEFAULT_OUTDOOR,
                },
                options={
                    CONF_MIN_FLOW: user_input.get(CONF_MIN_FLOW, DEFAULT_MIN_FLOW_TEMP),
                    CONF_MAX_FLOW: user_input.get(CONF_MAX_FLOW, DEFAULT_MAX_FLOW_TEMP),
                    CONF_CURVE: user_input.get(CONF_CURVE, DEFAULT_CURVE_COEFF),
                    CONF_ZONES: zones,
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=f"{NAME} (Demo)"): str,
                vol.Required(CONF_MIN_FLOW, default=DEFAULT_MIN_FLOW_TEMP): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=MIN_FLOW_TEMP_LIMIT, max=MAX_FLOW_TEMP_LIMIT),
                ),
                vol.Required(CONF_MAX_FLOW, default=DEFAULT_MAX_FLOW_TEMP): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=MIN_FLOW_TEMP_LIMIT, max=MAX_FLOW_TEMP_LIMIT),
                ),
                vol.Required(CONF_CURVE, default=DEFAULT_CURVE_COEFF): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=CURVE_COEFF_MIN, max=CURVE_COEFF_MAX),
                ),
            }
        )
        return self.async_show_form(step_id="demo", data_schema=schema)

    async def async_step_discovery(self, discovery_info):
        """A new HCS board announced itself on MQTT — offer setup."""
        info = discovery_info or {}
        node = info.get("node_id") or self.context.get("node_id") or ""
        self._data[CONF_NODE_ID] = node
        self._data[CONF_BACKEND] = BACKEND_HCS
        self.context["title_placeholders"] = {"node": node}
        if node:
            await self.async_set_unique_id(f"hcs_{node}")
            self._abort_if_unique_id_configured()
        return await self.async_step_hcs()

    async def async_step_hcs(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Native Home Climate System device — discovered automatically."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data.update(user_input)
            self._data[CONF_BACKEND] = BACKEND_HCS
            node = (user_input.get(CONF_NODE_ID) or "").strip()
            if not node:
                errors["base"] = "node_required"
            else:
                await self.async_set_unique_id(f"hcs_{node}")
                self._abort_if_unique_id_configured()
                return await self.async_step_zone()
        suggested_node = self._data.get(CONF_NODE_ID) or ""
        node_field = (
            vol.Required(CONF_NODE_ID, default=suggested_node)
            if suggested_node
            else vol.Required(
                CONF_NODE_ID,
                description={"suggested_value": ""},
            )
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=NAME): str,
                node_field: str,
                vol.Required(CONF_MIN_FLOW, default=DEFAULT_MIN_FLOW_TEMP): vol.All(
                    vol.Coerce(float), vol.Range(min=20, max=90)
                ),
                vol.Required(CONF_MAX_FLOW, default=DEFAULT_MAX_FLOW_TEMP): vol.All(
                    vol.Coerce(float), vol.Range(min=30, max=95)
                ),
                vol.Required(CONF_CURVE, default=DEFAULT_CURVE_COEFF): vol.All(
                    vol.Coerce(float), vol.Range(min=0.2, max=3.5)
                ),
            }
        )
        return self.async_show_form(
            step_id="hcs",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "hint": "Native MQTT topics (hcs/<node>/…). The node id is shown on the device web UI and in its discovery payload."
            },
        )

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add a heated room: TRV + optional external temperature sensor.

        The HCS ESP module is the boiler gateway for the whole system — it is
        not selected per room. Temperature comes from an external sensor when
        present, otherwise from the TRV's own current_temperature.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            control = user_input.get(CONF_ZONE_HEAT_CONTROL, HEAT_CONTROL_SMART)
            trv = user_input.get(CONF_ZONE_TRV_CLIMATES)
            if control == HEAT_CONTROL_SMART and not trv:
                # A controlled room needs at least one addressable TRV;
                # manual-radiator rooms legitimately have none.
                errors["base"] = "trv_required"
            else:
                # Selector may return str (single) or list; normalise to list.
                trv_list = ([trv] if isinstance(trv, str) else list(trv)) if trv else []
                try:
                    floor = int(user_input.get(CONF_ZONE_FLOOR, 0) or 0)
                except (TypeError, ValueError):
                    floor = 0
                zone = {
                    CONF_ZONE_NAME: user_input[CONF_ZONE_NAME],
                    CONF_ZONE_TRV_CLIMATES: trv_list,
                    CONF_ZONE_TEMP_SENSOR: user_input.get(CONF_ZONE_TEMP_SENSOR) or None,
                    CONF_ZONE_WINDOW_SENSORS: user_input.get(CONF_ZONE_WINDOW_SENSORS)
                    or [],
                    CONF_ZONE_FLOOR: max(0, floor),
                    CONF_ZONE_HEAT_CONTROL: control,
                }
                self._zones.append(zone)

                if user_input.get("add_another"):
                    return await self.async_step_zone()

                return self.async_create_entry(
                    title=self._data.get(CONF_NAME, NAME),
                    data={
                        CONF_BACKEND: self._data[CONF_BACKEND],
                        CONF_NODE_ID: self._data.get(CONF_NODE_ID, ""),
                        CONF_NAME: self._data.get(CONF_NAME, NAME),
                    },
                    options={
                        CONF_MIN_FLOW: self._data[CONF_MIN_FLOW],
                        CONF_MAX_FLOW: self._data[CONF_MAX_FLOW],
                        CONF_CURVE: self._data[CONF_CURVE],
                        CONF_ZONES: self._zones,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ZONE_NAME, default=f"Room {len(self._zones) + 1}"
                ): str,
                vol.Required(
                    CONF_ZONE_HEAT_CONTROL, default=HEAT_CONTROL_SMART
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=HEAT_CONTROL_SMART, label="Smart TRV (controlled by HCC)"),
                            selector.SelectOptionDict(value=HEAT_CONTROL_MANUAL, label="Manual radiator (valve turned by hand)"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_ZONE_TRV_CLIMATES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate", multiple=True)
                ),
                vol.Optional(CONF_ZONE_FLOOR, default=0): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=30, step=1, mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(CONF_ZONE_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor", device_class="temperature"
                    )
                ),
                vol.Optional(CONF_ZONE_WINDOW_SENSORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor",
                        device_class=["window", "door", "opening"],
                        multiple=True,
                    )
                ),
                vol.Optional("add_another", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="zone",
            data_schema=schema,
            errors=errors,
            description_placeholders={"zone_count": str(len(self._zones))},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HomeClimateControlOptionsFlow()


class HomeClimateControlOptionsFlow(config_entries.OptionsFlow):
    """Options flow: retune curve / flow limits."""

    def _options_schema(self) -> vol.Schema:
        opts = self.config_entry.options
        return vol.Schema(
            {
                vol.Required(
                    CONF_MIN_FLOW,
                    default=opts.get(CONF_MIN_FLOW, DEFAULT_MIN_FLOW_TEMP),
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=MIN_FLOW_TEMP_LIMIT, max=MAX_FLOW_TEMP_LIMIT),
                ),
                vol.Required(
                    CONF_MAX_FLOW,
                    default=opts.get(CONF_MAX_FLOW, DEFAULT_MAX_FLOW_TEMP),
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=MIN_FLOW_TEMP_LIMIT, max=MAX_FLOW_TEMP_LIMIT),
                ),
                vol.Required(
                    CONF_CURVE, default=opts.get(CONF_CURVE, DEFAULT_CURVE_COEFF)
                ): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=CURVE_COEFF_MIN, max=CURVE_COEFF_MAX),
                ),
                vol.Required(
                    CONF_AUTOTUNE,
                    default=opts.get(CONF_AUTOTUNE, True),
                    description="auto_tune_curve",
                ): bool,
                vol.Required(
                    CONF_LEARN_SETBACKS,
                    default=opts.get(CONF_LEARN_SETBACKS, True),
                    description="learn_setbacks",
                ): bool,
                vol.Optional(
                    CONF_OUTDOOR_SENSOR,
                    description="outdoor_sensor",
                    **(
                        {"default": opts[CONF_OUTDOOR_SENSOR]}
                        if opts.get(CONF_OUTDOOR_SENSOR)
                        else {}
                    ),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "weather"],
                        multiple=False,
                    )
                ),
                vol.Required(
                    CONF_MIN_MOD,
                    default=opts.get(CONF_MIN_MOD, DEFAULT_BOILER_MIN_MODULATION),
                    description="boiler_min_modulation",
                ): vol.All(vol.Coerce(float), vol.Range(min=5, max=80)),
                vol.Required(
                    CONF_DUTY_EN,
                    default=opts.get(CONF_DUTY_EN, True),
                    description="duty_cycle_enabled",
                ): bool,
                vol.Required(
                    CONF_GAS_POWER_KW,
                    default=opts.get(CONF_GAS_POWER_KW, 24.0),
                    description="rated_heat_input_kw",
                ): vol.All(vol.Coerce(float), vol.Range(min=1, max=200)),
                vol.Required(
                    CONF_GAS_MIN_KW,
                    default=opts.get(CONF_GAS_MIN_KW, 0.0),
                    description="min_heat_input_kw",
                ): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
                vol.Required(
                    CONF_GAS_NOMOD,
                    default=opts.get(CONF_GAS_NOMOD, 0.6),
                    description="nomod_duty_factor",
                ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1)),
                vol.Required(
                    CONF_GAS_CALIB,
                    default=opts.get(CONF_GAS_CALIB, 1.0),
                    description="gas_calibration",
                ): vol.All(vol.Coerce(float), vol.Range(min=0.01, max=10)),
                vol.Required(
                    CONF_GAS_PRICE,
                    default=opts.get(CONF_GAS_PRICE),
                    description="gas_price_per_kwh",
                ): vol.Any(
                    None, vol.All(vol.Coerce(float), vol.Range(min=0))
                ),
            }
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            mn = float(user_input.get(CONF_MIN_FLOW, DEFAULT_MIN_FLOW_TEMP))
            mx = float(user_input.get(CONF_MAX_FLOW, DEFAULT_MAX_FLOW_TEMP))
            if mn >= mx:
                errors["base"] = "min_flow_above_max"
            else:
                options = {**self.config_entry.options, **user_input}
                # Clearing the entity picker omits the key — drop stale value.
                if CONF_OUTDOOR_SENSOR not in user_input:
                    options.pop(CONF_OUTDOOR_SENSOR, None)
                elif not user_input.get(CONF_OUTDOOR_SENSOR):
                    options.pop(CONF_OUTDOOR_SENSOR, None)
                return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="init",
            data_schema=self._options_schema(),
            errors=errors,
        )
