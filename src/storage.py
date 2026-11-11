import os
import json
import logging
from datetime import datetime
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path
from typing import List, Dict, Any

from config.settings import RAW_DATA_DIR, PROCESSED_DATA_DIR

logger = logging.getLogger(__name__)

class StorageManager:
    """
    Manages saving and loading collected matrix data in Parquet format
    and exporting it to OR-Tools compatible JSON.
    """
    def __init__(self, raw_dir: Path = RAW_DATA_DIR, processed_dir: Path = PROCESSED_DATA_DIR):
        self.raw_dir = raw_dir
        self.processed_dir = processed_dir
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def save_snapshot_parquet(self, records: List[Dict[str, Any]]):
        """
        Saves a snapshot list of dictionaries as a partitioned Parquet dataset.
        Appends to existing partition directories.
        """
        if not records:
            logger.warning("No records to save.")
            return

        df = pd.DataFrame(records)
        
        # Parse timestamp to extract partition keys
        dt_series = pd.to_datetime(df["timestamp"])
        df["year"] = dt_series.dt.year.astype("int32")
        df["month"] = dt_series.dt.month.astype("int32")
        df["day"] = dt_series.dt.day.astype("int32")

        # Convert to Arrow Table
        table = pa.Table.from_pandas(df, preserve_index=False)

        # Write to dataset (appends new files automatically inside partition subdirectories)
        logger.info(f"Writing {len(records)} records to Parquet dataset at {self.raw_dir}")
        pq.write_to_dataset(
            table,
            root_path=str(self.raw_dir),
            partition_cols=["year", "month", "day"]
        )
        logger.info("Parquet write complete.")

    def export_ortools_json(self, records: List[Dict[str, Any]], locations: List[Dict[str, Any]], filename: str = None) -> Path:
        """
        Exports collected matrix records to OR-Tools compatible JSON format.
        Puts Hub first in the locations list.
        """
        # Sort locations: hub first, then stores
        sorted_locations = sorted(locations, key=lambda l: 0 if l["type"] == "hub" else 1)
        
        # Mapping from node ID to index
        id_to_idx = {loc["id"]: i for i, loc in enumerate(sorted_locations)}
        num_nodes = len(sorted_locations)

        # Initialize empty matrices
        distance_matrix = [[0] * num_nodes for _ in range(num_nodes)]
        time_matrix = [[0] * num_nodes for _ in range(num_nodes)]

        # Map records to matrix cells
        for rec in records:
            o_id = rec["origin_id"]
            d_id = rec["destination_id"]
            
            if o_id in id_to_idx and d_id in id_to_idx:
                o_idx = id_to_idx[o_id]
                d_idx = id_to_idx[d_id]
                
                distance_matrix[o_idx][d_idx] = int(rec["distance_m"])
                time_matrix[o_idx][d_idx] = int(rec["duration_traffic_s"])

        # Format locations array
        # Hub gets: "type": "depot", "name": name
        # Store gets: "type": "delivery", "id": index, "demand": 1 (default), "time_window": [9, 18] (default 9h-18h)
        formatted_locs = []
        for i, loc in enumerate(sorted_locations):
            if loc["type"] == "hub":
                formatted_locs.append({
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "type": "depot",
                    "name": loc["name"]
                })
            else:
                formatted_locs.append({
                    "lat": loc["lat"],
                    "lng": loc["lng"],
                    "type": "delivery",
                    "id": i - 1, # Delivery ID starts from 0 for stores
                    "name": loc["name"],
                    "demand": 1,
                    "time_window": [9, 18]  # Default store hours: 9 AM to 6 PM
                })

        output_data = {
            "locations": formatted_locs,
            "distance_matrix": distance_matrix,
            "time_matrix": time_matrix
        }

        # Generate filename if not provided
        if not filename:
            dt_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"ortools_matrix_{dt_str}.json"

        output_path = self.processed_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=4, ensure_ascii=False)

        logger.info(f"OR-Tools dataset exported successfully to {output_path}")
        return output_path

    def load_all_data(self) -> pd.DataFrame:
        """
        Loads all raw parquet snapshots into a single pandas DataFrame.
        """
        # Read the raw parquet dataset directory
        if not self.raw_dir.exists() or len(list(self.raw_dir.glob("**/*.parquet"))) == 0:
            logger.warning("No parquet data files found.")
            return pd.DataFrame()

        logger.info(f"Loading Parquet dataset from {self.raw_dir}...")
        df = pd.read_parquet(str(self.raw_dir))
        return df
