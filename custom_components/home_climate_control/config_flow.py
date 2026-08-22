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
    CONF_OTGW_NODE_ID,
    CONF_OTGW_PREFIX,
    CONF_ZONE_NAME,
    CONF_ZONE_TEMP_SENSOR,
    CONF_ZONE_TRV_CLIMATES,
    CONF_ZONE_WINDOW_SENSORS,
    CONF_ZONES,
    CURVE_COEFF_MAX,
    CURVE_COEFF_MIN,
    DEFAULT_CURVE_COEFF,
    DEFAULT_MAX_FLOW_TEMP,
    DEFAULT_MIN_FLOW_TEMP,
    DEFAULT_OTGW_PREFIX,
    DOMAIN,
    MAX_FLOW_TEMP_LIMIT,
    MIN_FLOW_TEMP_LIMIT,
    NAME,
)

CONF_MIN_FLOW = "min_flow_temp"
CONF_MAX_FLOW = "max_flow_temp"
CONF_CURVE = "curve_coeff"


class HomeClimateControlConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Home Climate Control."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._zones: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: boiler / OTGW connection."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                f"hcc_{user_input[CONF_OTGW_PREFIX]}_{user_input[CONF_OTGW_NODE_ID]}"
            )
            self._abort_if_unique_id_configured()
            self._data = user_input
            return await self.async_step_zone()

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=NAME): str,
                vol.Required(CONF_OTGW_PREFIX, default=DEFAULT_OTGW_PREFIX): str,
                vol.Required(CONF_OTGW_NODE_ID): str,
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
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_zone(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2+: add heating zones (at least one)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            zone = {
                CONF_ZONE_NAME: user_input[CONF_ZONE_NAME],
                CONF_ZONE_TEMP_SENSOR: user_input[CONF_ZONE_TEMP_SENSOR],
                CONF_ZONE_WINDOW_SENSORS: user_input.get(CONF_ZONE_WINDOW_SENSORS) or [],
                CONF_ZONE_TRV_CLIMATES: user_input.get(CONF_ZONE_TRV_CLIMATES) or [],
            }
            self._zones.append(zone)

            if user_input.get("add_another"):
                return await self.async_step_zone()

            return self.async_create_entry(
                title=self._data.get(CONF_NAME, NAME),
                data={
                    CONF_OTGW_PREFIX: self._data[CONF_OTGW_PREFIX],
                    CONF_OTGW_NODE_ID: self._data[CONF_OTGW_NODE_ID],
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
                vol.Required(CONF_ZONE_NAME, default=f"Zone {len(self._zones) + 1}"): str,
                vol.Required(CONF_ZONE_TEMP_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
                ),
                vol.Optional(CONF_ZONE_WINDOW_SENSORS): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="binary_sensor",
                        device_class=["window", "door", "opening"],
                        multiple=True,
                    )
                ),
                vol.Optional(CONF_ZONE_TRV_CLIMATES): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate", multiple=True)
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
    """Options flow: retune curve / flow limits. Zones reconfiguration later."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            options = {**self.config_entry.options, **user_input}
            return self.async_create_entry(title="", data=options)

        opts = self.config_entry.options
        schema = vol.Schema(
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
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
