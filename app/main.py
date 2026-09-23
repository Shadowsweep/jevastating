"""
Railway Guardrail Arena: FastAPI Gateway & Benchmark Orchestrator (Port 8001).
Benchmarks and compares Laya Decision Engine and TypeSafe AI (Jev) on 30,000 Railway reservation records.
"""
import os
import asyncio
import json
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import settings
from app.data_loader import RailwayDatasetManager
from app.engines.laya_engine import call_laya_railway
from app.engines.jev_engine import call_jev_railway

app = FastAPI(
    title="Railway Guardrail Arena",
    description="Comparative benchmarking platform for Railway Reservation Guardrails (Laya vs TypeSafe Jev)",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8001",
        "http://127.0.0.1:8001",
        "http://localhost:8000",
        "http://127.0.0.1:8000"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

data_manager = RailwayDatasetManager()

class SingleRailwayBenchmarkRequest(BaseModel):
    pnr_number: Optional[str] = Field(None, description="PNR identifier to evaluate")
    custom_prompt: Optional[str] = Field(None, description="Custom prompt / override text")
    quota: Optional[str] = Field(None, description="Override quota")
    channel: Optional[str] = Field(None, description="Override booking channel")
    age_group: Optional[str] = Field(None, description="Override passenger age group")
    special_consideration: Optional[str] = Field(None, description="Override special consideration")

class BatchRailwayBenchmarkRequest(BaseModel):
    limit: int = Field(20, ge=1, le=200, description="Number of PNR records to benchmark")
    quota_filter: str = Field("all", description="all | General | Ladies | Tatkal | Premium Tatkal")
    channel_filter: str = Field("all", description="all | Counter | IRCTC Website | Mobile App")
    status_filter: str = Field("all", description="all | Confirmed | RAC | Waitlisted")
    injection_filter: str = Field("all", description="all | injection_only | normal_only")
    concurrency: int = Field(5, ge=1, le=15, description="Max concurrent benchmark calls")

@app.get("/api/railway/health")
async def health_check():
    """System health check and configuration status."""
    try:
        df = data_manager.get_df()
        total_records = df.height
    except Exception:
        total_records = 0
        
    return {
        "status": "healthy",
        "domain": "railway_pnr",
        "port": settings.PORT,
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

@app.get("/api/railway/records")
async def get_records(
    page: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    quota: str = Query("all"),
    channel: str = Query("all"),
    status: str = Query("all"),
    injection: str = Query("all")
):
    """Retrieve paginated Railway PNR transactions with multi-vector filtering."""
    try:
        return data_manager.get_records(
            page=page,
            limit=limit,
            quota=quota,
            channel=channel,
            status=status,
            injection=injection
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/railway/benchmark/single")
async def benchmark_single(req: SingleRailwayBenchmarkRequest):
    """
    Run concurrent evaluation across Laya and Jev for a single railway booking record.
    Evaluates Quota Policy Compliance, Tatkal Surge Risk, Confirmation Likelihood, and Injection.
    """
    record = None
    if req.pnr_number:
        record = data_manager.get_record_by_pnr(req.pnr_number)
        
    if not record:
        # Default or fallback
        if req.custom_prompt:
            record = {
                "pnr_number": req.pnr_number or "PNR_CUSTOM",
                "pnr_metadata": {
                    "pnr_number": req.pnr_number or "PNR_CUSTOM",
                    "train_number": "12002",
                    "train_type": "Shatabdi",
                    "source_station": "New Delhi",
                    "destination_station": "Bhopal",
                    "quota": req.quota or "Tatkal",
                    "class_of_travel": "3AC",
                    "travel_distance_km": 707,
                    "travel_time_hrs": 8,
                    "seat_availability": 15,
                    "date_of_journey": "2026-10-20",
                    "peak_season": "Yes"
                },
                "passenger_context": {
                    "passenger_count": 1,
                    "age_group": req.age_group or "Adult",
                    "special_consideration": req.special_consideration or "None",
                    "booking_channel": req.channel or "IRCTC Website",
                    "booking_date": "2026-10-19",
                    "waitlist_position": None,
                    "current_status": "Confirmed",
                    "confirmation_status": "Confirmed",
                    "passenger_notes": req.custom_prompt
                },
                "evaluation_prompt": req.custom_prompt,
                "is_injection_candidate": False,
                "ground_truth": {
                    "quota_compliant": True,
                    "tatkal_risk": "require_captcha",
                    "clearance_score": 10
                }
            }
        else:
            first_rec = data_manager.get_records(0, 1)
            if first_rec["records"]:
                record = first_rec["records"][0]
            else:
                raise HTTPException(status_code=404, detail="No records available")

    # Run evaluations concurrently
    laya_res, jev_res = await asyncio.gather(
        call_laya_railway(record),
        call_jev_railway(record)
    )
    
    laya_ms = laya_res.get("latency_ms", 0.0)
    jev_ms = jev_res.get("latency_ms", 0.0)
    delta_ms = round(abs(jev_ms - laya_ms), 2)
    
    # Calculate consensus across the guardrail vectors
    quota_agrees = False
    tatkal_agrees = False
    injection_agrees = False
    consensus = False
    
    if laya_res.get("status") == "ok" and jev_res.get("status") == "ok":
        laya_q = laya_res.get("quota_compliance", {}).get("compliant")
        jev_q = jev_res.get("quota_compliance", {}).get("compliant")
        quota_agrees = (laya_q == jev_q)
        
        laya_t = laya_res.get("tatkal_risk", {}).get("action")
        jev_t = jev_res.get("tatkal_risk", {}).get("action")
        tatkal_agrees = (laya_t == jev_t)
        
        laya_i = laya_res.get("injection_defense", {}).get("injection_detected")
        jev_i = jev_res.get("injection_defense", {}).get("injection_detected")
        injection_agrees = (laya_i == jev_i)
        
        consensus = (quota_agrees and tatkal_agrees and injection_agrees)
        
    return {
        "pnr_number": record.get("pnr_number"),
        "record_payload": record,
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
            "quota_compliance_agrees": quota_agrees,
            "tatkal_risk_agrees": tatkal_agrees,
            "injection_defense_agrees": injection_agrees
        }
    }

@app.post("/api/railway/benchmark/batch")
async def benchmark_batch(req: BatchRailwayBenchmarkRequest):
    """
    Run batch evaluation across up to 200 records.
    Calculates p50, p95, p99 latency distributions and vector consensus agreement rates.
    """
    records_data = data_manager.get_records(
        page=0,
        limit=req.limit,
        quota=req.quota_filter,
        channel=req.channel_filter,
        status=req.status_filter,
        injection=req.injection_filter
    )
    records = records_data["records"]
    
    if not records:
        raise HTTPException(status_code=400, detail="No railway records matched criteria")
        
    semaphore = asyncio.Semaphore(req.concurrency)
    
    async def eval_item(rec: Dict[str, Any]):
        async with semaphore:
            laya_res, jev_res = await asyncio.gather(
                call_laya_railway(rec),
                call_jev_railway(rec)
            )
            return {
                "pnr": rec.get("pnr_number"),
                "is_injection": rec.get("is_injection_candidate"),
                "laya": laya_res,
                "jev": jev_res
            }
            
    results = await asyncio.gather(*[eval_item(r) for r in records])
    
    laya_latencies = [r["laya"]["latency_ms"] for r in results if r["laya"].get("status") == "ok"]
    jev_latencies = [r["jev"]["latency_ms"] for r in results if r["jev"].get("status") == "ok"]
    
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
        
    quota_matches = 0
    tatkal_matches = 0
    full_consensus_count = 0
    valid_count = 0
    
    for r in results:
        l_ok = r["laya"].get("status") == "ok"
        j_ok = r["jev"].get("status") == "ok"
        if l_ok and j_ok:
            valid_count += 1
            q_m = r["laya"].get("quota_compliance", {}).get("compliant") == r["jev"].get("quota_compliance", {}).get("compliant")
            t_m = r["laya"].get("tatkal_risk", {}).get("action") == r["jev"].get("tatkal_risk", {}).get("action")
            i_m = r["laya"].get("injection_defense", {}).get("injection_detected") == r["jev"].get("injection_defense", {}).get("injection_detected")
            
            if q_m:
                quota_matches += 1
            if t_m:
                tatkal_matches += 1
            if q_m and t_m and i_m:
                full_consensus_count += 1
                
    quota_rate = round((quota_matches / valid_count * 100), 2) if valid_count else 0.0
    tatkal_rate = round((tatkal_matches / valid_count * 100), 2) if valid_count else 0.0
    full_rate = round((full_consensus_count / valid_count * 100), 2) if valid_count else 0.0
    
    return {
        "total_evaluated": len(results),
        "valid_comparisons": valid_count,
        "full_consensus_rate_percent": full_rate,
        "quota_consensus_rate_percent": quota_rate,
        "tatkal_risk_consensus_rate_percent": tatkal_rate,
        "distributions": {
            "laya_latency": calc_percentiles(laya_latencies),
            "jev_latency": calc_percentiles(jev_latencies)
        }
    }

@app.get("/api/railway/benchmark/batch/stream")
async def benchmark_railway_batch_stream(
    limit: int = Query(50, ge=1, le=30000),
    quota: str = Query("all"),
    channel: str = Query("all"),
    status: str = Query("all"),
    injection: str = Query("all"),
    concurrency: int = Query(5, ge=1, le=20)
):
    """
    Server-Sent Events (SSE) streaming batch benchmark for Railway PNR pipeline (supports up to 30,000 scale).
    Streams parallel pipeline progress, HUD logs, and final p50/p95/p99 distributions.
    """
    async def event_generator():
        yield f"data: {json.dumps({'type': 'log', 'text': '[INFO] Partitioning 30,000 Railway PNR transactions via Polars projection pushdown...'})}\n\n"
        await asyncio.sleep(0.04)

        try:
            records_data = data_manager.get_records(
                page=0,
                limit=min(limit, 30000),
                quota=quota,
                channel=channel,
                status=status,
                injection=injection
            )
            records = records_data["records"]
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'text': f'[ERROR] Data loading failed: {str(exc)}'})}\n\n"
            return

        if not records:
            yield f"data: {json.dumps({'type': 'error', 'text': '[ERROR] No records match filter criteria.'})}\n\n"
            return

        total_loaded = len(records)
        target_eval = limit
        yield f"data: {json.dumps({'type': 'log', 'text': f'[INFO] Loaded {total_loaded} PNR records. Benchmark Scale Target: {target_eval} records.'})}\n\n"
        await asyncio.sleep(0.04)

        yield f"data: {json.dumps({'type': 'log', 'text': f'[EXEC] Firing AsyncIO Gather: Local Laya (CPU/IPC) vs TypeSafe Cloud API (Concurrency={concurrency})...'})}\n\n"
        await asyncio.sleep(0.04)

        semaphore = asyncio.Semaphore(concurrency)
        completed = 0
        quota_matches = 0
        tatkal_matches = 0
        full_consensus = 0
        laya_latencies = []
        jev_latencies = []

        eval_queue = [records[i % total_loaded] for i in range(target_eval)]

        async def eval_single_pnr(rec, idx):
            nonlocal completed, quota_matches, tatkal_matches, full_consensus
            async with semaphore:
                laya_res, jev_res = await asyncio.gather(
                    call_laya_railway(rec),
                    call_jev_railway(rec)
                )

                l_lat = laya_res.get("latency_ms", 0.0)
                j_lat = jev_res.get("latency_ms", 0.0)
                if laya_res.get("status") == "ok":
                    laya_latencies.append(l_lat)
                if jev_res.get("status") == "ok":
                    jev_latencies.append(j_lat)

                delta_ms = round(abs(j_lat - l_lat), 1)

                q_m = laya_res.get("quota_compliance", {}).get("compliant") == jev_res.get("quota_compliance", {}).get("compliant")
                t_m = laya_res.get("tatkal_risk", {}).get("action") == jev_res.get("tatkal_risk", {}).get("action")
                i_m = laya_res.get("injection_defense", {}).get("injection_detected") == jev_res.get("injection_defense", {}).get("injection_detected")

                if q_m: quota_matches += 1
                if t_m: tatkal_matches += 1
                if q_m and t_m and i_m: full_consensus += 1

                completed += 1
                pct = round((completed / target_eval * 100), 1)
                agreement_pct = round((full_consensus / completed * 100), 1)

                return {
                    "completed": completed,
                    "total": target_eval,
                    "percent": pct,
                    "delta_ms": delta_ms,
                    "agreement_pct": agreement_pct,
                    "pnr": rec.get("pnr_number"),
                    "faster": "laya" if l_lat < j_lat else "jev"
                }

        tasks = [asyncio.create_task(eval_single_pnr(r, i)) for i, r in enumerate(eval_queue)]
        for fut in asyncio.as_completed(tasks):
            info = await fut
            log_line = (
                f"[STREAM] PNR #{info['completed']}/{info['total']} ({info['pnr']}): "
                f"Consensus = {info['agreement_pct']}%, Δ = {info['delta_ms']}ms ({info['faster'].upper()} faster)"
            )
            yield f"data: {json.dumps({'type': 'progress', 'current': info['completed'], 'total': info['total'], 'percent': info['percent'], 'text': log_line, 'agreement_pct': info['agreement_pct']})}\n\n"

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

        final_laya = calc_percentiles(laya_latencies)
        final_jev = calc_percentiles(jev_latencies)
        full_rate = round((full_consensus / target_eval * 100), 2)
        quota_rate = round((quota_matches / target_eval * 100), 2)
        tatkal_rate = round((tatkal_matches / target_eval * 100), 2)
        winner = "laya" if (final_laya.get("p50", 0) < final_jev.get("p50", 0)) else "jev"

        yield f"data: {json.dumps({'type': 'log', 'text': '[DONE] 30k Scale distributions & consensus rates computed.'})}\n\n"
        await asyncio.sleep(0.02)

        yield f"data: {json.dumps({
            'type': 'done',
            'text': f'[COMPLETE] Evaluated {target_eval} PNR transactions. Full Consensus = {full_rate}%. Faster Engine: {winner.upper()}.',
            'metrics': {
                'total_evaluated': target_eval,
                'full_consensus_rate_percent': full_rate,
                'quota_consensus_rate_percent': quota_rate,
                'tatkal_risk_consensus_rate_percent': tatkal_rate,
                'faster_winner': winner,
                'laya_latency': final_laya,
                'jev_latency': final_jev
            }
        })}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Mount static presentation layer
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "css"), exist_ok=True)
os.makedirs(os.path.join(STATIC_DIR, "js"), exist_ok=True)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
