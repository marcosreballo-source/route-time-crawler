import sqlite3
import logging
from datetime import datetime
import pytz
from config.settings import CACHE_DB_PATH, TIMEZONE

logger = logging.getLogger(__name__)

class GeocodeCache:
    """
    Cache for geocoding coordinates to avoid duplicate calls to the Geocoding API,
    as the 15 addresses are fixed.
    """
    def __init__(self, db_path=CACHE_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite cache table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS geocode_cache (
                address TEXT PRIMARY KEY,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                formatted_address TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def get_cached_coordinates(self, address: str):
        """
        Retrieves cached coordinates for a given address if it exists.
        Returns a tuple of (lat, lng, formatted_address) or None.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT lat, lng, formatted_address FROM geocode_cache WHERE address = ?",
            (address.strip(),)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            logger.info(f"Geocoding cache hit for address: {address}")
            return row[0], row[1], row[2]
        return None

    def set_cached_coordinates(self, address: str, lat: float, lng: float, formatted_address: str):
        """Saves geocoded coordinates in the cache."""
        tz = pytz.timezone(TIMEZONE)
        timestamp = datetime.now(tz).isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """INSERT OR REPLACE INTO geocode_cache (address, lat, lng, formatted_address, timestamp)
                   VALUES (?, ?, ?, ?, ?)""",
                (address.strip(), lat, lng, formatted_address, timestamp)
            )
            conn.commit()
            logger.info(f"Cached geocoding coordinates for address: {address} -> ({lat}, {lng})")
        except Exception as e:
            logger.error(f"Error caching coordinates: {str(e)}")
        finally:
            conn.close()
