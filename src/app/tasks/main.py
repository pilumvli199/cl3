import os, time, asyncio, json
from fastapi import FastAPI
from dotenv import load_dotenv

from ..api_clients import binance_client
from ..datastore import redis_store as ds
from ..processors import rule_engine
from ..ai import gpt_handler
from ..alerts import telegram as telegram_module

from fastapi.responses import JSONResponse
import json as _json

load_dotenv()

FETCH_INTERVAL = int(os.getenv("FETCH_INTERVAL_SECONDS", 1800))
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

app = FastAPI(title="Crypto Signal Bot")

_baseline_oi = {}


def update_baseline_if_missing(symbol: str, current_oi: float):
    if symbol not in _baseline_oi or _baseline_oi.get(symbol) == 0:
        _baseline_oi[symbol] = current_oi


async def worker_loop():
    print("Starting scheduler loop (background worker)")
    while True:
        try:
            data = binance_client.fetch_all()
            now = int(time.time())

            for sym, snap in data.items():
                if snap.get("error"):
                    print(f"[{sym}] fetch error: {snap.get('error')}")
                    continue

                ticker = snap.get("ticker", {})
                oi = snap.get("open_interest", {})

                try:
                    current_oi = float(oi.get("openInterest") or 0.0)
                except Exception:
                    current_oi = 0.0

                # Save snapshot
                ds.push_snapshot(sym, {"ticker": ticker, "open_interest": oi, "ts": now})

                # Baseline OI
                if sym not in _baseline_oi:
                    prev = ds.get_latest_snapshot(sym)
                    prev_oi = 0.0
                    try:
                        prev_oi = float(prev.get("open_interest", {}).get("openInterest") or 0.0)
                    except Exception:
                        prev_oi = 0.0
                    update_baseline_if_missing(sym, prev_oi or current_oi)

                baseline = _baseline_oi.get(sym, current_oi)

                # Evaluate candidate
                candidate = rule_engine.evaluate_crypto(
                    {"ticker": ticker, "open_interest": oi, "ts": now},
                    baseline_oi=baseline,
                )
                _baseline_oi[sym] = current_oi

                res = gpt_handler.handle_candidate(candidate, {"recent_baseline_oi": baseline})
                print(f"[{sym}] -> candidate {candidate.get('side')} | sent={res.get('result', {}).get('sent')}")

            await asyncio.sleep(FETCH_INTERVAL)

        except Exception as e:
            print("worker_loop error:", str(e))
            await asyncio.sleep(5)


@app.on_event("startup")
async def startup_event():
    # Bot online झाल्यावर Telegram ला notify करणे
    try:
        telegram_module.send_text("🚀 Bot is online and running!")
    except Exception as e:
        print("Telegram startup alert failed:", str(e))

    loop = asyncio.get_event_loop()
    loop.create_task(worker_loop())


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/signals")
async def get_recent_signals(limit: int = 50):
    try:
        raw = ds.r.lrange("signals:all", 0, limit - 1)
        parsed = []
        for item in raw:
            try:
                parsed.append(_json.loads(item))
            except Exception:
                parsed.append({"raw": item})
        return JSONResponse(content={"count": len(parsed), "signals": parsed})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/test-telegram")
async def test_telegram():
    """Send a quick test message to Telegram via configured bot/token."""
    try:
        ok = telegram_module.send_text("🚀 Test alert from Railway bot")
        return {"sent": ok}
    except Exception as e:
        return {"sent": False, "error": str(e)}


@app.get("/redis-health")
async def redis_health():
    """Check Redis connectivity and keys count."""
    try:
        pong = ds.r.ping()
        keys = ds.r.keys("*")
        return {
            "redis_ping": pong,
            "keys_count": len(keys),
            "keys_sample": [k.decode("utf-8") if isinstance(k, bytes) else str(k) for k in keys[:10]]
        }
    except Exception as e:
        return {"error": str(e)}
