"""Constants for Home Climate Control."""

DOMAIN = "home_climate_control"
MANUFACTURER = "Home Climate Control"
NAME = "Home Climate Control"

# Sidebar app (custom panel)
PANEL_URL_PATH = "home-climate"
PANEL_TITLE = "Home Climate"
PANEL_ICON = "mdi:home-thermometer"
PANEL_WEBCOMPONENT = "home-climate-panel"
PANEL_STATIC_URL = f"/{DOMAIN}_static"
PANEL_JS = "home-climate-panel.js"

# --- Boiler limits -----------------------------------------------------------
DEFAULT_MIN_FLOW_TEMP = 25.0
DEFAULT_MAX_FLOW_TEMP = 75.0
MIN_FLOW_TEMP_LIMIT = 10.0
MAX_FLOW_TEMP_LIMIT = 90.0

# --- Heating curve -----------------------------------------------------------
# Precision-curve style: flow = room_setpoint + coeff * (setpoint - outdoor)
# scaled against design outdoor temperature.
DEFAULT_CURVE_COEFF = 1.2
CURVE_COEFF_MIN = 0.1
CURVE_COEFF_MAX = 3.0
DESIGN_OUTDOOR_TEMP = -10.0  # design condition for the building (radiators)

# Underfloor systems run lower flows and react slower.
UNDERFLOOR_MAX_FLOW_DEFAULT = 50.0
UNDERFLOOR_SAMPLE_TIME_SCALE = 3.0

# --- PID ---------------------------------------------------------------------
PID_KP = 12.0  # °C flow per °C room error, scaled by curve coeff at runtime
PID_KI = 0.15
PID_KD = 0.0
PID_INTEGRAL_CLAMP = 15.0  # max °C contribution from I term
PID_SAMPLE_SECONDS = 60.0

# --- Low-load duty cycling ---------------------------------------------------
# When required modulation < boiler min modulation we cycle instead of letting
# the boiler short-cycle on its own thermostat logic.
DEFAULT_BOILER_MIN_MODULATION = 20.0  # percent, user-tunable
DUTY_CYCLE_MIN_ON_SECONDS = 600.0
DUTY_CYCLE_MIN_OFF_SECONDS = 600.0

# --- Zones -------------------------------------------------------------------
PRESET_NONE = "none"
PRESET_AWAY = "away"
PRESET_ECO = "eco"
PRESET_COMFORT = "comfort"
PRESET_BOOST = "boost"
ZONE_PRESETS = [PRESET_NONE, PRESET_AWAY, PRESET_ECO, PRESET_COMFORT, PRESET_BOOST]

PRESET_OFFSETS = {
    PRESET_AWAY: -4.0,
    PRESET_ECO: -2.0,
    PRESET_COMFORT: 0.5,
    PRESET_BOOST: +2.0,
}

DEFAULT_MIN_ROOM_TEMP = 5.0
DEFAULT_MAX_ROOM_TEMP = 30.0
DEFAULT_TARGET_STEP = 0.5
DEFAULT_ZONE_SETPOINT = 20.0

# --- Window detection --------------------------------------------------------
WINDOW_OPEN_PAUSE_MINUTES = 30

# --- Outdoor temperature staleness ------------------------------------------
OUTDOOR_STALE_AFTER_SECONDS = 1800

# --- Control loop ------------------------------------------------------------
CONTROL_LOOP_SECONDS = 60

# --- Backend selection -------------------------------------------------------
CONF_BACKEND = "backend"
BACKEND_HCS = "hcs"
BACKEND_DEMO = "demo"
BACKENDS = [BACKEND_DEMO, BACKEND_HCS]

# --- MQTT (Home Climate System device) ---------------------------------------
CONF_NODE_ID = "node_id"
DEMO_UNIQUE_ID = "hcc_demo"
DEMO_DEFAULT_OUTDOOR = 5.0
DEMO_DEFAULT_ROOMS = (
    ("Living Room", 18.5, 21.0),
    ("Bedroom", 17.0, 19.0),
)
CONF_OUTDOOR_SENSOR = "outdoor_sensor"
CONF_WIND_ENABLED = "wind_compensation"
CONF_WIND_ENTITY = "wind_entity"
CONF_WIND_MAX_DELTA = "wind_max_delta"
DEFAULT_WIND_MAX_DELTA = 3.0
CONF_SCHEDULE_ENTITY = "schedule_entity"
CONF_SCHEDULE_ON_PRESET = "schedule_on_preset"
CONF_SCHEDULE_OFF_PRESET = "schedule_off_preset"
CONF_OCCUPANCY_ENABLED = "occupancy_enabled"
CONF_OCCUPANCY_TRACKERS = "occupancy_trackers"
CONF_OCCUPANCY_AWAY_PRESET = "occupancy_away_preset"
CONF_OCCUPANCY_HOME_PRESET = "occupancy_home_preset"

# Rooms (stored under options key "zones" for backward compatibility).
# A room is: one TRV climate + optional external temperature sensor.
# If no external sensor is set, the TRV's current_temperature is used.
# The HCS ESP module is the boiler gateway only — never a room member.
CONF_ZONES = "zones"  # options key (legacy name; UI says "Rooms")
CONF_ZONE_NAME = "name"
CONF_ZONE_TEMP_SENSOR = "temp_sensor"  # optional external wall sensor
CONF_ZONE_WINDOW_SENSORS = "window_sensors"
CONF_ZONE_TRV_CLIMATES = "trv_climates"  # one or more climate entities (TRV)
CONF_ZONE_FLOOR = "floor"  # int: 0 = ground floor, 1 = first floor, ...
CONF_ZONE_HEAT_CONTROL = "heat_control"  # smart | manual
HEAT_CONTROL_SMART = "smart"    # addressable TRV: HCC commands it
HEAT_CONTROL_MANUAL = "manual"  # hand-turned valve: HCC observes only
CONF_ZONE_IS_UNDERFLOOR = "underfloor"

# Tier 3/4 per-room extras
CONF_ZONE_LUX_SENSOR = "lux_sensor"          # Tier 3: solar gain (sensor.*)
CONF_ZONE_CO2_SENSOR = "co2_sensor"          # Tier 3: air quality (sensor.*)
CONF_ZONE_RADIATOR_KW = "radiator_kw"        # Tier 4: nominal kW @ ΔT50
CONF_ZONE_TRV_POSITION = "trv_position_entity"  # Tier 4: valve 0-100 (sensor./number.*)

# Telemetry subjects on the native hcs/<node> bus (informational only):
# (docs/api/MQTT.md "OpenTherm Numeric Values" + status flags).
# Command subjects under <prefix>/set/<node-id>/<command> (MQTTstuff.ino setcmds).

