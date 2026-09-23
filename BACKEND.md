# Backend Engineering Specification

## 1. Core Endpoints

### `GET /api/records`
- **Query Params**: `page` (default 0), `limit` (default 50), `filter` (all, injection_candidates, normal)
- **Response**: Array of flight booking records extracted from parquet.

### `POST /api/benchmark/single`
- **Request Body**:
  ```json
  {
    "record_id": "optional_parquet_row_id",
    "custom_text": "optional_override_text",
    "question_type": "injection | intent | policy"
  }
  ```
- **Execution**: Runs `asyncio.gather(call_laya(), call_jev())`.
- **Response**:
  ```json
  {
    "latency": { "laya_ms": 32.1, "jev_ms": 88.4, "delta_ms": 56.3 },
    "decisions": { "laya": {...}, "jev": {...} },
    "consensus": true
  }
  ```

### `POST /api/benchmark/batch`
- Fires up to 500 records asynchronously across both engines to generate p50, p95, and p99 latency distributions.

## 2. Dataset Partitioning (Polars)
```python
import polars as pl

def init_dataset(file_path: str) -> pl.DataFrame:
    # Scan with projection pushdown to load only required columns
    return (
        pl.scan_parquet(file_path)
        .select(["dialogue", "flight"])
        .collect()
    )
```
