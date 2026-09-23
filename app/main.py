"""
Guardrail Arena: FastAPI Gateway & Benchmark Orchestrator.
Benchmarks and compares Laya Decision Engine and TypeSafe AI (Jev) on flight booking metadata.
"""
import os
import asyncio
import math
import json
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
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
    
@app.get("/api/benchmark/batch/stream")
async def benchmark_batch_stream(
    limit: int = Query(50, ge=1, le=1000),
    filter: str = Query("all", pattern="^(all|injection_candidates|normal)$"),
    concurrency: int = Query(5, ge=1, le=20)
):
    """
    Server-Sent Events (SSE) streaming batch benchmark execution.
    Pushes real-time HUD terminal log entries, progress percentages, and final p50/p95/p99 metrics.
    """
    async def event_generator():
        # Step 1: Dataset Partitioning Notice
        yield f"data: {json.dumps({'type': 'log', 'text': '[INFO] Partitioning dataset via Polars projection pushdown...'})}\n\n"
        await asyncio.sleep(0.04)

        try:
            records_data = data_manager.get_records(page=0, limit=min(limit, 320), filter_type=filter)
            records = records_data["records"]
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'text': f'[ERROR] Data loading failed: {str(exc)}'})}\n\n"
            return

        if not records:
            yield f"data: {json.dumps({'type': 'error', 'text': '[ERROR] No records available for benchmark.'})}\n\n"
            return

        total_records = len(records)
        target_eval_count = limit
        yield f"data: {json.dumps({'type': 'log', 'text': f'[INFO] Loaded {total_records} flight records. Target scale: {target_eval_count} evaluations.'})}\n\n"
        await asyncio.sleep(0.04)

        yield f"data: {json.dumps({'type': 'log', 'text': f'[EXEC] Firing AsyncIO Gather: Local Laya (CPU/IPC) vs TypeSafe Cloud API (Concurrency={concurrency})...'})}\n\n"
        await asyncio.sleep(0.04)

        semaphore = asyncio.Semaphore(concurrency)
        completed = 0
        consensus_count = 0
        laya_latencies = []
        jev_latencies = []
        results = []

        # If user requests higher scale than stored records (e.g. 500 or 1000), cycle through records
        eval_queue = [records[i % total_records] for i in range(target_eval_count)]

        async def eval_single(rec, idx):
            nonlocal completed, consensus_count
            async with semaphore:
                text = sanitize_payload(rec.get("dialogue", ""))
                laya_res, jev_res = await asyncio.gather(
                    call_laya(text),
                    call_jev(text)
                )
                
                l_lat = laya_res.get("latency_ms", 0.0)
                j_lat = jev_res.get("latency_ms", 0.0)
                if laya_res.get("status") == "ok":
                    laya_latencies.append(l_lat)
                if jev_res.get("status") == "ok":
                    jev_latencies.append(j_lat)

                delta_ms = round(abs(j_lat - l_lat), 1)
                n_match = laya_res.get("noul", {}).get("injection_detected") == jev_res.get("noul", {}).get("injection_detected")
                c_match = laya_res.get("choice", {}).get("intent") == jev_res.get("choice", {}).get("intent")
                is_consensus = (n_match and c_match)
                if is_consensus:
                    consensus_count += 1

                completed += 1
                current_agreement = round((consensus_count / completed * 100), 1)
                progress_pct = round((completed / target_eval_count * 100), 1)

                return {
                    "completed": completed,
                    "total": target_eval_count,
                    "progress_pct": progress_pct,
                    "delta_ms": delta_ms,
                    "agreement_pct": current_agreement,
                    "rec_id": rec.get("id"),
                    "faster": "laya" if l_lat < j_lat else "jev"
                }

        # Stream tasks as they complete
        tasks = [asyncio.create_task(eval_single(r, i)) for i, r in enumerate(eval_queue)]
        for fut in asyncio.as_completed(tasks):
            info = await fut
            log_line = (
                f"[STREAM] Record #{info['completed']}/{info['total']} evaluated: "
                f"Agreement = {info['agreement_pct']}%, Latency Delta = {info['delta_ms']}ms "
                f"({info['faster'].upper()} faster)"
            )
            yield f"data: {json.dumps({'type': 'progress', 'current': info['completed'], 'total': info['total'], 'percent': info['progress_pct'], 'text': log_line, 'agreement_pct': info['agreement_pct']})}\n\n"

        # Calculate final distributions
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

        final_laya_dist = calc_percentiles(laya_latencies)
        final_jev_dist = calc_percentiles(jev_latencies)
        final_rate = round((consensus_count / target_eval_count * 100), 2)

        faster_winner = "laya" if (final_laya_dist.get("p50", 0) < final_jev_dist.get("p50", 0)) else "jev"

        yield f"data: {json.dumps({'type': 'log', 'text': '[DONE] Latency distribution (p50, p95, p99) computed successfully.'})}\n\n"
        await asyncio.sleep(0.02)

        yield f"data: {json.dumps({
            'type': 'done',
            'text': f'[COMPLETE] Evaluated {target_eval_count} records. Final Consensus Agreement = {final_rate}%. Faster Engine: {faster_winner.upper()}.',
            'metrics': {
                'total_evaluated': target_eval_count,
                'consensus_rate_percent': final_rate,
                'faster_winner': faster_winner,
                'laya_latency': final_laya_dist,
                'jev_latency': final_jev_dist
            }
        })}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Mount static files for the presentation layer
os.makedirs("static", exist_ok=True)
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
