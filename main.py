"""
ARTEMIS — MT5 Live Monitor Dashboard
FastAPI backend, connects to running MT5 terminal via Python API
"""

import os
import re
import glob
import time
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import MetaTrader5 as mt5
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse

# ── paths ────────────────────────────────────────────────────────────────────
MT5_TERMINAL_ID = os.getenv("MT5_TERMINAL_ID", "")
MT5_LOG_DIR = Path(os.getenv(
    "MT5_LOG_DIR",
    str(Path.home() / "AppData/Roaming/MetaQuotes/Terminal" / MT5_TERMINAL_ID / "logs")
))
HTML_PATH = Path(__file__).parent / "templates" / "index.html"
PORT = int(os.getenv("PORT", "8100"))
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK", "")

# ── app ──────────────────────────────────────────────────────────────────────
app = FastAPI(title="ARTEMIS", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

# ── EA magic number → name map ───────────────────────────────────────────────
MAGIC_MAP = {
    8001:  "Gold Reaper",
    8002:  "Gold Reaper",
    8005:  "Gold Reaper",
    8008:  "Gold Reaper",
    8009:  "Gold Reaper",
    8012:  "Gold Reaper",
    8013:  "Gold Reaper",
    8014:  "Gold Reaper",
    8015:  "Gold Reaper",
    11001: "Ultimate Breakout",
    11002: "Ultimate Breakout",
    11003: "Ultimate Breakout",
    11004: "Ultimate Breakout",
    11005: "Ultimate Breakout",
    11006: "Ultimate Breakout",
}

def magic_to_ea(magic: int) -> str:
    return MAGIC_MAP.get(magic, f"EA#{magic}" if magic else "—")


# ── MT5 helpers ──────────────────────────────────────────────────────────────

_mt5_last_connected = 0.0
_MT5_RETRY_COOLDOWN = 5.0  # seconds between reconnect attempts

def mt5_connect() -> bool:
    """Initialize MT5 connection with retry logic."""
    global _mt5_last_connected
    if mt5.terminal_info() is not None:
        return True
    now = time.time()
    if now - _mt5_last_connected < _MT5_RETRY_COOLDOWN:
        return False
    _mt5_last_connected = now
    for attempt in range(3):
        if mt5.initialize():
            return True
        time.sleep(0.5)
    return False


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
        else:
            is_active = hour >= start or hour < end

        if is_active:
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

def read_today_log(lines: int = 50) -> list:
    today = datetime.now().strftime("%Y%m%d")
    log_path = MT5_LOG_DIR / f"{today}.log"
    if not log_path.exists():
        return ["[log file not found]"]
    try:
        raw = log_path.read_bytes()
        text = raw.decode("utf-16-le", errors="replace").replace("\x00", "")
        all_lines = [l.strip() for l in text.splitlines() if l.strip()]
        return all_lines[-lines:]
    except Exception as e:
        return [f"[log read error: {e}]"]


# ── history helper ────────────────────────────────────────────────────────────

def _fetch_deals(from_dt: datetime, to_dt: datetime) -> list:
    deals = mt5.history_deals_get(from_dt, to_dt)
    if deals is None:
        return []
    result = []
    cumulative = 0.0
    for d in sorted(deals, key=lambda x: x.time):
        cumulative += d.profit
        if d.entry == 0 and d.profit == 0.0:
            continue
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
            "date":       datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m-%d"),
            "magic":      d.magic,
            "ea":         magic_to_ea(d.magic),
            "comment":    d.comment,
        })
    return result


# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML_PATH.read_text(encoding="utf-8"))


@app.get("/api/status")
async def api_status():
    connected = mt5_connect()
    if not connected:
        return {"connected": False, "error": str(mt5.last_error())}
    info = mt5.terminal_info()
    return {
        "connected": True,
        "build": info.build if info else None,
        "connected_to_broker": info.connected if info else False,
    }


@app.get("/api/account")
async def api_account():
    if not mt5_connect():
        return {"error": "MT5 not connected", "connected": False}
    acc = mt5.account_info()
    if acc is None:
        return {"error": "Could not fetch account info", "connected": False}
    return {
        "login":        acc.login,
        "name":         acc.name,
        "server":       acc.server,
        "currency":     acc.currency,
        "leverage":     acc.leverage,
        "balance":      safe_float(acc.balance),
        "equity":       safe_float(acc.equity),
        "margin":       safe_float(acc.margin),
        "free_margin":  safe_float(acc.margin_free),
        "margin_level": safe_float(acc.margin_level),
        "profit":       safe_float(acc.profit),
        "margin_pct":   safe_float(
            (acc.margin / acc.equity * 100) if acc.equity else 0
        ),
        "connected": True,
    }


@app.get("/api/positions")
async def api_positions():
    if not mt5_connect():
        return []
    positions = mt5.positions_get()
    if positions is None:
        return []
    result = []
    for p in positions:
        result.append({
            "ticket":    p.ticket,
            "symbol":    p.symbol,
            "type":      "BUY" if p.type == 0 else "SELL",
            "lots":      safe_float(p.volume),
            "entry":     safe_float(p.price_open),
            "current":   safe_float(p.price_current),
            "sl":        safe_float(p.sl),
            "tp":        safe_float(p.tp),
            "profit":    safe_float(p.profit),
            "swap":      safe_float(p.swap),
            "open_time": datetime.fromtimestamp(p.time, tz=timezone.utc).strftime("%H:%M:%S"),
            "magic":     p.magic,
            "ea":        magic_to_ea(p.magic),
            "comment":   p.comment,
        })
    return result


@app.get("/api/orders")
async def api_orders():
    if not mt5_connect():
        return []
    orders = mt5.orders_get()
    if orders is None:
        return []
    TYPE_MAP = {
        0: "BUY", 1: "SELL",
        2: "BUY LIMIT", 3: "SELL LIMIT",
        4: "BUY STOP",  5: "SELL STOP",
        6: "BUY STOP LIMIT", 7: "SELL STOP LIMIT",
    }
    result = []
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
            "ea":         magic_to_ea(o.magic),
            "comment":    o.comment,
        })
    return result


@app.get("/api/history")
async def api_history(
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    to_date:   Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    if not mt5_connect():
        return []
    now_utc = datetime.now(timezone.utc)
    if from_date:
        try:
            from_dt = datetime.strptime(from_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(400, detail="Invalid from_date format, use YYYY-MM-DD")
    else:
        from_dt = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    if to_date:
        try:
            to_dt = datetime.strptime(to_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            raise HTTPException(400, detail="Invalid to_date format, use YYYY-MM-DD")
    else:
        to_dt = from_dt + timedelta(days=1)

    return _fetch_deals(from_dt, to_dt)


@app.get("/api/balance_history")
async def api_balance_history(days: int = Query(7, ge=1, le=90)):
    if not mt5_connect():
        return []
    now_utc = datetime.now(timezone.utc)
    from_dt = (now_utc - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt   = now_utc + timedelta(days=1)
    deals   = mt5.history_deals_get(from_dt, to_dt)
    if not deals:
        return []

    # get starting balance (account balance minus all profits in range)
    acc = mt5.account_info()
    total_profit = sum(d.profit + d.commission + d.swap for d in deals)
    start_balance = safe_float((acc.balance if acc else 0) - total_profit)

    # build daily closing balance
    daily = {}
    running = start_balance
    for d in sorted(deals, key=lambda x: x.time):
        running += d.profit + d.commission + d.swap
        day = datetime.fromtimestamp(d.time, tz=timezone.utc).strftime("%Y-%m-%d")
        daily[day] = safe_float(running)

    # fill gaps with previous value
    result = []
    prev = start_balance
    for i in range(days):
        day = (from_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        val = daily.get(day, prev)
        prev = val
        result.append({"date": day, "balance": val})
    return result


@app.get("/api/symbols")
async def api_symbols():
    if not mt5_connect():
        return []
    symbols = set()
    positions = mt5.positions_get()
    if positions:
        for p in positions:
            symbols.add(p.symbol)
    orders = mt5.orders_get()
    if orders:
        for o in orders:
            symbols.add(o.symbol)
    return sorted(symbols)


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


@app.post("/api/alert")
async def api_alert(payload: dict):
    """Send an alert to Discord via webhook or Hermes send_message."""
    msg = payload.get("message", "ARTEMIS ALERT")
    if DISCORD_WEBHOOK:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(DISCORD_WEBHOOK, json={"content": f"🚨 **ARTEMIS ALERT**\n{msg}"})
            return {"sent": True, "via": "webhook"}
        except Exception as e:
            return {"sent": False, "error": str(e)}
    return {"sent": False, "error": "DISCORD_WEBHOOK not configured"}


# ── entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)
