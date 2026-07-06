# ARTEMIS — MT5 Live Monitor Dashboard
**Status:** Approved ✓  
**Last updated:** 2026-07-06

---

## Overview

A Bloomberg-style web dashboard that connects directly to the running MT5 terminal (`terminal64.exe`, PID 16296) via the MetaTrader5 Python API. Displays live account state, open positions, pending orders, today's deal history, equity curve, and EA journal — auto-refreshing every 3 seconds.

---

## Confirmed Context

| Item | Value |
|---|---|
| Active EA | The Gold Reaper MT5 4.3 on `GOLD.i#` |
| Account | `430380523` on `XMGlobal-MT5 18` |
| Terminal dir | `D0E8209F77C8CF37AD8BF550E51FF075` |
| MT5 Python API | `MetaTrader5==5.0.5735` ✓ installed |
| FastAPI / uvicorn | ✓ installed |

---

## Architecture

```
MT5 terminal (terminal64.exe running on host)
        ↓  Windows named pipe
  MetaTrader5 Python API
        ↓
  FastAPI + uvicorn  →  http://localhost:8000
        ↓  JSON  (polling every 3s via setInterval)
  Browser dashboard (single HTML page, served by FastAPI)
```

---

## API Endpoints

| Endpoint | Returns |
|---|---|
| `GET /` | Serves `index.html` |
| `GET /api/account` | Balance, equity, margin, free margin, profit, currency, leverage |
| `GET /api/positions` | All open positions (ticket, symbol, type, lots, entry, current, SL, TP, P&L) |
| `GET /api/orders` | All pending orders (ticket, symbol, type, lots, price, SL, TP) |
| `GET /api/history` | Today's closed deals (time, ticket, symbol, type, lots, price, profit) |
| `GET /api/log` | Last 50 lines from today's MT5 log file (UTF-16 decoded, cleaned) |

---

## Dashboard Panels

| Panel | Location | Data source |
|---|---|---|
| **Top bar** | Full width, pinned top | `/api/account` — balance, equity, free margin, UTC clock, MT5 connection dot |
| **Account KPIs** | Row of 4 stat cards | balance, equity, margin used%, today's P&L |
| **Open Positions** | Left column, top | `/api/positions` — live table with colored P&L |
| **Pending Orders** | Left column, bottom | `/api/orders` — table |
| **Equity Curve** | Right column, top | `/api/history` — Chart.js line chart built from cumulative deal profit |
| **Today's Deals** | Right column, middle | `/api/history` — scrollable table, newest first |
| **EA Journal** | Right column, bottom | `/api/log` — last 50 log lines, monospace, auto-scroll to bottom |

---

## Design System

- **Style**: Bloomberg Terminal — pure black `#000000`, panels `#0d0d0d` / `#141414`
- **Accent**: `#ff6600` orange — brand strip, section headers, key numbers
- **Font**: `IBM Plex Mono` (Google Fonts CDN) — everything monospace
- **Colors**: green `#00cc44` = BUY / profit, red `#ff2222` = SELL / loss, orange `#ffaa00` = pending
- **Density**: 12px base, 5px row padding, `1px solid #2a2a2a` borders, zero border-radius
- **Refresh**: `setInterval` every 3 seconds, no page reload, status dot flashes on each fetch

---

## File Layout

```
C:/Users/arief/Documents/projects/artemis-dashboard/
  PLAN.md              ← this file
  main.py              ← FastAPI app + MT5 data layer + log parser
  templates/
    index.html         ← Bloomberg dashboard (vanilla JS + Chart.js CDN)
  run.bat              ← double-click launcher (activates venv, starts uvicorn)
```

---

## Out of Scope (for now)

- No trade execution / order management from the dashboard (read-only)
- No multi-account view
- No historical equity beyond today's session
- No alerts / notifications

---

## Open Questions for Approval

1. Port `8000` OK, or do you want a different one?
2. Should the equity curve show **today only** or also pull from previous days' history?
3. Any extra panels you want (e.g. symbol tick price, spread, drawdown meter)?
