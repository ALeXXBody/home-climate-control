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
BACKEND_OTGW_MQTT = "otgw_mqtt"
BACKEND_HCS = "hcs_native"
BACKEND_DEMO = "demo"
# BACKEND_HCS reuses the OTGW-MQTT backend (devices publish an OTGW-compat
# mirror under node id "hcs-device") — it exists so setup reads correctly.
BACKENDS = [BACKEND_DEMO, BACKEND_HCS, BACKEND_OTGW_MQTT]

# --- MQTT (OTGW-firmware) ----------------------------------------------------
CONF_OTGW_PREFIX = "otgw_prefix"
CONF_OTGW_NODE_ID = "otgw_node_id"
DEFAULT_OTGW_PREFIX = "OTGW"
DEMO_UNIQUE_ID = "hcc_demo"
DEMO_DEFAULT_OUTDOOR = 5.0
DEMO_DEFAULT_ROOMS = (
    ("Living Room", 18.5, 21.0),
    ("Bedroom", 17.0, 19.0),
)
# Node id defaults to the gateway hostname pattern published by otgw-firmware,
# e.g. "otgw-AABBCCDDEEFF". User must confirm it in config flow.
CONF_OUTDOOR_SENSOR = "outdoor_sensor"

CONF_ZONES = "zones"
CONF_ZONE_NAME = "name"
CONF_ZONE_TEMP_SENSOR = "temp_sensor"
CONF_ZONE_WINDOW_SENSORS = "window_sensors"
CONF_ZONE_TRV_CLIMATES = "trv_climates"
CONF_ZONE_IS_UNDERFLOOR = "underfloor"

# Telemetry subjects published by otgw-firmware under <prefix>/
# (docs/api/MQTT.md "OpenTherm Numeric Values" + status flags).
OTGW_TOPIC_MAP = {
    "control_setpoint": "controlsetpoint",
    "room_setpoint": "roomsetpoint",
    "room_temp": "roomtemperature",
    "modulation_level": "relmodlvl",
    "max_modulation": "maxrelmodlvl",
    "flow_temp": "boilertemperature",
    "return_temp": "returnwatertemperature",
    "dhw_temp": "dhwtemperature",
    "outside_temp": "outsidetemperature",
    "ch_pressure": "chwaterpressure",
    "flame": "flamestatus",      # ON/OFF
    "ch_active": "chmodus",      # ON/OFF
    "dhw_active": "dhwmode",     # ON/OFF
}

# Command subjects under <prefix>/set/<node-id>/<command> (MQTTstuff.ino setcmds).
OTGW_CMD_FLOW_SETPOINT = "ctrlsetpt"   # CS=<temp>
OTGW_CMD_MAX_MODULATION = "maxmodulation"  # MM=<level>
OTGW_CMD_CH_ENABLE = "chenable"        # CH=on/off

