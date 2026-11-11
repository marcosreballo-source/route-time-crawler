import logging
import requests
import re
from datetime import datetime
import pytz
from typing import List, Dict, Any, Tuple

from config.settings import (
    ROUTES_MATRIX_API_URL, TIMEZONE, TIMEOUT_SECONDS, VERIFY_SSL
)
from src.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

class RoutesMatrixCollector:
    """
    Collects distance and travel time matrix between locations using 
    Google Maps Routes API (computeRouteMatrix).
    """
    def __init__(self, rate_limiter: RateLimiter):
        self.rate_limiter = rate_limiter

    def _parse_duration(self, duration_str: str) -> int:
        """
        Parses Google API duration string (e.g. '123s' or '54.2s') into integer seconds.
        """
        if not duration_str:
            return 0
        match = re.match(r"^([\d.]+)\s*s$", duration_str)
        if match:
            return int(float(match.group(1)))
        return 0

    def collect_matrix(self, locations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Collects the 15x15 (225 elements) route matrix.
        Returns a list of dictionaries representing each O-D pair.
        """
        # No longer checking API_KEY here since it's managed by rate_limiter

        # Prepare payloads
        # We need to construct origins and destinations waypoints
        waypoints = []
        for loc in locations:
            waypoints.append({
                "waypoint": {
                    "location": {
                        "latLng": {
                            "latitude": loc["lat"],
                            "longitude": loc["lng"]
                        }
                    }
                }
            })

        # Routes API Compute Route Matrix payload
        payload = {
            "origins": waypoints,
            "destinations": waypoints,
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE"
        }

        def _call_api(api_key: str):
            # Header with API key and FieldMask
            # FieldMask is CRITICAL to keep the request in the Compute Route Matrix Essentials SKU ($5.00/1000 elements)
            # Adding features like staticDuration or travelAdvisory triggers the Pro SKU ($10.00/1000 elements).
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,condition,status"
            }

            logger.info("Sending request to Google Maps Routes API (computeRouteMatrix)...")
            response = requests.post(
                ROUTES_MATRIX_API_URL,
                json=payload,
                headers=headers,
                verify=VERIFY_SSL,
                timeout=TIMEOUT_SECONDS
            )
            response.raise_for_status()
            return response.json()

        # Execute API call with retries and budget enforcement.
        # 15 locations x 15 locations = 225 elements.
        num_elements = len(locations) * len(locations)
        try:
            raw_response = self.rate_limiter.execute_with_retry(
                "matrix", _call_api, element_count=num_elements
            )
        except Exception as e:
            logger.error(f"Failed to collect route matrix: {str(e)}")
            raise e

        # Get current timestamp in local timezone
        tz = pytz.timezone(TIMEZONE)
        collect_time = datetime.now(tz)

        # Parse response
        records = []
        
        # The response is an array of objects. Note that the matrix items can arrive in ANY order.
        # Each item has originIndex and destinationIndex.
        for item in raw_response:
            origin_idx = item.get("originIndex", 0)
            dest_idx = item.get("destinationIndex", 0)
            
            origin = locations[origin_idx]
            dest = locations[dest_idx]
            
            # Parse duration and distance
            duration_str = item.get("duration", "0s")
            duration_s = self._parse_duration(duration_str)
            distance_m = item.get("distanceMeters", 0)
            condition = item.get("condition", "ROUTE_EXISTS")
            status = item.get("status", {})

            # Check if there is an error status
            if status and status.get("code") != 0:
                logger.warning(
                    f"API returned error status for route {origin['id']} -> {dest['id']}: {status}"
                )
                condition = "ERROR"

            record = {
                "origin_id": origin["id"],
                "origin_name": origin["name"],
                "origin_lat": origin["lat"],
                "origin_lng": origin["lng"],
                "destination_id": dest["id"],
                "destination_name": dest["name"],
                "dest_lat": dest["lat"],
                "dest_lng": dest["lng"],
                "timestamp": collect_time.isoformat(),
                "distance_m": distance_m,
                "duration_traffic_s": duration_s,
                "day_of_week": collect_time.weekday(),  # 0=Monday, 6=Sunday
                "day_name": collect_time.strftime("%A"),
                "hour": collect_time.hour,
                "minute": collect_time.minute,
                "is_weekday": collect_time.weekday() < 5,
                "is_peak": self._is_peak_hour(collect_time),
                "period": self._get_time_period(collect_time),
                "route_condition": condition
            }
            records.append(record)

        # In case some elements are missing from the response (e.g. self-loops, though Google usually computes them),
        # we can backfill them with 0 distance/duration if origin == destination.
        seen_pairs = {(r["origin_id"], r["destination_id"]) for r in records}
        for o_idx, origin in enumerate(locations):
            for d_idx, dest in enumerate(locations):
                if (origin["id"], dest["id"]) not in seen_pairs:
                    # Self loops should be 0, others we log warning
                    if origin["id"] == dest["id"]:
                        record = {
                            "origin_id": origin["id"],
                            "origin_name": origin["name"],
                            "origin_lat": origin["lat"],
                            "origin_lng": origin["lng"],
                            "destination_id": dest["id"],
                            "destination_name": dest["name"],
                            "dest_lat": dest["lat"],
                            "dest_lng": dest["lng"],
                            "timestamp": collect_time.isoformat(),
                            "distance_m": 0,
                            "duration_traffic_s": 0,
                            "day_of_week": collect_time.weekday(),
                            "day_name": collect_time.strftime("%A"),
                            "hour": collect_time.hour,
                            "minute": collect_time.minute,
                            "is_weekday": collect_time.weekday() < 5,
                            "is_peak": self._is_peak_hour(collect_time),
                            "period": self._get_time_period(collect_time),
                            "route_condition": "ROUTE_EXISTS"
                        }
                        records.append(record)
                    else:
                        logger.warning(f"O-D pair {origin['id']} -> {dest['id']} was missing from the API response.")

        logger.info(f"Collected {len(records)} matrix elements successfully.")
        return records

    def _is_peak_hour(self, dt: datetime) -> bool:
        """Determines if a given datetime is during São Paulo peak hours (7-9h, 17-19h)."""
        if dt.weekday() >= 5:  # Weekend
            return False
        hour = dt.hour
        minute = dt.minute
        # Morning peak: 07:00 - 09:30, Afternoon peak: 17:00 - 19:30
        is_morning = (7 <= hour < 9) or (hour == 9 and minute <= 30)
        is_afternoon = (17 <= hour < 19) or (hour == 19 and minute <= 30)
        return is_morning or is_afternoon

    def _get_time_period(self, dt: datetime) -> str:
        """Categorizes time of day into logistically relevant periods."""
        hour = dt.hour
        if 23 <= hour or hour < 5:
            return "night"
        elif 5 <= hour < 7:
            return "early_morning"
        elif 7 <= hour < 10:
            return "morning_peak"
        elif 10 <= hour < 12:
            return "mid_morning"
        elif 12 <= hour < 14:
            return "lunchtime"
        elif 14 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 20:
            return "evening_peak"
        else:
            return "late_evening"
