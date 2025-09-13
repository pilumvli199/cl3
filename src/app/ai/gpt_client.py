import os
import time
from typing import Dict, Any
try:
    import openai
except Exception:
    openai = None
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
if OPENAI_API_KEY and openai is not None:
    openai.api_key = OPENAI_API_KEY
def build_prompt(signal_candidate: Dict[str, Any], recent_aggregates: Dict[str, Any]) -> str:
    return (
        "You are a concise trading assistant. Given the candidate and recent aggregates, "
        "answer in JSON like: {"symbol":"","side":"BUY|SELL|HOLD","confidence":0-100,"reasoning":"..."}.

"
        f"Candidate: {signal_candidate}\n\nAggregates: {recent_aggregates}\n\n"
        "Return only valid JSON with keys: symbol, side, confidence, reasoning."
    )
def call_model(signal_candidate: Dict[str, Any], recent_aggregates: Dict[str, Any], max_tokens: int = 150) -> Dict[str, Any]:
    if not OPENAI_API_KEY or openai is None:
        return {
            "symbol": signal_candidate.get("symbol"),
            "side": signal_candidate.get("side"),
            "confidence": int(signal_candidate.get("confidence", 0) or 0),
            "reasoning": signal_candidate.get("reasoning", "")
        }
    prompt = build_prompt(signal_candidate, recent_aggregates)
    try:
        resp = openai.ChatCompletion.create(
            model=OPENAI_MODEL,
            messages=[{"role":"system","content":"You are a concise trading assistant."},
                      {"role":"user","content":prompt}],
            max_tokens=max_tokens,
            temperature=0.0
        )
        text = resp["choices"][0]["message"]["content"]
    except Exception as e:
        return {
            "symbol": signal_candidate.get("symbol"),
            "side": signal_candidate.get("side"),
            "confidence": int(signal_candidate.get("confidence", 0) or 0),
            "reasoning": f"{signal_candidate.get('reasoning','')} (model_error: {e})"
        }
    try:
        import json
        parsed = json.loads(text)
        parsed_result = {
            "symbol": parsed.get("symbol", signal_candidate.get("symbol")),
            "side": (parsed.get("side") or signal_candidate.get("side") or "HOLD"),
            "confidence": int(round(float(parsed.get("confidence", signal_candidate.get("confidence", 0) or 0)))),
            "reasoning": parsed.get("reasoning", "")[:1000]
        }
        parsed_result["confidence"] = max(0, min(100, parsed_result["confidence"]))
        return parsed_result
    except Exception:
        return {
            "symbol": signal_candidate.get("symbol"),
            "side": signal_candidate.get("side"),
            "confidence": int(signal_candidate.get("confidence", 0) or 0),
            "reasoning": f"{signal_candidate.get('reasoning','')} (model-unparseable)"
        }
