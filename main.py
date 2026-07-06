"""
ARTEMIS — MT5 Live Monitor Dashboard
FastAPI backend, connects to running MT5 terminal via Python API
"""

import os
import re
import glob
from datetime import datetime, timezone, timedelta
from pathlib import Path

import MetaTrader5 as mt5
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from starlette.responses import JSONResponse

# ── paths ────────────────────────────────────────────────────────────────────
MT5_TERMINAL_ID = os.getenv("MT5_TERMINAL_ID", "")
MT5_LOG_DIR = Path(os.getenv(
    "MT5_LOG_DIR",
    str(Path.home() / "AppData/Roaming/MetaQuotes/Terminal" / MT5_TERMINAL_ID / "logs")
))
HTML_PATH = Path(__file__).parent / "templates" / "index.html"
PORT = int(os.getenv("PORT", "8100"))

# ── app ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="ARTEMIS", docs_url=None, redoc_url=None)


# ── MT5 helpers ──────────────────────────────────────────────────────────────

def mt5_connect() -> bool:
    """Initialize MT5 connection if not already connected."""
    if mt5.terminal_info() is not None:
        return True
    return mt5.initialize()


def safe_float(val) -> float:
    try:
        return round(float(val), 2)
    except Exception:
        return 0.0


# ── trading session helper ────────────────────────────────────────────────────

SESSIONS = [
    {"name": "Sydney",   "start": 21, "end": 6},
    {"name": "Tokyo",    "start": 0,  "end": 9},
    {"name": "London",   "start": 7,  "end": 16},
    {"name": "New York", "start": 12, "end": 21},
]


def get_session_info() -> dict:
    now_utc = datetime.now(timezone.utc)
    hour = now_utc.hour
    active = []
    upcoming = None

    for s in SESSIONS:
        start, end = s["start"], s["end"]
        if start < end:
            is_active = start <= hour < end
        else:  # wraps midnight
            is_active = hour >= start or hour < end

        if is_active:
            # minutes remaining
            if start < end:
                close_today = now_utc.replace(hour=end, minute=0, second=0, microsecond=0)
            else:
                if hour >= start:
                    close_today = (now_utc + timedelta(days=1)).replace(
                        hour=end, minute=0, second=0, microsecond=0
                    )
                else:
                    close_today = now_utc.replace(hour=end, minute=0, second=0, microsecond=0)
            mins_left = int((close_today - now_utc).total_seconds() / 60)
            active.append({"name": s["name"], "mins_left": mins_left})

        else:
            # find next open
            if start < end:
                open_time = now_utc.replace(hour=start, minute=0, second=0, microsecond=0)
                if open_time <= now_utc:
                    open_time += timedelta(days=1)
            else:
                open_time = now_utc.replace(hour=start, minute=0, second=0, microsecond=0)
                if open_time <= now_utc:
                    open_time += timedelta(days=1)
            mins_until = int((open_time - now_utc).total_seconds() / 60)
            if upcoming is None or mins_until < upcoming["mins_until"]:
                upcoming = {"name": s["name"], "mins_until": mins_until}

    return {"active": active, "upcoming": upcoming, "utc_hour": hour}


# ── log parser ────────────────────────────────────────────────────────────────

def read_today_log(lines: int = 50) -> list[str]:
    today = datetime.now().strftime("%Y%m%d")
    log_path = MT5_LOG_DIR / f"{today}.log"
    if not log_path.exists():
        return ["[log file not found]"]
    try:
        raw = log_path.read_bytes()
        # MT5 logs are UTF-16 LE
        text = raw.decode("utf-16-le", errors="replace")
        # strip null bytes and clean
        text = text.replace("\x00", "")
        all_lines = [l.strip() for l in text.splitlines() if l.strip()]
        return all_lines[-lines:]
    except Exception as e:
        return [f"[log read error: {e}]"]


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML_PATH.read_text(encoding="utf-8"))


@app.get("/api/status")
async def api_status():
    connected = mt5_connect()
    if not connected:
        return {"connected": False, "error": mt5.last_error()}
    info = mt5.terminal_info()
    return {
        "connected": True,
        "build": info.build if info else None,
        "connected_to_broker": info.connected if info else False,
    }


@app.get("/api/account")
async def api_account():
    if not mt5_connect():
        raise HTTPException(503, detail="MT5 not connected")
    acc = mt5.account_info()
    if acc is None:
        raise HTTPException(503, detail="Could not fetch account info")
    return {
        "login":       acc.login,
        "name":        acc.name,
        "server":      acc.server,
        "currency":    acc.currency,
        "leverage":    acc.leverage,
        "balance":     safe_float(acc.balance),
        "equity":      safe_float(acc.equity),
        "margin":      safe_float(acc.margin),
        "free_margin": safe_float(acc.margin_free),
        "margin_level": safe_float(acc.margin_level),
        "profit":      safe_float(acc.profit),
        "margin_pct":  safe_float(
            (acc.margin / acc.equity * 100) if acc.equity else 0
        ),
    }


@app.get("/api/positions")
async def api_positions():
    if not mt5_connect():
        raise HTTPException(503, detail="MT5 not connected")
    positions = mt5.positions_get()
    if positions is None:
        return []
    result = []
    for p in positions:
        result.append({
            "ticket":     p.ticket,
            "symbol":     p.symbol,
            "type":       "BUY" if p.type == 0 else "SELL",
            "lots":       safe_float(p.volume),
            "entry":      safe_float(p.price_open),
            "current":    safe_float(p.price_current),
            "sl":         safe_float(p.sl),
            "tp":         safe_float(p.tp),
            "profit":     safe_float(p.profit),
            "swap":       safe_float(p.swap),
            "open_time":  datetime.fromtimestamp(p.time, tz=timezone.utc).strftime("%H:%M:%S"),
            "magic":      p.magic,
            "comment":    p.comment,
        })
    return result


@app.get("/api/orders")
async def api_orders():
    if not mt5_connect():
        raise HTTPException(503, detail="MT5 not connected")
    orders = mt5.orders_get()
    if orders is None:
        return []
    result = []
    TYPE_MAP = {
        0: "BUY", 1: "SELL",
        2: "BUY LIMIT", 3: "SELL LIMIT",
        4: "BUY STOP", 5: "SELL STOP",
        6: "BUY STOP LIMIT", 7: "SELL STOP LIMIT",
    }
    for o in orders:
        result.append({
            "ticket":     o.ticket,
            "symbol":     o.symbol,
            "type":       TYPE_MAP.get(o.type, str(o.type)),
            "lots":       safe_float(o.volume_current),
            "price":      safe_float(o.price_open),
            "sl":         safe_float(o.sl),
            "tp":         safe_float(o.tp),
            "placed_time": datetime.fromtimestamp(o.time_setup, tz=timezone.utc).strftime("%H:%M:%S"),
            "magic":      o.magic,
            "comment":    o.comment,
        })
    return result


@app.get("/api/history")
async def api_history():
    if not mt5_connect():
        raise HTTPException(503, detail="MT5 not connected")
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    deals = mt5.history_deals_get(today, tomorrow)
    if deals is None:
        return []
    result = []
    cumulative = 0.0
    for d in sorted(deals, key=lambda x: x.time):
        cumulative += d.profit
        result.append({
            "ticket":     d.ticket,
            "order":      d.order,
            "symbol":     d.symbol,
            "type":       "BUY" if d.type == 0 else "SELL" if d.type == 1 else "BALANCE",
            "lots":       safe_float(d.volume),
            "price":      safe_float(d.price),
            "profit":     safe_float(d.profit),
            "commission": safe_float(d.commission),
            "swap":       safe_float(d.swap),
            "cumulative": safe_float(cumulative),
            "time":       datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%H:%M:%S"),
            "comment":    d.comment,
        })
    return result


@app.get("/api/tick")
async def api_tick(symbol: str = "GOLD.i#"):
    if not mt5_connect():
        raise HTTPException(503, detail="MT5 not connected")
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    if tick is None:
        raise HTTPException(404, detail=f"Symbol {symbol} not found")
    spread_pts = tick.ask - tick.bid
    point = info.point if info else 0.01
    spread_pips = round(spread_pts / point, 1) if point else 0
    return {
        "symbol":      symbol,
        "bid":         safe_float(tick.bid),
        "ask":         safe_float(tick.ask),
        "spread":      safe_float(spread_pts),
        "spread_pips": spread_pips,
        "time":        datetime.fromtimestamp(tick.time, tz=timezone.utc).strftime("%H:%M:%S"),
    }


@app.get("/api/log")
async def api_log(lines: int = 50):
    return read_today_log(lines)


@app.get("/api/session")
async def api_session():
    return get_session_info()


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
