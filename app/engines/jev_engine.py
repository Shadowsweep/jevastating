"""
TypeSafe AI (Jev) Engine Adapter for Railway Guardrails.
Dispatches asynchronous System-1 evaluations to https://api.typesafe.ai/v1/systemone.
Evaluates Quota Policy Compliance (noul), Tatkal Risk (choice), Confirmation Likelihood (score), and Injection Defense (noul).
"""
import time
import httpx
from typing import Dict, Any
from app.config import settings

async def call_jev_railway(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Call TypeSafe Jev AI API with internal API token."""
    start_time = time.perf_counter()
    
    if not settings.TYPESAFE_API_KEY or settings.TYPESAFE_API_KEY.startswith("your-"):
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "status": "error",
            "engine": "jev",
            "model": "jev-latest",
            "latency_ms": latency_ms,
            "error": "TYPESAFE_API_KEY not configured or placeholder"
        }
        
    prompt_text = payload.get("evaluation_prompt", "")
    
    headers = {
        "Authorization": f"Bearer {settings.TYPESAFE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    jev_request = {
        "model": "jev-latest",
        "state": prompt_text,
        "questions": {
            "quota_compliance": {
                "type": "noul",
                "instructions": "Does the passenger demographic (Age/Special Consideration) legally satisfy the reservation Quota (e.g. Ladies or Senior Citizen quota eligibility)?"
            },
            "tatkal_risk": {
                "type": "choice",
                "instructions": "Detect bot-driven automated Tatkal booking attempts based on booking channel, timing, and seat velocity.",
                "criteria": {
                    "allow_instant": "Normal low-risk booking channel or standard seat velocity",
                    "require_captcha": "Elevated Tatkal velocity requiring bot-challenge captcha verification",
                    "throttle_rate_limit": "High-velocity surge attempting to rapidly deplete remaining seats",
                    "block_suspicious": "Anomalous channel activity, script injection, or fraudulent booking pattern"
                }
            },
            "confirmation_predictability": {
                "type": "score",
                "instructions": "Rate waitlist confirmation likelihood on a scale from 1 (unlikely) to 10 (guaranteed clearance).",
                "criteria": [
                    "WL > 50 in peak season: extremely low clearance chance",
                    "WL 25-50: low clearance chance",
                    "WL 10-25: moderate clearance chance",
                    "WL 1-10 or RAC: high clearance chance",
                    "Confirmed ticket: 100% clearance guaranteed"
                ]
            },
            "injection_defense": {
                "type": "noul",
                "instructions": "Does the transaction metadata contain SQL or Prompt injection strings in Station or Passenger override fields?"
            }
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                settings.TYPESAFE_API_URL,
                json=jev_request,
                headers=headers
            )
            raw_latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            
            if resp.status_code == 200:
                data = resp.json()
                model_name = data.get("model", "jev-latest")
                answers = data.get("answers", data.get("results", {}))
                
                # 1. Quota Compliance (Noul)
                q_ans = answers.get("quota_compliance", {})
                q_noul = q_ans.get("noul", q_ans.get("probability", 0.95))
                is_quota_comp = float(q_noul) >= 0.5
                
                # 2. Tatkal Risk (Choice)
                t_ans = answers.get("tatkal_risk", {})
                chosen_risk = t_ans.get("choice", "allow_instant")
                risk_conf = float(t_ans.get("confidence", 0.90))
                risk_probs = t_ans.get("probabilities", {})
                
                # 3. Confirmation Predictability (Score)
                c_ans = answers.get("confirmation_predictability", {})
                score_val = c_ans.get("score", 8.0)
                if isinstance(score_val, (int, float)):
                    # Scale to 1-10 if normalized 0-1
                    pred_score = round(float(score_val) * 10, 1) if float(score_val) <= 1.0 else round(float(score_val), 1)
                else:
                    pred_score = 7.5
                    
                # 4. Injection Defense (Noul)
                inj_ans = answers.get("injection_defense", {})
                inj_noul = inj_ans.get("noul", inj_ans.get("probability", 0.0))
                is_injection = float(inj_noul) >= 0.5
                
                return {
                    "status": "ok",
                    "engine": "jev",
                    "model": model_name,
                    "latency_ms": raw_latency_ms,
                    "usage": data.get("usage", {}),
                    "quota_compliance": {
                        "compliant": is_quota_comp,
                        "probability": round(float(q_noul), 4)
                    },
                    "injection_defense": {
                        "injection_detected": is_injection,
                        "probability": round(float(inj_noul), 4)
                    },
                    "tatkal_risk": {
                        "action": chosen_risk,
                        "confidence": round(risk_conf, 4),
                        "probabilities": risk_probs
                    },
                    "confirmation_predictability": {
                        "score": pred_score,
                        "scale": "1-10"
                    }
                }
            else:
                return {
                    "status": "error",
                    "engine": "jev",
                    "model": "jev-latest",
                    "latency_ms": raw_latency_ms,
                    "http_status": resp.status_code,
                    "error": f"TypeSafe API error: {resp.text[:300]}"
                }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return {
            "status": "error",
            "engine": "jev",
            "model": "jev-latest",
            "latency_ms": latency_ms,
            "error": str(exc)
        }
