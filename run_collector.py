import argparse
import json
import logging
import sys
from pathlib import Path

# Setup root logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(__file__).resolve().parent / "logs" / "collector.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("run_collector")

from config.settings import CONFIG_DIR
from src.rate_limiter import RateLimiter
from src.collector import RoutesMatrixCollector
from src.polyline_collector import PolylineCollector
from src.storage import StorageManager

def main():
    parser = argparse.ArgumentParser(description="Delivery Graph Dataset Collector (Google Maps Routes API)")
    parser.add_argument(
        "--action", 
        type=str, 
        choices=["matrix", "polylines", "all"], 
        default="matrix", 
        help="Action to perform: 'matrix' (collect OD snapshot), 'polylines' (collect physical route polylines), or 'all' (both)."
    )
    parser.add_argument(
        "--export-ortools", 
        action="store_true", 
        default=True, 
        help="Whether to export an OR-Tools compatible JSON file from the collected matrix."
    )
    
    args = parser.parse_args()
    
    # 1. Load coordinates
    addresses_file = CONFIG_DIR / "addresses.json"
    if not addresses_file.exists():
        logger.critical(f"Addresses file does not exist at {addresses_file}. Run geocoder first.")
        sys.exit(1)
        
    with open(addresses_file, "r", encoding="utf-8") as f:
        locations = json.load(f)
        
    # Check if geocoded
    for loc in locations:
        if loc.get("lat") is None or loc.get("lng") is None:
            logger.critical(f"Location {loc['id']} has unresolved coordinates. Run geocoder first.")
            sys.exit(1)

    # Initialize components
    rate_limiter = RateLimiter()
    storage = StorageManager()
    
    logger.info(f"Loaded {len(locations)} locations. Action: {args.action}")

    # 2. Collect OD Matrix
    if args.action in ["matrix", "all"]:
        logger.info("Initializing matrix collection...")
        collector = RoutesMatrixCollector(rate_limiter)
        
        try:
            records = collector.collect_matrix(locations)
            storage.save_snapshot_parquet(records)
            
            if args.export_ortools:
                json_path = storage.export_ortools_json(records, locations)
                logger.info(f"OR-Tools JSON exported to {json_path}")
        except Exception as e:
            logger.error(f"Error during matrix collection: {str(e)}")
            sys.exit(1)

    # 3. Collect Polylines (Physical Routes)
    if args.action in ["polylines", "all"]:
        logger.info("Initializing polyline collection...")
        polyline_collector = PolylineCollector(rate_limiter)
        
        try:
            routes = polyline_collector.collect_all_polylines(locations)
            logger.info(f"Collected and cached {len(routes)} route polylines.")
        except Exception as e:
            logger.error(f"Error during polyline collection: {str(e)}")
            sys.exit(1)

    logger.info("Task completed successfully.")

if __name__ == "__main__":
    main()
