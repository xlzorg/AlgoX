# Trading Bot Usage Guide

This guide covers setup, offline backtesting, live paper trading, engine control, and monitoring for the FastAPI trading bot.

## 1. Prerequisites & Setup

Requirements:

- Python 3.11 or newer
- Network access for Binance public market data and CoinGecko Terminal data
- Optional Binance API credentials for future authenticated integrations. The current public market feeds do not require keys.

From the project directory:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

The existing workspace virtual environment can also be used:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
source ../venv/bin/activate
python -m pip install -r requirements.txt
```

### Configure `.env`

Create or edit `.env` in the `trading_bot/` directory. Start from the included `.env.example`:

```bash
cp .env.example .env
```

Use values like these:

```dotenv
APP_NAME=AlgoBot
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./trading_bot.db
API_HOST=127.0.0.1
API_PORT=8000
CORS_ORIGINS=http://localhost:3000,http://localhost:8000

# Optional for future authenticated Binance APIs.
# Public Binance market streams do not require these values.
BINANCE_API_KEY=
BINANCE_SECRET=

# The default is 10000.0 if omitted.
STARTING_BALANCE_USDT=10000.0
```

Never commit `.env` or API secrets. `.gitignore` already excludes `.env` and SQLite database files.

The application defaults include:

- Binance WebSocket: `wss://data-stream.binance.vision/stream`
- Binance REST: `https://data-api.binance.vision`
- Symbols: `BTCUSDT`, `ETHUSDT`
- Timeframes: `1m`, `5m`, `1h`
- Starting paper balance: `10000.0` USDT
- SQLite database: `trading_bot.db`

Initialize the database manually when needed:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
source ../venv/bin/activate
python -c 'import asyncio; from db.base import init_db; asyncio.run(init_db())'
```

There is currently no `Dockerfile` or `docker-compose.yml` in this project, so Docker Compose is not configured. Do not run `sudo docker compose up` unless you add a Docker setup separately.

## 2. Running a Backtest

The offline runner reads a CSV and reuses the production indicator, strategy, risk, paper-broker, and portfolio components. It does not connect to Binance or CoinGecko.

Place historical data anywhere readable by the process. A convenient location is:

```text
trading_bot/tests/backtest/data/BTCUSDT_1h.csv
```

The CSV must contain these columns:

```text
open_time,open,high,low,close,volume
```

Optional columns are `quote_volume`, `trades`, and `taker_buy_vol`. `open_time` may also be named `timestamp` and must be an integer timestamp in milliseconds.

Run a BTCUSDT 1-hour backtest from the project root:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
source ../venv/bin/activate
PYTHONPATH=. python tests/backtest/runner.py tests/backtest/data/BTCUSDT_1h.csv --symbol BTCUSDT --timeframe 1h

python tests/backtest/runner.py tests/backtest/data/BTCUSDT_1m_2026_07.csv --symbol BTCUSDT --timeframe 1m
```

Using the local `.venv` instead:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
source .venv/bin/activate
PYTHONPATH=. python tests/backtest/runner.py tests/backtest/data/BTCUSDT_1h.csv --symbol BTCUSDT --timeframe 1h
```

The command prints a JSON summary containing processed candles, elapsed time, candles per second, fills, signals, equity points, and final portfolio values.

The runner currently expects CSV input. It does not automatically trigger the Binance REST bootstrap. The REST feed API can fetch bootstrap candles for application code:

```python
import asyncio
from data.feeds.binance_rest_feed import BinanceRestFeed

async def main():
    feed = BinanceRestFeed()
    candles = await feed.fetch_candles("BTCUSDT", "1h", limit=500)
    await feed.close()
    print(len(candles))

asyncio.run(main())
```

Save/export those candles to the CSV format above before passing them to the offline runner.

## 3. Starting Live Paper Trading

Start the FastAPI application with Uvicorn:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
source ../venv/bin/activate
PYTHONPATH=. uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

With the project-local environment:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
source .venv/bin/activate
PYTHONPATH=. uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open the API documentation at:

```text
http://127.0.0.1:8000/docs
```

The application lifespan initializes SQLite and starts the trading engine automatically during startup. The engine creates the Binance WebSocket and CoinGecko feed tasks, so paper trading can begin as market events arrive.

## 4. Controlling the Engine

Check the current engine state:

```bash
curl http://127.0.0.1:8000/engine/status
```

Start the engine explicitly. This operation is idempotent if it is already running:

```bash
curl -X POST http://127.0.0.1:8000/engine/start
```

Stop the engine gracefully:

```bash
curl -X POST http://127.0.0.1:8000/engine/stop
```

The status response includes `running`, `uptime_sec`, `symbols`, and `active_tfs`:

```json
{
  "running": true,
  "uptime_sec": 12.4,
  "symbols": ["BTCUSDT", "ETHUSDT"],
  "active_tfs": ["1m", "5m", "1h"]
}
```

The same operations are available in Swagger UI at `http://127.0.0.1:8000/docs` by expanding the Engine section and selecting **Try it out**.

## 5. Monitoring Progress

### WebSocket live feed

Connect to the live endpoint:

```text
ws://127.0.0.1:8000/ws/live
```

If `wscat` is installed:

```bash
wscat -c ws://127.0.0.1:8000/ws/live
```

A dependency-free Python client using the installed `websockets` package:

```bash
cd /home/raspberrypi/Documents/Project_siang/trading_bot
source ../venv/bin/activate
python - <<'PY'
import asyncio
import json
import websockets

async def watch():
    async with websockets.connect("ws://127.0.0.1:8000/ws/live") as socket:
        while True:
            print(json.dumps(json.loads(await socket.recv()), indent=2))

asyncio.run(watch())
PY
```

Live messages use this shape:

```json
{
  "type": "signal",
  "payload": {},
  "ts": 1787330000000
}
```

Typical event types include `candle`, `indicator`, `signal`, `order_intent`, `fill`, and `trade_journal`.

### Money and portfolio state

Paper wallet and PnL summary:

```bash
curl http://127.0.0.1:8000/portfolio/summary
```

Currently open positions and unrealized PnL:

```bash
curl http://127.0.0.1:8000/trades/open
curl http://127.0.0.1:8000/portfolio/positions
```

Executed fills:

```bash
curl 'http://127.0.0.1:8000/trades?symbol=BTCUSDT&limit=50'
```

Full signal-to-fill journal:

```bash
curl http://127.0.0.1:8000/trades/journal
```

Wallet and equity history:

```bash
curl http://127.0.0.1:8000/portfolio/wallet/history
curl http://127.0.0.1:8000/portfolio/equity-curve
```

Indicator and signal monitoring:

```bash
curl http://127.0.0.1:8000/indicators/BTCUSDT/1h/latest
curl http://127.0.0.1:8000/signals/live
```

Performance analytics:

```bash
curl http://127.0.0.1:8000/analytics/performance
curl http://127.0.0.1:8000/analytics/performance/by-symbol
curl http://127.0.0.1:8000/analytics/performance/by-strategy
curl http://127.0.0.1:8000/analytics/performance/by-regime
curl http://127.0.0.1:8000/analytics/returns/distribution
curl http://127.0.0.1:8000/analytics/slippage/report
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

To stop live paper trading, press `Ctrl+C` in the Uvicorn terminal or call:

```bash
curl -X POST http://127.0.0.1:8000/engine/stop
```
