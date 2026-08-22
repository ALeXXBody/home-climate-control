"""Constants for the Home Climate System component."""

from homeassistant.const import PRECISION_HALVES

# Base constants
DOMAIN = "home_climate_system"
DEFAULT_NAME = "Home Climate System"

# Temperature settings
DEFAULT_MIN_TEMP = 5.0
DEFAULT_MAX_TEMP = 35.0
DEFAULT_TARGET_TEMP_STEP = PRECISION_HALVES

# HVAC modes
DEFAULT_HVAC_MODES = [
    "off",
    "heat",
]

# Preset modes
DEFAULT_PRESET_MODES = ["none", "away", "boost", "comfort"]

# Boiler control settings
DEFAULT_BOILER_STATE = False

# PID controller parameters (enhanced)
PID_KP_DEFAULT = 2.0      # Proportional gain - increased for faster response
PID_KI_DEFAULT = 0.5      # Integral gain - reduced to prevent overshoot  
PID_KD_DEFAULT = 1.0      # Derivative gain - added for stability

# Control parameters
MODULATION_MIN = 0        # Minimum modulation level (percent)
MODULATION_MAX = 100      # Maximum modulation level (percent)

# Time settings
UPDATE_INTERVAL_SECONDS = 30    # How often to update the system

# Sensor configuration  
SENSOR_TEMPERATURE_ENTITY_ID = "sensor.temperature"