import json
import logging
import requests
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from config.settings import (
    ROUTES_DIRECTIONS_API_URL, POLYLINES_DIR, CACHE_DB_PATH, VERIFY_SSL
)
from src.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

def decode_polyline(polyline_str: str) -> List[Tuple[float, float]]:
    """
    Decodes a Google Maps encoded polyline into a list of (latitude, longitude) tuples.
    Pure Python implementation of the Google Polyline Algorithm.
    """
    index, lat, lng = 0, 0, 0
    coordinates = []
    changes = {'latitude': 0, 'longitude': 0}

    try:
        while index < len(polyline_str):
            for unit in ['latitude', 'longitude']:
                shift, result = 0, 0

                while True:
                    byte = ord(polyline_str[index]) - 63
                    index += 1
                    result |= (byte & 0x1f) << shift
                    shift += 5
                    if not (byte >= 0x20):
                        break

                if result & 1:
                    changes[unit] = ~(result >> 1)
                else:
                    changes[unit] = (result >> 1)

            lat += changes['latitude']
            lng += changes['longitude']

            coordinates.append((lat / 100000.0, lng / 100000.0))
    except Exception as e:
        logger.error(f"Error decoding polyline string '{polyline_str[:30]}...': {str(e)}")

    return coordinates

class PolylineCollector:
    """
    Collects and caches physical route paths (polylines) between all O-D pairs.
    Saves results as a GeoJSON dataset.
    """
    def __init__(self, rate_limiter: RateLimiter, db_path: Path = CACHE_DB_PATH):
        self.rate_limiter = rate_limiter
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite cache table for polylines."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS polyline_cache (
                origin_id TEXT,
                destination_id TEXT,
                distance_m INTEGER,
                duration_s INTEGER,
                encoded_polyline TEXT,
                coordinates_json TEXT,
                PRIMARY KEY (origin_id, destination_id)
            )
        """)
        conn.commit()
        conn.close()

    def get_cached_route(self, origin_id: str, destination_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves cached polyline route from SQLite."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT distance_m, duration_s, encoded_polyline, coordinates_json FROM polyline_cache WHERE origin_id = ? AND destination_id = ?",
            (origin_id, destination_id)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            coords = json.loads(row[3])
            geojson_geom = {
                "type": "LineString",
                "coordinates": [[lng, lat] for lat, lng in coords]
            } if coords else None
            return {
                "origin_id": origin_id,
                "destination_id": destination_id,
                "distance_m": row[0],
                "duration_s": row[1],
                "encoded_polyline": row[2],
                "coordinates": coords,
                "geojson": geojson_geom
            }
        return None

    def cache_route(self, origin_id: str, destination_id: str, distance_m: int, duration_s: int, encoded_polyline: str, coordinates: List[Tuple[float, float]]):
        """Saves a computed route to the SQLite cache."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """INSERT OR REPLACE INTO polyline_cache 
                   (origin_id, destination_id, distance_m, duration_s, encoded_polyline, coordinates_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (origin_id, destination_id, distance_m, duration_s, encoded_polyline, json.dumps(coordinates))
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Error caching route {origin_id} -> {destination_id}: {str(e)}")
        finally:
            conn.close()

    def collect_route_polyline(self, origin_loc: Dict[str, Any], dest_loc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Retrieves a route polyline between a single pair. Checks cache first.
        """
        o_id, d_id = origin_loc["id"], dest_loc["id"]
        
        # Self loop check
        if o_id == d_id:
            return {
                "origin_id": o_id,
                "destination_id": d_id,
                "distance_m": 0,
                "duration_s": 0,
                "encoded_polyline": "",
                "coordinates": [],
                "geojson": None
            }

        # Check Cache
        cached = self.get_cached_route(o_id, d_id)
        if cached:
            return cached

        # No longer checking API_KEY here since rate_limiter manages it
        payload = {
            "origin": {"location": {"latLng": {"latitude": origin_loc["lat"], "longitude": origin_loc["lng"]}}},
            "destination": {"location": {"latLng": {"latitude": dest_loc["lat"], "longitude": dest_loc["lng"]}}},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE"
        }

        def _call_api(api_key: str):
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline"
            }
            logger.info(f"Querying Directions API: {o_id} -> {d_id}")
            response = requests.post(
                ROUTES_DIRECTIONS_API_URL,
                json=payload,
                headers=headers,
                verify=VERIFY_SSL,
                timeout=10
            )
            response.raise_for_status()
            return response.json()

        try:
            # Directions API costs $5 per 1000 requests (Compute Routes Essentials)
            api_response = self.rate_limiter.execute_with_retry(
                "directions", _call_api, element_count=1
            )
            
            routes = api_response.get("routes", [])
            if not routes:
                logger.error(f"No routes found for pair: {o_id} -> {d_id}")
                return None

            route = routes[0]
            distance_m = route.get("distanceMeters", 0)
            
            # Parse duration (e.g. "350s")
            dur_str = route.get("duration", "0s")
            dur_s = int(float(dur_str.rstrip('s'))) if dur_str else 0

            encoded_poly = route.get("polyline", {}).get("encodedPolyline", "")
            coordinates = decode_polyline(encoded_poly)

            # Save in cache
            self.cache_route(o_id, d_id, distance_m, dur_s, encoded_poly, coordinates)

            geojson_geom = {
                "type": "LineString",
                "coordinates": [[lng, lat] for lat, lng in coordinates]
            } if coordinates else None

            return {
                "origin_id": o_id,
                "destination_id": d_id,
                "distance_m": distance_m,
                "duration_s": dur_s,
                "encoded_polyline": encoded_poly,
                "coordinates": coordinates,
                "geojson": geojson_geom
            }
        except Exception as e:
            logger.error(f"Failed to fetch route {o_id} -> {d_id}: {str(e)}")
            return None

    def collect_all_polylines(self, locations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Collects polylines for all 210 pairs (15x14, no self-loops).
        """
        routes = []
        count = 0
        total_pairs = len(locations) * (len(locations) - 1)
        
        logger.info(f"Starting polyline collection for {total_pairs} pairs...")
        
        for orig in locations:
            for dest in locations:
                if orig["id"] == dest["id"]:
                    continue
                
                route = self.collect_route_polyline(orig, dest)
                if route:
                    routes.append(route)
                    count += 1
                
                if count % 10 == 0:
                    logger.info(f"Collected {count}/{total_pairs} route polylines...")

        # Export to GeoJSON
        self.export_geojson(routes, locations)
        return routes

    def export_geojson(self, routes: List[Dict[str, Any]], locations: List[Dict[str, Any]], filename: str = "routes.geojson") -> Path:
        """
        Converts the routes list into a standard GeoJSON file.
        """
        features = []
        loc_map = {loc["id"]: loc for loc in locations}

        for r in routes:
            coords = r.get("coordinates", [])
            if not coords:
                continue

            # GeoJSON coordinates are [longitude, latitude]
            geojson_coords = [[lng, lat] for lat, lng in coords]
            
            # Build feature
            feature = {
                "type": "Feature",
                "properties": {
                    "origin_id": r["origin_id"],
                    "origin_name": loc_map.get(r["origin_id"], {}).get("name", ""),
                    "destination_id": r["destination_id"],
                    "destination_name": loc_map.get(r["destination_id"], {}).get("name", ""),
                    "distance_m": r["distance_m"],
                    "duration_s": r["duration_s"]
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": geojson_coords
                }
            }
            features.append(feature)

        geojson_data = {
            "type": "FeatureCollection",
            "features": features
        }

        output_path = POLYLINES_DIR / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(geojson_data, f, indent=4, ensure_ascii=False)

        logger.info(f"GeoJSON exported to: {output_path}")
        return output_path
