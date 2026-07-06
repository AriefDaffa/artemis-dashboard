# ARTEMIS — MT5 Live Monitor Dashboard

A Bloomberg-style web dashboard for monitoring a live MetaTrader 5 terminal and Expert Advisor in real time.

![Dashboard](https://img.shields.io/badge/stack-FastAPI%20%2B%20Vanilla%20JS-ff6600?style=flat-square)
![Python](https://img.shields.io/badge/python-3.11-blue?style=flat-square)
![MT5](https://img.shields.io/badge/MT5-5.0.5735-green?style=flat-square)

---

## Features

- **Live account stats** — balance, equity, free margin, margin level
- **Open positions** — real-time P&L, entry/current price, SL/TP
- **Pending orders** — all order types (buy/sell stop, limit)
- **Today's deals** — full closed trade history with cumulative P&L
- **Equity curve** — Chart.js line chart built from today's closed deals
- **Win rate strip** — trades, wins, losses, win%, avg win/loss, profit factor
- **Drawdown meter** — color-coded max drawdown bar (green → yellow → red)
- **Live tick** — real-time bid/ask/spread for any symbol
- **Session clock** — active trading sessions (Sydney/Tokyo/London/New York) with time remaining
- **EA journal** — last 50 lines from the MT5 daily log, color-coded by type
- **Auto-refresh** every 3 seconds, no page reload
- **Responsive** — works on desktop and mobile

---

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + uvicorn |
| MT5 data | `MetaTrader5` Python API (Windows named pipe) |
| Frontend | Vanilla JS + Chart.js CDN |
| Design | Bloomberg terminal style — IBM Plex Mono, pure black, `#ff6600` orange |

---

## Requirements

- Windows (MT5 Python API is Windows-only)
- MetaTrader 5 terminal running
- Python 3.11+

---

## Setup

**1. Clone the repo**
```bash
git clone git@github.com:AriefDaffa/artemis-dashboard.git
cd artemis-dashboard
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Configure environment**
```bash
cp .env.example .env
```

Edit `.env` and set your `MT5_TERMINAL_ID` (the folder name under `AppData/Roaming/MetaQuotes/Terminal/`):
```env
MT5_TERMINAL_ID=YOUR_TERMINAL_ID_HERE
PORT=8100
```

> To find your terminal ID: open `%APPDATA%\MetaQuotes\Terminal\` — it's the folder that was last modified when your MT5 is running.

**4. Run**
```bash
python main.py
```
Or double-click `run.bat`.

**5. Open in browser**
```
http://localhost:8100
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MT5_TERMINAL_ID` | *(empty)* | MT5 terminal folder ID under `AppData/Roaming/MetaQuotes/Terminal/` |
| `MT5_LOG_DIR` | *(auto-derived)* | Full path to terminal log dir. Auto-built from `MT5_TERMINAL_ID` if not set. |
| `PORT` | `8100` | Port to serve the dashboard on |

---

## Project Structure

```
artemis-dashboard/
  main.py             ← FastAPI backend + MT5 data layer
  requirements.txt    ← pinned dependencies
  run.bat             ← Windows one-click launcher
  .env.example        ← environment variable template
  templates/
    index.html        ← Bloomberg-style dashboard (vanilla JS + Chart.js)
```

---

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Dashboard HTML |
| `GET /api/status` | MT5 connection status |
| `GET /api/account` | Account info (balance, equity, margin, leverage) |
| `GET /api/positions` | Open positions |
| `GET /api/orders` | Pending orders |
| `GET /api/history` | Today's closed deals |
| `GET /api/tick?symbol=SYMBOL` | Live bid/ask/spread for a symbol |
| `GET /api/log?lines=50` | Last N lines from today's MT5 journal |
| `GET /api/session` | Active trading sessions + time remaining |

---

## Notes

- **Read-only** — no orders are placed, modified, or cancelled. Safe to run alongside any EA.
- The MT5 Python API connects via a Windows named pipe to the running `terminal64.exe`. MT5 must be open for the dashboard to work.
- The equity curve shows today's session only (resets at broker's daily rollover).
