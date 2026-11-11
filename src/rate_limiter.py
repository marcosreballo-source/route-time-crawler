import time
import sqlite3
import logging
from datetime import datetime
import pytz
from config.settings import (
    CACHE_DB_PATH, TIMEZONE, BUDGET_USD, API_KEYS,
    COST_PER_MATRIX_ELEMENT_USD, COST_PER_GEOCODE_REQUEST_USD,
    COST_PER_DIRECTIONS_REQUEST_USD, MAX_RETRIES, BACKOFF_FACTOR
)

logger = logging.getLogger(__name__)

class BudgetExceededError(Exception):
    """Raised when the API calls cost exceeds the defined monthly budget."""
    pass

class RateLimiter:
    """
    Manages rate limits, retries, and tracks costs in SQLite to guarantee
    the project stays within the R$200 monthly budget.
    """
    def __init__(self, db_path=CACHE_DB_PATH, tokens_per_sec=10):
        self.db_path = db_path
        self.tokens_per_sec = tokens_per_sec
        self.capacity = tokens_per_sec
        self.tokens = tokens_per_sec
        self.last_update = time.time()
        self.api_keys = API_KEYS
        self.current_key_index = 0
        self._init_db()

    def _init_db(self):
        """Initializes the database table for tracking cost logs."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS api_cost_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                api_name TEXT NOT NULL,
                request_count INTEGER NOT NULL,
                element_count INTEGER NOT NULL,
                cost_usd REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def _acquire_token(self):
        """Simple token bucket implementation for rate limiting."""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.tokens_per_sec)
        self.last_update = now

        if self.tokens < 1.0:
            sleep_time = (1.0 - self.tokens) / self.tokens_per_sec
            time.sleep(sleep_time)
            self.tokens = 0.0
            self.last_update = time.time()
        else:
            self.tokens -= 1.0

    def get_monthly_spent_usd(self) -> float:
        """Calculates the total USD spent during the current month."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get start of current month in America/Sao_Paulo
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz)
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        cursor.execute(
            "SELECT SUM(cost_usd) FROM api_cost_log WHERE timestamp >= ?",
            (start_of_month,)
        )
        row = cursor.fetchone()
        spent = row[0] if row[0] is not None else 0.0
        conn.close()
        return spent

    def log_api_call(self, api_name: str, request_count: int, element_count: int):
        """
        Logs an API call and calculates cost. Raises BudgetExceededError 
        if the call would breach the budget limit.
        """
        # Calculate cost
        if api_name == "geocode":
            cost = COST_PER_GEOCODE_REQUEST_USD * request_count
        elif api_name == "matrix":
            cost = COST_PER_MATRIX_ELEMENT_USD * element_count
        elif api_name == "directions":
            cost = COST_PER_DIRECTIONS_REQUEST_USD * request_count
        else:
            cost = 0.0

        current_spent = self.get_monthly_spent_usd()
        if current_spent + cost > BUDGET_USD:
            msg = (
                f"Budget limit warning! Current spent: ${current_spent:.2f} USD, "
                f"this call would cost ${cost:.2f} USD, exceeding the limit of ${BUDGET_USD:.2f} USD."
            )
            logger.error(msg)
            raise BudgetExceededError(msg)

        tz = pytz.timezone(TIMEZONE)
        timestamp = datetime.now(tz).isoformat()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO api_cost_log (timestamp, api_name, request_count, element_count, cost_usd) VALUES (?, ?, ?, ?, ?)",
            (timestamp, api_name, request_count, element_count, cost)
        )
        conn.commit()
        conn.close()
        
        logger.info(f"API Call logged: {api_name} | Cost: ${cost:.4f} USD | Total Spent this month: ${current_spent + cost:.4f} USD")

    def execute_with_retry(self, api_name: str, call_func, *args, element_count: int = 1, **kwargs):
        """
        Executes a Google API request with rate limiting, budget control, and exponential backoff retries.
        """
        # 1. Check budget before proceeding
        # We don't log the call yet (in case it fails), but we check if it will exceed
        spent = self.get_monthly_spent_usd()
        if api_name == "geocode":
            expected_cost = COST_PER_GEOCODE_REQUEST_USD
        elif api_name == "matrix":
            expected_cost = COST_PER_MATRIX_ELEMENT_USD * element_count
        elif api_name == "directions":
            expected_cost = COST_PER_DIRECTIONS_REQUEST_USD
        else:
            expected_cost = 0.0

        if spent + expected_cost > BUDGET_USD:
            raise BudgetExceededError(
                f"Cannot execute API call. Spent ${spent:.2f} USD, limit is ${BUDGET_USD:.2f} USD."
            )

        if not self.api_keys:
            raise ValueError("No API keys available.")

        # 3. Retry loop with Key Rotation
        retries = 0
        keys_attempted = 0
        
        while retries <= MAX_RETRIES and keys_attempted <= len(self.api_keys):
            # 2. Acquire rate limiting token
            self._acquire_token()
            
            current_key = self.api_keys[self.current_key_index]
            try:
                # call_func must accept the api_key as the first argument
                response = call_func(current_key, *args, **kwargs)
                
                # 4. Log the call now that it succeeded
                self.log_api_call(api_name, 1, element_count)
                return response
            except Exception as e:
                err_str = str(e).upper()
                # If error is related to quota or auth, rotate the key
                if any(term in err_str for term in ["REQUEST_DENIED", "OVER_QUERY_LIMIT", "API_KEY_INVALID", "403", "429"]):
                    logger.warning(f"Key index {self.current_key_index} failed with {err_str}. Rotating key...")
                    self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    keys_attempted += 1
                    if keys_attempted >= len(self.api_keys):
                        logger.error(f"All {len(self.api_keys)} API keys failed. Aborting.")
                        raise e
                    continue # Retry immediately with the new key

                if any(term in err_str for term in ["INVALID_REQUEST", "NOT_FOUND"]):
                    logger.error(f"Permanent error in API {api_name}: {str(e)}. Aborting retries.")
                    raise e

                retries += 1
                if retries > MAX_RETRIES:
                    logger.critical(f"Max retries reached for API {api_name}. Error: {str(e)}")
                    raise e
                
                sleep_time = BACKOFF_FACTOR ** retries
                logger.warning(f"Error calling {api_name} (attempt {retries}/{MAX_RETRIES}): {str(e)}. Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
