"""Constants for the Fulcrum Tracker integration."""
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

DOMAIN = "fulcrum_tracker"

# Configuration Constants
CONF_PERSON_ID = "person_id"
CONF_CLIENT_ID = "client_id"
CONF_START_DATE = "start_date"
CONF_MONTHLY_COST = "monthly_cost"

# Default Values
DEFAULT_START_DATE = "2021-11-01"
DEFAULT_UPDATE_INTERVAL = 1440  # minutes
DEFAULT_PERSON_ID = ""  # Will be provided by user during setup
DEFAULT_USER_ID = DEFAULT_PERSON_ID 
DEFAULT_CLIENT_ID = ""  # Will be provided by user during setup
DEFAULT_MONTHLY_COST = 315.35  # Default monthly cost

# API Constants
API_BASE_URL = "https://fulcrum.sites.zenplanner.com"
API_ENDPOINTS = {
    "login": "/login.cfm",
    "workouts": "/workouts.cfm",
    "calendar": "/calendar.cfm",
    "pr_page": "/workout-pr-page.cfm",
    "attendance": "/person-attendance.cfm",
    "month_calendar": "/calendar/month-calendar.cfm"
}

# Error messages
ERROR_AUTH = "Authentication failed"
ERROR_CONNECTION = "Connection failed"
ERROR_TIMEOUT = "Request timed out"
ERROR_INVALID_DATA = "Invalid data received"

# Data processing
DEFAULT_SLEEP_TIME = 2  # seconds between requests
MAX_RETRIES = 3

# Display formats
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MONTH_FORMAT = "%B %Y"
TIME_FORMAT = "%I:%M %p"