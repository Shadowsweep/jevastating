"""
Dual-Domain Data Loader using Polars.
Loads Flight (Air Dialogue) and Railway (IRCTC 30k) reservation datasets with projection pushdown.
"""
import os
import polars as pl
from typing import List, Dict, Any, Optional
from app.config import settings, BASE_DIR

# --- Flight Booking Dataset Loader ---

def init_dataset(file_path: str = settings.FLIGHT_DATASET_PATH) -> pl.DataFrame:
    """Scan with projection pushdown to load required columns per BACKEND.md."""
    if not os.path.isabs(file_path):
        file_path = os.path.join(BASE_DIR, file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Flight dataset not found at {file_path}")
    return (
        pl.scan_parquet(file_path)
        .select(["id", "dialogue", "flight", "intent", "type", "status"])
        .collect()
    )

class DatasetManager:
    def __init__(self, file_path: str = settings.FLIGHT_DATASET_PATH):
        self.file_path = file_path
        self._df: Optional[pl.DataFrame] = None
        
    def get_df(self) -> pl.DataFrame:
        if self._df is None:
            self._df = init_dataset(self.file_path)
        return self._df

    def get_records(
        self,
        page: int = 0,
        limit: int = 50,
        filter_type: str = "all"
    ) -> Dict[str, Any]:
        """Fetch paginated flight booking records with optional filtering."""
        df = self.get_df()
        
        if filter_type == "injection_candidates":
            filtered_df = df.filter(pl.col("type") == "injection_candidates")
        elif filter_type == "normal":
            filtered_df = df.filter(pl.col("type") == "normal")
        else:
            filtered_df = df
            
        total = filtered_df.height
        offset = page * limit
        paginated_df = filtered_df.slice(offset, limit)
        
        records: List[Dict[str, Any]] = paginated_df.to_dicts()
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "filter": filter_type,
            "records": records
        }

    def get_record_by_id(self, record_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve single record by its parquet row id."""
        df = self.get_df()
        match_df = df.filter(pl.col("id") == record_id)
        if match_df.height == 0:
            return None
        return match_df.to_dicts()[0]


# --- Railway PNR Dataset Loader ---

def init_railway_dataset(file_path: str = settings.RAILWAY_DATASET_PATH) -> pl.DataFrame:
    """Read railway parquet dataset using Polars projection pushdown."""
    if not os.path.isabs(file_path):
        file_path = os.path.join(BASE_DIR, file_path)
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Railway dataset not found at {file_path}")
    return pl.read_parquet(file_path)

class RailwayDatasetManager:
    def __init__(self, file_path: str = settings.RAILWAY_DATASET_PATH):
        self.file_path = file_path
        self._df: Optional[pl.DataFrame] = None
        
    def get_df(self) -> pl.DataFrame:
        if self._df is None:
            self._df = init_railway_dataset(self.file_path)
        return self._df

    def format_evaluation_payload(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """Convert tabular PNR record into structured evaluation payload."""
        pnr_meta = {
            "pnr_number": row.get("pnr_number"),
            "train_number": row.get("train_number"),
            "train_type": row.get("train_type"),
            "source_station": row.get("source_station"),
            "destination_station": row.get("destination_station"),
            "quota": row.get("quota"),
            "class_of_travel": row.get("class_of_travel"),
            "travel_distance_km": row.get("travel_distance"),
            "travel_time_hrs": row.get("travel_time"),
            "seat_availability": row.get("seat_availability"),
            "date_of_journey": str(row.get("date_of_journey")),
            "peak_season": row.get("holiday_or_peak_season")
        }
        
        passenger_ctx = {
            "passenger_count": row.get("number_of_passengers"),
            "age_group": row.get("age_of_passengers"),
            "special_consideration": row.get("special_considerations"),
            "booking_channel": row.get("booking_channel"),
            "booking_date": str(row.get("booking_date")),
            "waitlist_position": row.get("waitlist_position"),
            "current_status": row.get("current_status"),
            "confirmation_status": row.get("confirmation_status"),
            "passenger_notes": row.get("passenger_notes")
        }
        
        prompt_text = (
            f"Railway Transaction PNR: {row.get('pnr_number')} | Train: {row.get('train_number')} ({row.get('train_type')}) | "
            f"Route: {row.get('source_station')} -> {row.get('destination_station')} | Distance: {row.get('travel_distance')}km | "
            f"Class: {row.get('class_of_travel')} | Quota Requested: {row.get('quota')} | "
            f"Passenger Demographic: Age={row.get('age_of_passengers')}, Special Consideration={row.get('special_considerations')} | "
            f"Booking Channel: {row.get('booking_channel')} | Seats Available: {row.get('seat_availability')} | "
            f"Peak Season: {row.get('holiday_or_peak_season')} | Status: {row.get('current_status')} (WL: {row.get('waitlist_position')}) | "
            f"Notes/Override: {row.get('passenger_notes') or 'None'}"
        )
        
        return {
            "pnr_number": row.get("pnr_number"),
            "pnr_metadata": pnr_meta,
            "passenger_context": passenger_ctx,
            "evaluation_prompt": prompt_text,
            "is_injection_candidate": bool(row.get("is_injection_candidate", False)),
            "ground_truth": {
                "quota_compliant": bool(row.get("quota_compliant", True)),
                "tatkal_risk": row.get("tatkal_risk", "allow_instant"),
                "clearance_score": row.get("clearance_score", 10)
            }
        }

    def get_records(
        self,
        page: int = 0,
        limit: int = 25,
        quota: str = "all",
        channel: str = "all",
        status: str = "all",
        injection: str = "all"
    ) -> Dict[str, Any]:
        """Paginated PNR query with multi-vector filtering."""
        df = self.get_df()
        
        if quota != "all":
            df = df.filter(pl.col("quota") == quota)
        if channel != "all":
            df = df.filter(pl.col("booking_channel") == channel)
        if status != "all":
            df = df.filter(pl.col("current_status") == status)
        if injection == "injection_only":
            df = df.filter(pl.col("is_injection_candidate") == True)
        elif injection == "normal_only":
            df = df.filter(pl.col("is_injection_candidate") == False)
            
        total = df.height
        offset = page * limit
        sliced = df.slice(offset, limit).to_dicts()
        
        records = [self.format_evaluation_payload(r) for r in sliced]
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "filters": {
                "quota": quota,
                "channel": channel,
                "status": status,
                "injection": injection
            },
            "records": records
        }

    def get_record_by_pnr(self, pnr: str) -> Optional[Dict[str, Any]]:
        """Retrieve single record by PNR."""
        df = self.get_df()
        matched = df.filter(pl.col("pnr_number") == pnr)
        if matched.height == 0:
            return None
        return self.format_evaluation_payload(matched.to_dicts()[0])
