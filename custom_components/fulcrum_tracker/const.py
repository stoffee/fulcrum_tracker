"""Constants for the Fulcrum Tracker integration."""
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

DOMAIN = "fulcrum_tracker"

# Configuration Constants
CONF_PERSON_ID = "person_id"
CONF_CLIENT_ID = "client_id"
CONF_START_DATE = "start_date"
CONF_MONTHLY_COST = "monthly_cost"
CONF_CALENDAR_ID = "calendar_id"
CONF_SERVICE_ACCOUNT_PATH = "service_account_path"

# Default Values
DEFAULT_START_DATE = "2021-11-01"
DEFAULT_UPDATE_INTERVAL = 1440  # minutes
DEFAULT_PERSON_ID = ""  # Will be provided by user during setup
DEFAULT_USER_ID = DEFAULT_PERSON_ID 
DEFAULT_CLIENT_ID = ""  # Will be provided by user during setup
DEFAULT_MONTHLY_COST = 315.35  # Default monthly cost
DEFAULT_CACHE_TTL = 86400  # 1 hour in seconds

# Scheduling Constants
UPDATE_TIME_HOUR = 19  # 7 PM
UPDATE_TIME_MINUTE = 0
UPDATE_TIMEZONE = "America/Los_Angeles"  # PST/PDT
UPDATE_RETRY_DELAY = 300  # 5 minutes between retry attempts
UPDATE_MAX_RETRIES = 3

# Calendar Search Terms
CALENDAR_SEARCH_TERMS = [
    "Small Group Personal Training Hawthorne",
    "Small Group Training",
    "Small Group",
    "Fulcrum",
    "exercise",
    "fix back",
    "fucking back exercise",
    "Do the back muscles"
]

# trainer names
TRAINERS = [
    "Ash",
    "Cate",
    "Charlotte",
    "Cheryl",
    "Curtis",
    "Dakayla",
    "Devon",
    "Ellis",
    "Emma",
    "Eric",
    "Genevieve",
    "Reggie",
    "Shane",
    "Shelby",
    "Sonia",
    "Sydney",
    "Walter",
    "Zei"
]

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
ERROR_CALENDAR_AUTH = "Google Calendar authentication failed"
ERROR_CALENDAR_FETCH = "Failed to fetch calendar events"

# Data processing
DEFAULT_SLEEP_TIME = 2  # seconds between requests
MAX_RETRIES = 3

# Display formats
DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
MONTH_FORMAT = "%B %Y"
TIME_FORMAT = "%I:%M %p"