"""Constants for the Fulcrum Tracker integration."""
from datetime import datetime

DOMAIN = "fulcrum_tracker"
CONF_START_DATE = "start_date"

# Default Values
DEFAULT_START_DATE = "2021-11-01"
DEFAULT_UPDATE_INTERVAL = 30  # minutes

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

# User Constants
DEFAULT_USER_ID = "E28E53AA-CE35-4958-9B3F-C46584509E03"
DEFAULT_CLIENT_ID = "5FB54891-E59C-4B11-B594-D6273E607418"

# Error messages
ERROR_AUTH = "Authentication failed"
ERROR_CONNECTION = "Connection failed"
ERROR_TIMEOUT = "Request timed out"
ERROR_INVALID_DATA = "Invalid data received"

# Data processing
DEFAULT_SLEEP_TIME = 2  # seconds between requests
MAX_RETRIES = 3

# Date handling
TIMEZONE = "America/Los_Angeles"
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Display formats
MONTH_FORMAT = "%B %Y"
TIME_FORMAT = "%I:%M %p"