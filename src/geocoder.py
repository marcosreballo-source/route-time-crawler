import json
import logging
import requests
from typing import List, Dict, Any, Optional

from config.settings import (
    GEOCODE_API_URL, API_KEY, CONFIG_DIR,
    SP_LAT_MIN, SP_LAT_MAX, SP_LNG_MIN, SP_LNG_MAX, VERIFY_SSL
)
from src.cache import GeocodeCache
from src.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

class Geocoder:
    """
    Geocoder resolves addresses to GPS coordinates with caching and bounding box validation.
    """
    def __init__(self, cache: GeocodeCache, rate_limiter: RateLimiter):
        self.cache = cache
        self.rate_limiter = rate_limiter

    def is_in_sp_region(self, lat: float, lng: float) -> bool:
        """Checks if coordinates are within the São Paulo Metropolitan bounding box."""
        return SP_LAT_MIN <= lat <= SP_LAT_MAX and SP_LNG_MIN <= lng <= SP_LNG_MAX

    def geocode_address(self, address: str) -> Optional[Dict[str, Any]]:
        """
        Geocodes a single address. Uses cache if available, otherwise queries API.
        """
        # 1. Check cache first
        cached = self.cache.get_cached_coordinates(address)
        if cached:
            lat, lng, formatted_address = cached
            return {
                "lat": lat,
                "lng": lng,
                "formatted_address": formatted_address,
                "source": "cache"
            }

        # 2. Call Geocoding API
        if not API_KEY:
            logger.warning("API Key is missing. Falling back to Nominatim.")
            return self._geocode_with_nominatim_fallback(address)

        def _call_api():
            params = {
                "address": address,
                "key": API_KEY
            }
            response = requests.get(GEOCODE_API_URL, params=params, verify=VERIFY_SSL, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "OK":
                raise ValueError(f"Geocoding API error: {data.get('status')} - {data.get('error_message', '')}")
            
            return data

        try:
            logger.info(f"Querying Geocoding API for address: {address}")
            # Geocoding API costs $5 per 1000 requests (Essentials), i.e., 1 request = 1 element
            api_response = self.rate_limiter.execute_with_retry(
                "geocode", _call_api, element_count=1
            )
            
            results = api_response.get("results", [])
            if not results:
                logger.warning(f"No geocoding results found for address: {address}. Falling back to Nominatim.")
                return self._geocode_with_nominatim_fallback(address)
                
            location = results[0]["geometry"]["location"]
            lat = location["lat"]
            lng = location["lng"]
            formatted_address = results[0]["formatted_address"]

            # Validate geofence
            if not self.is_in_sp_region(lat, lng):
                logger.warning(
                    f"Geocoded coordinates ({lat}, {lng}) for address '{address}' "
                    f"are outside São Paulo Metropolitan Area."
                )

            # Store in cache
            self.cache.set_cached_coordinates(address, lat, lng, formatted_address)

            return {
                "lat": lat,
                "lng": lng,
                "formatted_address": formatted_address,
                "source": "api"
            }

        except Exception as e:
            logger.warning(f"Failed to geocode address '{address}' via Google API: {str(e)}. Falling back to Nominatim...")
            return self._geocode_with_nominatim_fallback(address)

    def _geocode_with_nominatim_fallback(self, address: str) -> Optional[Dict[str, Any]]:
        """Fallback to free OSM Nominatim geocoding if Google API fails or is disabled."""
        try:
            import re
            from geopy.geocoders import Nominatim
            
            # Clean address for Nominatim (remove " - CEP \d+" or "CEP \d+")
            query_address = re.sub(r"\s*-\s*CEP\s*\d+\s*", "", address, flags=re.IGNORECASE)
            query_address = re.sub(r"CEP\s*\d+\s*", "", query_address, flags=re.IGNORECASE)
            query_address = query_address.strip()
            
            logger.info(f"Querying Nominatim (OSM) with cleaned query: '{query_address}' (original: '{address}')")
            # Use unique user agent as required by OSM terms of service
            geolocator = Nominatim(user_agent="delivery_graph_collector")
            location = geolocator.geocode(query_address, timeout=10)
            if location:
                lat = location.latitude
                lng = location.longitude
                formatted_address = location.address

                # Validate geofence
                if not self.is_in_sp_region(lat, lng):
                    logger.warning(
                        f"Nominatim geocoded coordinates ({lat}, {lng}) for address '{address}' "
                        f"are outside São Paulo Metropolitan Area."
                    )

                # Store in cache using the ORIGINAL address string as key
                self.cache.set_cached_coordinates(address, lat, lng, formatted_address)

                return {
                    "lat": lat,
                    "lng": lng,
                    "formatted_address": formatted_address,
                    "source": "nominatim"
                }
            else:
                logger.error(f"Nominatim geocoder returned None for query: '{query_address}'")
                return None
        except Exception as ex:
            logger.error(f"Nominatim geocoding exception for address '{address}': {str(ex)}")
            return None

    def geocode_addresses_file(self, file_path=CONFIG_DIR / "addresses.json") -> List[Dict[str, Any]]:
        """
        Reads addresses.json, geocodes unresolved addresses, updates coordinates,
        and saves them back to the JSON file.
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Addresses file not found at: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            addresses = json.load(f)

        updated = False
        for entry in addresses:
            # Re-geocode if lat/lng is missing
            if entry.get("lat") is None or entry.get("lng") is None:
                result = self.geocode_address(entry["address"])
                if result:
                    entry["lat"] = result["lat"]
                    entry["lng"] = result["lng"]
                    entry["formatted_address"] = result["formatted_address"]
                    updated = True
                else:
                    logger.warning(f"Could not resolve coordinates for ID {entry['id']}")

        if updated:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(addresses, f, indent=2, ensure_ascii=False)
            logger.info(f"Updated addresses file saved: {file_path}")
        else:
            logger.info("All addresses already geocoded. No updates needed.")

        return addresses
