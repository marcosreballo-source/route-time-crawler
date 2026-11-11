import os
import re
import urllib3
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
POLYLINES_DIR = DATA_DIR / "polylines"
LOGS_DIR = BASE_DIR / "logs"
CACHE_DB_PATH = DATA_DIR / "cache.db"

# Create directories
for directory in [CONFIG_DIR, SRC_DIR, DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, POLYLINES_DIR, LOGS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# SSL Certificate Verification bypass (necessary for corporate network proxy)
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() != "false"
if not VERIFY_SSL:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# API Key loading
API_KEYS_PATH = BASE_DIR / "API_KEYS.txt"
API_KEYS = []
if API_KEYS_PATH.exists():
    with open(API_KEYS_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                match = re.search(r"AIzaSy[A-Za-z0-9_-]+", line)
                if match:
                    API_KEYS.append(match.group(0))
                else:
                    API_KEYS.append(line)
else:
    env_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if env_key:
        API_KEYS.append(env_key)

if not API_KEYS:
    # Fallback to older APIKEY.txt if needed
    API_KEY_PATH = BASE_DIR / "APIKEY.txt"
    if API_KEY_PATH.exists():
        with open(API_KEY_PATH, "r", encoding="utf-8") as f:
            content = f.read().strip()
            match = re.search(r"AIzaSy[A-Za-z0-9_-]+", content)
            API_KEYS.append(match.group(0) if match else content)

# Timezone
TIMEZONE = "America/Sao_Paulo"

# Google Maps APIs
GEOCODE_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
ROUTES_MATRIX_API_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_DIRECTIONS_API_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"

# Budget and Cost limits
# Routes Compute Route Matrix (Essentials SKU): $5.00 per 1000 elements.
# Geocoding API (Essentials SKU): $5.00 per 1000 requests.
# Routes Directions (Compute Routes Essentials SKU): $5.00 per 1000 requests.
COST_PER_MATRIX_ELEMENT_USD = 0.005
COST_PER_GEOCODE_REQUEST_USD = 0.005
COST_PER_DIRECTIONS_REQUEST_USD = 0.005

# Monthly Budget limit in BRL (user has R$1727.36 for the 90-day phase which is about $319 USD at 5.4 BRL/USD rate)
# We track in USD since Google bills in USD.
USD_BRL_RATE = 5.4
BUDGET_BRL = 1727.36
BUDGET_USD = BUDGET_BRL / USD_BRL_RATE

# Geofence for São Paulo Metropolitan Area (for geocoding validation)
SP_LAT_MIN, SP_LAT_MAX = -24.0, -23.2
SP_LNG_MIN, SP_LNG_MAX = -47.0, -45.8

# Network parameters
TIMEOUT_SECONDS = 15
MAX_RETRIES = 5
BACKOFF_FACTOR = 2.0  # Exponential backoff base
