"""Polars-based flight booking dataset loader with projection pushdown."""
import os
import polars as pl
from typing import List, Dict, Any, Optional

def init_dataset(file_path: str) -> pl.DataFrame:
    """Scan with projection pushdown to load required columns per BACKEND.md."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset not found at {file_path}")
    return (
        pl.scan_parquet(file_path)
        .select(["id", "dialogue", "flight", "intent", "type", "status"])
        .collect()
    )

class DatasetManager:
    def __init__(self, file_path: str):
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
