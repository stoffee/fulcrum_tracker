"""Constants for the Fulcrum Tracker integration."""
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD

DOMAIN = "fulcrum_tracker"
CONF_START_DATE = "start_date"
CONF_PERSON_ID = "person_id"
CONF_CLIENT_ID = "client_id"

# Configuration Keys
CONF_MONTHLY_COST = "monthly_cost"

# Default Values
DEFAULT_START_DATE = "2021-11-01"
DEFAULT_UPDATE_INTERVAL = 30  # minutes
DEFAULT_MONTHLY_COST = 0.0

# API Constants
API_BASE_URL = "https://fulcrum.sites.zenplanner.com"

# Error messages
ERROR_AUTH = "Authentication failed"
ERROR_CONNECTION = "Connection failed"

# Schema version
CONFIG_VERSION = 1