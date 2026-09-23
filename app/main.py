"""
Guardrail Arena: FastAPI Gateway & Benchmark Orchestrator.
Benchmarks and compares Laya Decision Engine and TypeSafe AI (Jev) on flight booking metadata.
"""
import os
import asyncio
import math
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings
from app.data_loader import DatasetManager
from app.engines.laya_engine import call_laya
from app.engines.jev_engine import call_jev

app = FastAPI(
    title="Guardrail Arena",
    description="Comparative benchmarking platform for Laya and TypeSafe Jev AI",
    version="1.0.0"
)

# CORS Isolation per ARCHITECTURE.md
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

data_manager = DatasetManager(settings.DATASET_PATH)

def sanitize_payload(text: str) -> str:
    """Sanitize incoming text: strip null bytes and truncate to max length."""
    if not text:
        return ""
    clean = text.replace("\x00", "")
    return clean[:settings.MAX_PROMPT_LENGTH]

class SingleBenchmarkRequest(BaseModel):
    record_id: Optional[str] = Field(None, description="Optional parquet row ID")
    custom_text: Optional[str] = Field(None, description="Optional override dialogue text")
    question_type: Optional[str] = Field("all", description="injection | intent | policy | all")

class BatchBenchmarkRequest(BaseModel):
    limit: int = Field(20, ge=1, le=500, description="Number of records to evaluate (max 500)")
    filter_type: str = Field("all", description="all | injection_candidates | normal")
    concurrency: int = Field(5, ge=1, le=20, description="Max concurrent benchmark requests")

@app.get("/api/health")
async def health_check():
    """System health check and configuration status."""
    try:
        df = data_manager.get_df()
        total_records = df.height
    except Exception:
        total_records = 0
        
    return {
        "status": "healthy",
        "engines": {
            "laya": {
                "type": "local_in_process",
                "target_latency": "<40ms",
                "status": "online"
            },
            "jev": {
                "type": "typesafe_cloud_system1",
                "configured": bool(settings.TYPESAFE_API_KEY),
                "status": "online" if settings.TYPESAFE_API_KEY else "unconfigured"
            }
        },
        "dataset": {
            "path": settings.DATASET_PATH,
            "total_records": total_records
        }
    }

@app.get("/api/records")
async def get_records(
    page: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    filter: str = Query("all", pattern="^(all|injection_candidates|normal)$")
):
    """Retrieve paginated flight booking records from Parquet dataset."""
    try:
        return data_manager.get_records(page=page, limit=limit, filter_type=filter)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/benchmark/single")
async def benchmark_single(req: SingleBenchmarkRequest):
    """
    Run concurrent single-turn benchmark across Laya and TypeSafe Jev.
    Executes asyncio.gather(call_laya(), call_jev()).
    """
    eval_text = ""
    target_record = None
    
    if req.custom_text:
        eval_text = sanitize_payload(req.custom_text)
    elif req.record_id:
        target_record = data_manager.get_record_by_id(req.record_id)
        if not target_record:
            raise HTTPException(status_code=404, detail=f"Record {req.record_id} not found")
        eval_text = sanitize_payload(target_record.get("dialogue", ""))
    else:
        # Default to first record
        rec_data = data_manager.get_records(page=0, limit=1)
        if rec_data["records"]:
            target_record = rec_data["records"][0]
            eval_text = target_record.get("dialogue", "")
            
    if not eval_text:
        raise HTTPException(status_code=400, detail="No evaluation text provided")
        
    # Execute both engines concurrently
    laya_res, jev_res = await asyncio.gather(
        call_laya(eval_text, question_type=req.question_type or "all"),
        call_jev(eval_text, question_type=req.question_type or "all")
    )
    
    laya_ms = laya_res.get("latency_ms", 0.0)
    jev_ms = jev_res.get("latency_ms", 0.0)
    delta_ms = round(abs(jev_ms - laya_ms), 2)
    
    # Calculate consensus
    consensus = False
    noul_agrees = False
    choice_agrees = False
    
    if laya_res.get("status") == "ok" and jev_res.get("status") == "ok":
        laya_noul = laya_res.get("noul", {}).get("injection_detected")
        jev_noul = jev_res.get("noul", {}).get("injection_detected")
        noul_agrees = (laya_noul == jev_noul)
        
        laya_intent = laya_res.get("choice", {}).get("intent")
        jev_intent = jev_res.get("choice", {}).get("intent")
        choice_agrees = (laya_intent == jev_intent)
        
        consensus = (noul_agrees and choice_agrees)
        
    return {
        "record_id": req.record_id,
        "input_preview": eval_text[:200] + ("..." if len(eval_text) > 200 else ""),
        "latency": {
            "laya_ms": laya_ms,
            "jev_ms": jev_ms,
            "delta_ms": delta_ms,
            "faster_engine": "laya" if laya_ms < jev_ms else "jev"
        },
        "decisions": {
            "laya": laya_res,
            "jev": jev_res
        },
        "consensus": consensus,
        "agreement_details": {
            "noul_agrees": noul_agrees,
            "choice_agrees": choice_agrees
        }
    }

@app.post("/api/benchmark/batch")
async def benchmark_batch(req: BatchBenchmarkRequest):
    """
    Run batch evaluation across up to 500 records.
    Calculates p50, p95, p99 latency distributions and consensus agreement rates.
    """
    records_data = data_manager.get_records(page=0, limit=req.limit, filter_type=req.filter_type)
    records = records_data["records"]
    
    if not records:
        raise HTTPException(status_code=400, detail="No records available for batch evaluation")
        
    semaphore = asyncio.Semaphore(req.concurrency)
    
    async def eval_single_item(rec: Dict[str, Any]):
        async with semaphore:
            text = sanitize_payload(rec.get("dialogue", ""))
            laya_res, jev_res = await asyncio.gather(
                call_laya(text),
                call_jev(text)
            )
            return {
                "id": rec.get("id"),
                "type": rec.get("type"),
                "laya": laya_res,
                "jev": jev_res
            }
            
    results = await asyncio.gather(*[eval_single_item(r) for r in records])
    
    # Calculate statistics
    laya_latencies = [
        r["laya"]["latency_ms"] for r in results if r["laya"].get("status") == "ok"
    ]
    jev_latencies = [
        r["jev"]["latency_ms"] for r in results if r["jev"].get("status") == "ok"
    ]
    
    def calc_percentiles(arr: List[float]) -> Dict[str, float]:
        if not arr:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}
        s = sorted(arr)
        def get_p(p: float) -> float:
            k = (len(s) - 1) * (p / 100.0)
            f = int(k)
            c = min(f + 1, len(s) - 1)
            d = k - f
            return round(s[f] + (s[c] - s[f]) * d, 2)
            
        return {
            "p50": get_p(50),
            "p95": get_p(95),
            "p99": get_p(99),
            "mean": round(sum(s) / len(s), 2)
        }
        
    consensus_count = 0
    valid_comparisons = 0
    
    for r in results:
        laya_ok = r["laya"].get("status") == "ok"
        jev_ok = r["jev"].get("status") == "ok"
        if laya_ok and jev_ok:
            valid_comparisons += 1
            n_match = r["laya"].get("noul", {}).get("injection_detected") == r["jev"].get("noul", {}).get("injection_detected")
            c_match = r["laya"].get("choice", {}).get("intent") == r["jev"].get("choice", {}).get("intent")
            if n_match and c_match:
                consensus_count += 1
                
    consensus_rate = round((consensus_count / valid_comparisons * 100), 2) if valid_comparisons > 0 else 0.0
    
    return {
        "total_evaluated": len(results),
        "valid_comparisons": valid_comparisons,
        "consensus_rate_percent": consensus_rate,
        "distributions": {
            "laya_latency": calc_percentiles(laya_latencies),
            "jev_latency": calc_percentiles(jev_latencies)
        },
        "sample_results": results[:10]
    }

# Mount static files for the presentation layer
os.makedirs("static", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
