# ALGO TRADING BOT — SYSTEM DESIGN REFERENCE
## Paper Trading Engine · FastAPI · SQLite · Binance + CoinGecko Terminal

> **Document type:** System Design Reference for AI Agent Code Generation  
> **Scope:** Paper (simulated) broker · Live market data · Algorithmic signal logic · FastAPI REST layer · SQLite persistence · Statistical analysis  
> **Stack:** Python 3.11+ · FastAPI · SQLAlchemy (async) · SQLite · WebSocket · Asyncio

---

## 1. FULL SYSTEM ARCHITECTURE

```
╔══════════════════════════════════════════════════════════════════════════════╗
║                          EXTERNAL DATA SOURCES                               ║
║                                                                              ║
║  ┌──────────────────────┐          ┌─────────────────────────────────────┐  ║
║  │    BINANCE API        │          │    COINGECKO TERMINAL API           │  ║
║  │  WS: kline streams   │          │    REST: on-chain metrics (free)    │  ║
║  │  REST: OHLCV history │          │    DEX pools · TVL · Netflow        │  ║
║  │  WS: order book      │          │    NVT · Active Addresses           │  ║
║  │  WS: trade stream    │          │    Rate limit: ~30 req/min          │  ║
║  └──────────┬───────────┘          └────────────────┬────────────────────┘  ║
╚═════════════╪════════════════════════════════════════╪════════════════════════╝
              │                                        │
╔═════════════▼════════════════════════════════════════▼════════════════════════╗
║                        DATA INGESTION LAYER                                   ║
║                                                                               ║
║  DataFeedManager (async task manager)                                         ║
║  ├── BinanceWSFeed      websocket client · reconnect logic · ping/pong        ║
║  ├── BinanceRESTFeed    historical bootstrap · rate-limited pagination        ║
║  └── CoinGeckoFeed      60s polling loop · exponential backoff on 429        ║
║                                                                               ║
║  RawDataBus (asyncio.Queue)                                                   ║
║       │                                                                       ║
║       ▼                                                                       ║
║  Normalizer ──► canonical Candle / OnChainSnapshot schema                    ║
║       │                                                                       ║
║       ├──► MarketDataStore (in-memory deque, fast indicator compute)         ║
║       │                                                                       ║
║       └──► [WRITE] SQLite · tables: candles, onchain_snapshots               ║
╚═══════════════════════════════════╦══════════════════════════════════════════╝
                                    ║
╔═══════════════════════════════════▼══════════════════════════════════════════╗
║                        INDICATOR ENGINE LAYER                                 ║
║                                                                               ║
║  IndicatorPipeline.compute(symbol, timeframe)                                ║
║  ├── [PRICE]      EMA(9,21,50,200) · VWAP · Bollinger Bands · Ichimoku      ║
║  ├── [MOMENTUM]   RSI(14) · MACD(12,26,9) · Stochastic · MFI               ║
║  ├── [VOLUME]     OBV · Volume Profile · Taker Buy Ratio · VWAP Dev         ║
║  ├── [VOLATILITY] ATR(14) · Keltner Channel · Historical Vol · ADX          ║
║  └── [ON-CHAIN]   NVT · Exchange Netflow · Active Addresses · TVL Delta     ║
║                                                                               ║
║  IndicatorSnapshot ──► [WRITE] SQLite · table: indicator_snapshots           ║
╚═══════════════════════════════════╦══════════════════════════════════════════╝
                                    ║
╔═══════════════════════════════════▼══════════════════════════════════════════╗
║                         STRATEGY LAYER                                        ║
║                                                                               ║
║  RegimeDetector ──► market_regime: TRENDING_UP | RANGING | HIGH_VOL | ...   ║
║                                                                               ║
║  StrategyEngine                                                               ║
║  ├── TrendFollowingStrategy   (weight: 0.40)                                  ║
║  ├── MeanReversionStrategy    (weight: 0.25)                                  ║
║  ├── BreakoutStrategy         (weight: 0.25)                                  ║
║  └── CompositeStrategy        (weighted combinator + regime gate)             ║
║                                                                               ║
║  Signal { BUY|SELL|HOLD|EXIT, confidence, reasoning_trace }                  ║
║  └──► [WRITE] SQLite · table: signals                                         ║
╚═══════════════════════════════════╦══════════════════════════════════════════╝
                                    ║
╔═══════════════════════════════════▼══════════════════════════════════════════╗
║                       RISK MANAGEMENT LAYER                                   ║
║                                                                               ║
║  RiskGuard (pre-trade gate)                                                   ║
║  ├── PositionSizer        Kelly-fractional · ATR-normalized                   ║
║  ├── StopLossManager      ATR-based · fixed % · trailing                      ║
║  ├── TakeProfitManager    R-multiple (TP1 1.5R · TP2 2.5R) · trailing       ║
║  ├── MaxDrawdownCircuit   portfolio breaker — halts engine on breach          ║
║  ├── ExposureGuard        max positions · concentration limits                ║
║  └── CooldownManager      time-lock after stop-hit                            ║
║                                                                               ║
║  OrderIntent { approved | rejected + reason }                                 ║
║  └──► [WRITE] SQLite · table: risk_events                                     ║
╚═══════════════════════════════════╦══════════════════════════════════════════╝
                                    ║
╔═══════════════════════════════════▼══════════════════════════════════════════╗
║                    PAPER BROKER (SIMULATED EXECUTION)                         ║
║                                                                               ║
║  PaperBroker                                                                  ║
║  ├── VirtualWallet        USDT balance · per-asset holdings (in-memory)      ║
║  ├── OrderBook            pending LIMIT order queue                           ║
║  ├── OrderExecutor        fills against live Binance price + slippage        ║
║  ├── SlippageModel        market impact + Gaussian noise                      ║
║  └── FeeModel             0.10% taker / 0.08% maker                          ║
║                                                                               ║
║  Fill { order_id, price, qty, fee, slippage, timestamp }                     ║
║  └──► [WRITE] SQLite · tables: orders, fills, wallet_snapshots               ║
╚═══════════════════════════════════╦══════════════════════════════════════════╝
                                    ║
╔═══════════════════════════════════▼══════════════════════════════════════════╗
║                      PORTFOLIO & P&L LAYER                                    ║
║                                                                               ║
║  PortfolioManager                                                             ║
║  ├── PositionTracker      open / closed positions · unrealized PnL            ║
║  ├── PerformanceMetrics   Sharpe · Sortino · Max DD · Win Rate · Expectancy  ║
║  ├── EquityCurve          timestamped portfolio value series                  ║
║  └── TradeJournal         full audit: signal → intent → fill → outcome       ║
║                                                                               ║
║  └──► [WRITE] SQLite · tables: positions, equity_curve, trade_journal        ║
║  └──► [READ]  Statistical queries for FastAPI response layer                 ║
╚═══════════════════════════════════╦══════════════════════════════════════════╝
                                    ║
╔═══════════════════════════════════▼══════════════════════════════════════════╗
║                        FASTAPI APPLICATION LAYER                              ║
║                                                                               ║
║  app/                                                                         ║
║  ├── REST API routes     /engine /market /trades /portfolio /analytics       ║
║  ├── WebSocket endpoint  /ws/live  ──► streams ticks + signals to client     ║
║  └── Background Tasks    lifespan() starts trading engine on app boot        ║
║                                                                               ║
║  SQLite (SQLAlchemy async)                                                    ║
║  └── Single file: trading_bot.db                                              ║
║      ├── candles                 raw OHLCV per symbol/TF                     ║
║      ├── onchain_snapshots       CoinGecko on-chain data                     ║
║      ├── indicator_snapshots     computed indicator values per candle         ║
║      ├── signals                 strategy signals with reasoning trace        ║
║      ├── risk_events             approved/rejected order intents              ║
║      ├── orders                  paper broker order records                   ║
║      ├── fills                   execution records with slippage/fee         ║
║      ├── positions               open + closed positions                      ║
║      ├── wallet_snapshots        balance history over time                    ║
║      ├── equity_curve            portfolio value timeseries                   ║
║      └── trade_journal           full trade audit log                         ║
╚═══════════════════════════════════╦══════════════════════════════════════════╝
                                    ║
╔═══════════════════════════════════▼══════════════════════════════════════════╗
║                       OBSERVABILITY LAYER                                     ║
║                                                                               ║
║  StructuredLogger (JSON) · EventBus (asyncio) · AlertManager                 ║
║  Dashboard WebSocket ──► pushes live candles + signals + equity to frontend  ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

---

## 2. FULL DIRECTORY STRUCTURE

```
trading_bot/
│
├── main.py                        # FastAPI entry point (uvicorn target)
├── requirements.txt
├── .env                           # secrets: API keys (never committed)
├── trading_bot.db                 # SQLite database (auto-created)
│
├── config/
│   ├── settings.py                # pydantic BaseSettings, reads .env
│   ├── symbols.py                 # trading pairs + timeframes config
│   └── risk_params.py             # all risk limits + sizing params
│
├── app/                           # ── FASTAPI APPLICATION ──
│   ├── __init__.py
│   ├── lifespan.py                # startup/shutdown: boot trading engine
│   ├── dependencies.py            # get_db(), get_engine() DI providers
│   │
│   ├── routers/
│   │   ├── engine.py              # POST /engine/start|stop|status
│   │   ├── market.py              # GET  /market/candles · /market/onchain
│   │   ├── indicators.py          # GET  /indicators/{symbol}/{timeframe}
│   │   ├── signals.py             # GET  /signals · /signals/{id}
│   │   ├── trades.py              # GET  /trades · /trades/{id}
│   │   ├── portfolio.py           # GET  /portfolio/summary · /positions
│   │   ├── analytics.py           # GET  /analytics/* (statistical queries)
│   │   └── ws.py                  # WS   /ws/live
│   │
│   ├── schemas/                   # Pydantic request/response models
│   │   ├── market.py
│   │   ├── signal.py
│   │   ├── trade.py
│   │   ├── portfolio.py
│   │   └── analytics.py
│   │
│   └── middleware.py              # CORS · request logging · error handling
│
├── db/                            # ── DATABASE LAYER ──
│   ├── base.py                    # SQLAlchemy async engine + session factory
│   ├── models/                    # ORM table definitions
│   │   ├── candle.py
│   │   ├── onchain_snapshot.py
│   │   ├── indicator_snapshot.py
│   │   ├── signal.py
│   │   ├── risk_event.py
│   │   ├── order.py
│   │   ├── fill.py
│   │   ├── position.py
│   │   ├── wallet_snapshot.py
│   │   ├── equity_curve.py
│   │   └── trade_journal.py
│   │
│   ├── repositories/              # DB access — all raw SQL/ORM queries
│   │   ├── candle_repo.py
│   │   ├── signal_repo.py
│   │   ├── trade_repo.py
│   │   ├── portfolio_repo.py
│   │   └── analytics_repo.py      # complex statistical queries
│   │
│   └── migrations/                # Alembic migration scripts (optional)
│
├── data/                          # ── DATA INGESTION LAYER ──
│   ├── feeds/
│   │   ├── base_feed.py
│   │   ├── binance_ws_feed.py
│   │   ├── binance_rest_feed.py
│   │   └── coingecko_feed.py
│   ├── normalizer.py
│   ├── market_store.py            # in-memory rolling window (hot path)
│   └── data_bus.py                # asyncio pub/sub dispatcher
│
├── indicators/                    # ── INDICATOR ENGINE ──
│   ├── base_indicator.py
│   ├── price/
│   │   ├── ema.py
│   │   ├── vwap.py
│   │   └── bollinger.py
│   ├── momentum/
│   │   ├── rsi.py
│   │   ├── macd.py
│   │   └── stochastic.py
│   ├── volume/
│   │   ├── obv.py
│   │   └── volume_profile.py
│   ├── volatility/
│   │   ├── atr.py
│   │   ├── adx.py
│   │   └── keltner.py
│   ├── onchain/
│   │   ├── nvt_signal.py
│   │   ├── exchange_netflow.py
│   │   └── active_addresses.py
│   └── pipeline.py
│
├── strategy/                      # ── STRATEGY LAYER ──
│   ├── base_strategy.py
│   ├── regime_detector.py
│   ├── trend_following.py
│   ├── mean_reversion.py
│   ├── breakout.py
│   └── composite.py
│
├── risk/                          # ── RISK MANAGEMENT ──
│   ├── risk_guard.py
│   ├── position_sizer.py
│   ├── stop_loss.py
│   ├── take_profit.py
│   ├── drawdown_circuit.py
│   └── exposure_guard.py
│
├── broker/                        # ── PAPER BROKER ──
│   ├── paper_broker.py
│   ├── virtual_wallet.py
│   ├── order_executor.py
│   ├── slippage_model.py
│   └── fee_model.py
│
├── portfolio/                     # ── PORTFOLIO & P&L ──
│   ├── portfolio_manager.py
│   ├── position_tracker.py
│   ├── performance.py
│   └── trade_journal.py
│
├── engine/
│   └── trading_engine.py          # main async orchestrator
│
├── analytics/                     # ── STATISTICAL ANALYSIS ──
│   ├── performance_stats.py       # Sharpe, Sortino, Calmar, drawdown
│   ├── trade_distribution.py      # win/loss histograms, return dist
│   ├── indicator_correlation.py   # indicator vs outcome correlation
│   ├── regime_analysis.py         # performance segmented by regime
│   └── signal_quality.py          # precision/recall per strategy
│
├── observability/
│   ├── logger.py
│   ├── event_bus.py
│   └── alert_manager.py
│
└── tests/
    ├── unit/
    ├── integration/
    └── backtest/
```

---

## 3. FASTAPI APPLICATION DESIGN

### 3.1 Entry Point — `main.py`
```python
from fastapi import FastAPI
from app.lifespan import lifespan
from app.routers import engine, market, indicators, signals, trades, portfolio, analytics, ws
from app.middleware import register_middleware

app = FastAPI(
    title="AlgoBot Paper Trading Engine",
    version="1.0.0",
    lifespan=lifespan,
)

register_middleware(app)

app.include_router(engine.router,     prefix="/engine",     tags=["Engine"])
app.include_router(market.router,     prefix="/market",     tags=["Market Data"])
app.include_router(indicators.router, prefix="/indicators", tags=["Indicators"])
app.include_router(signals.router,    prefix="/signals",    tags=["Signals"])
app.include_router(trades.router,     prefix="/trades",     tags=["Trades"])
app.include_router(portfolio.router,  prefix="/portfolio",  tags=["Portfolio"])
app.include_router(analytics.router,  prefix="/analytics",  tags=["Analytics"])
app.include_router(ws.router,         prefix="/ws",         tags=["WebSocket"])
```

### 3.2 Lifespan — Engine Boot on App Start
```python
# app/lifespan.py
from contextlib import asynccontextmanager
from db.base import init_db
from engine.trading_engine import TradingEngine

trading_engine: TradingEngine | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP
    await init_db()                          # create tables if not exists
    global trading_engine
    trading_engine = TradingEngine()
    await trading_engine.start()             # boots feeds, indicators, strategy loop
    yield
    # SHUTDOWN
    await trading_engine.stop()
```

### 3.3 Full API Route Reference

#### ENGINE CONTROL
```
POST  /engine/start          Start the trading engine (if not running)
POST  /engine/stop           Graceful shutdown of all feeds + strategy loop
GET   /engine/status         { running, uptime_sec, symbols, active_tfs, regime }
POST  /engine/reset          Clear paper wallet, reset equity to starting balance
```

#### MARKET DATA
```
GET   /market/candles
      ?symbol=BTCUSDT&timeframe=1h&limit=200&from_ts=&to_ts=
      → List[CandleResponse]

GET   /market/candles/latest/{symbol}/{timeframe}
      → latest closed candle

GET   /market/onchain/{symbol}
      → latest OnChainSnapshot from DB

GET   /market/orderbook/{symbol}
      → current best bid/ask from in-memory store
```

#### INDICATORS
```
GET   /indicators/{symbol}/{timeframe}/latest
      → IndicatorSnapshotResponse (all computed values for last closed candle)

GET   /indicators/{symbol}/{timeframe}/history
      ?limit=100
      → List[IndicatorSnapshotResponse] from DB

GET   /indicators/{symbol}/compare
      ?tf1=1h&tf2=4h
      → side-by-side latest indicators for multi-TF analysis
```

#### SIGNALS
```
GET   /signals
      ?symbol=&direction=&strategy=&from_ts=&to_ts=&limit=50
      → List[SignalResponse] with reasoning_trace

GET   /signals/{signal_id}
      → full signal detail + linked indicator snapshot

GET   /signals/live
      → last 10 signals across all symbols (dashboard feed)
```

#### TRADES
```
GET   /trades
      ?symbol=&status=open|closed&from_ts=&to_ts=&limit=50
      → List[TradeResponse]

GET   /trades/{trade_id}
      → full trade detail: entry signal + fill + risk params + outcome

GET   /trades/open
      → all currently open paper positions with unrealized PnL

GET   /trades/journal
      → full audit log: signal → intent → fill → close → PnL
```

#### PORTFOLIO
```
GET   /portfolio/summary
      → { balance_usdt, total_equity, open_positions, unrealized_pnl,
          realized_pnl_today, realized_pnl_total }

GET   /portfolio/positions
      → List[PositionResponse] with entry price, current price, PnL%

GET   /portfolio/wallet/history
      ?from_ts=&to_ts=
      → List[WalletSnapshot] — balance over time

GET   /portfolio/equity-curve
      ?from_ts=&to_ts=&interval=1h
      → List[EquityPoint] — portfolio value timeseries (for charting)
```

#### ANALYTICS (Statistical Queries)
```
GET   /analytics/performance
      → full metrics: Sharpe, Sortino, Calmar, MaxDD, WinRate, Expectancy,
        ProfitFactor, AvgRR, TotalTrades, AvgHoldingTime

GET   /analytics/performance/by-symbol
      → performance breakdown per trading pair

GET   /analytics/performance/by-strategy
      → performance breakdown per strategy (TrendFollow / Reversion / Breakout)

GET   /analytics/performance/by-regime
      → performance segmented by detected market regime

GET   /analytics/drawdown/periods
      → List[DrawdownPeriod] { start, end, peak_equity, trough_equity, depth_pct, duration_bars }

GET   /analytics/returns/distribution
      ?bucket_size=0.005
      → histogram of trade returns (for fat-tail / skewness analysis)

GET   /analytics/indicators/correlation
      ?target=trade_pnl_pct&from_ts=&to_ts=
      → Pearson correlation of each indicator value vs trade PnL outcome
        (identifies which indicators actually predict profitability)

GET   /analytics/signals/quality
      → per-strategy precision / recall / F1:
        precision = BUY signals that led to profitable trades / total BUY signals
        recall    = profitable trades captured / all profitable opportunities

GET   /analytics/regime/summary
      → trading session counts + avg PnL per regime type

GET   /analytics/slippage/report
      → avg, p50, p95 slippage stats (paper broker execution quality audit)

GET   /analytics/calendar/heatmap
      → daily PnL map: { date, pnl_pct, trades, regime } for calendar heatmap

GET   /analytics/rolling
      ?window=30&metric=sharpe|winrate|pnl
      → rolling window metric over time (detect strategy decay)
```

#### WEBSOCKET
```
WS    /ws/live
      → streams JSON events to connected clients:
        { type: "candle" | "signal" | "fill" | "equity_update" | "alert",
          payload: {...},
          ts: unix_ms }
```

---

## 4. DATABASE DESIGN — SQLite TABLES

### 4.1 `candles`
```sql
CREATE TABLE candles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    open_time       INTEGER NOT NULL,     -- Unix ms
    open            REAL NOT NULL,
    high            REAL NOT NULL,
    low             REAL NOT NULL,
    close           REAL NOT NULL,
    volume          REAL NOT NULL,
    quote_volume    REAL NOT NULL,
    trades          INTEGER,
    taker_buy_vol   REAL,
    created_at      INTEGER NOT NULL,
    UNIQUE(symbol, timeframe, open_time)
);
CREATE INDEX idx_candles_symbol_tf_time ON candles(symbol, timeframe, open_time DESC);
```

### 4.2 `onchain_snapshots`
```sql
CREATE TABLE onchain_snapshots (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol               TEXT NOT NULL,
    chain                TEXT NOT NULL,
    timestamp            INTEGER NOT NULL,
    pool_tvl_usd         REAL,
    pool_volume_24h      REAL,
    exchange_netflow_24h REAL,       -- negative = bullish (outflows)
    nvt_ratio            REAL,
    active_addresses_24h INTEGER,
    top10_holder_pct     REAL,
    created_at           INTEGER NOT NULL,
    UNIQUE(symbol, timestamp)
);
```

### 4.3 `indicator_snapshots`
```sql
CREATE TABLE indicator_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    candle_time     INTEGER NOT NULL,    -- links to candles.open_time
    -- Price
    ema_9           REAL,
    ema_21          REAL,
    ema_50          REAL,
    ema_200         REAL,
    vwap            REAL,
    bb_upper        REAL,
    bb_mid          REAL,
    bb_lower        REAL,
    -- Momentum
    rsi_14          REAL,
    macd_line       REAL,
    macd_signal     REAL,
    macd_hist       REAL,
    stoch_k         REAL,
    stoch_d         REAL,
    mfi_14          REAL,
    -- Volume
    obv             REAL,
    taker_buy_ratio REAL,
    vwap_dev_pct    REAL,
    -- Volatility / Trend
    atr_14          REAL,
    adx_14          REAL,
    kc_upper        REAL,
    kc_lower        REAL,
    hist_vol_20     REAL,
    -- On-chain (denormalized from onchain_snapshots for query convenience)
    nvt_ratio       REAL,
    exchange_netflow REAL,
    -- Regime
    market_regime   TEXT,            -- TRENDING_UP | TRENDING_DOWN | RANGING | HIGH_VOL
    created_at      INTEGER NOT NULL,
    UNIQUE(symbol, timeframe, candle_time)
);
CREATE INDEX idx_ind_symbol_tf_time ON indicator_snapshots(symbol, timeframe, candle_time DESC);
```

### 4.4 `signals`
```sql
CREATE TABLE signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_uuid     TEXT NOT NULL UNIQUE,
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    timestamp       INTEGER NOT NULL,
    direction       TEXT NOT NULL,      -- BUY | SELL | HOLD | EXIT
    confidence      REAL NOT NULL,      -- 0.0 – 1.0
    strategy_id     TEXT NOT NULL,      -- trend_following | mean_reversion | breakout | composite
    reasoning       TEXT NOT NULL,      -- JSON blob: {indicator: value, threshold: value, met: bool}
    market_regime   TEXT,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_signals_symbol_time ON signals(symbol, timestamp DESC);
CREATE INDEX idx_signals_direction   ON signals(direction);
```

### 4.5 `risk_events`
```sql
CREATE TABLE risk_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_uuid     TEXT NOT NULL,      -- FK → signals.signal_uuid
    symbol          TEXT NOT NULL,
    timestamp       INTEGER NOT NULL,
    decision        TEXT NOT NULL,      -- APPROVED | REJECTED
    rejection_reason TEXT,              -- null if approved
    position_size   REAL,
    risk_pct        REAL,
    stop_loss_price REAL,
    tp1_price       REAL,
    tp2_price       REAL,
    created_at      INTEGER NOT NULL
);
```

### 4.6 `orders`
```sql
CREATE TABLE orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_uuid      TEXT NOT NULL UNIQUE,
    signal_uuid     TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    order_type      TEXT NOT NULL,      -- MARKET | LIMIT | STOP_MARKET
    side            TEXT NOT NULL,      -- BUY | SELL
    quantity        REAL NOT NULL,
    limit_price     REAL,
    stop_price      REAL,
    status          TEXT NOT NULL,      -- PENDING | FILLED | PARTIAL | CANCELLED | REJECTED
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER
);
```

### 4.7 `fills`
```sql
CREATE TABLE fills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fill_uuid       TEXT NOT NULL UNIQUE,
    order_uuid      TEXT NOT NULL,      -- FK → orders.order_uuid
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    filled_qty      REAL NOT NULL,
    avg_price       REAL NOT NULL,
    fee             REAL NOT NULL,
    fee_asset       TEXT NOT NULL,
    slippage_pct    REAL NOT NULL,
    timestamp       INTEGER NOT NULL,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_fills_symbol_time ON fills(symbol, timestamp DESC);
```

### 4.8 `positions`
```sql
CREATE TABLE positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_uuid   TEXT NOT NULL UNIQUE,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,          -- LONG | SHORT
    status          TEXT NOT NULL,          -- OPEN | CLOSED
    entry_signal_uuid TEXT,
    entry_fill_uuid TEXT,
    exit_fill_uuid  TEXT,
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    quantity        REAL NOT NULL,
    stop_loss_price REAL,
    tp1_price       REAL,
    tp2_price       REAL,
    realized_pnl    REAL,                  -- null while OPEN
    realized_pnl_pct REAL,
    total_fees      REAL,
    holding_bars    INTEGER,               -- duration in candle count
    entry_time      INTEGER NOT NULL,
    exit_time       INTEGER,
    strategy_id     TEXT,
    market_regime   TEXT,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_positions_symbol_status ON positions(symbol, status);
CREATE INDEX idx_positions_entry_time    ON positions(entry_time DESC);
```

### 4.9 `wallet_snapshots`
```sql
CREATE TABLE wallet_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       INTEGER NOT NULL,
    usdt_balance    REAL NOT NULL,
    total_equity    REAL NOT NULL,      -- balance + unrealized positions value
    open_positions  INTEGER NOT NULL,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_wallet_time ON wallet_snapshots(timestamp DESC);
```

### 4.10 `equity_curve`
```sql
CREATE TABLE equity_curve (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       INTEGER NOT NULL UNIQUE,
    equity          REAL NOT NULL,       -- total portfolio value in USDT
    drawdown_pct    REAL NOT NULL,       -- current drawdown from peak
    peak_equity     REAL NOT NULL,
    created_at      INTEGER NOT NULL
);
CREATE INDEX idx_equity_time ON equity_curve(timestamp DESC);
```

### 4.11 `trade_journal`
```sql
CREATE TABLE trade_journal (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    position_uuid       TEXT NOT NULL UNIQUE,
    symbol              TEXT NOT NULL,
    strategy_id         TEXT NOT NULL,
    market_regime       TEXT,
    -- Entry
    entry_time          INTEGER,
    entry_price         REAL,
    entry_signal_direction TEXT,
    entry_confidence    REAL,
    entry_reasoning     TEXT,           -- JSON: indicator state at entry
    -- Exit
    exit_time           INTEGER,
    exit_price          REAL,
    exit_reason         TEXT,           -- TP1 | TP2 | TRAILING_STOP | STOP_LOSS | SIGNAL_EXIT
    -- Outcome
    pnl_usdt            REAL,
    pnl_pct             REAL,
    r_multiple          REAL,           -- actual PnL / initial risk
    fees_usdt           REAL,
    slippage_pct        REAL,
    -- For statistical analysis
    indicator_snapshot  TEXT,           -- JSON: full indicator values at entry
    onchain_snapshot    TEXT,           -- JSON: on-chain state at entry
    created_at          INTEGER NOT NULL
);
```

---

## 5. SQLALCHEMY ASYNC SETUP

### 5.1 `db/base.py`
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./trading_bot.db"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 5.2 Example ORM Model — `db/models/position.py`
```python
from sqlalchemy import Column, Integer, Text, Real
from db.base import Base

class Position(Base):
    __tablename__ = "positions"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    position_uuid   = Column(Text, unique=True, nullable=False)
    symbol          = Column(Text, nullable=False)
    side            = Column(Text, nullable=False)
    status          = Column(Text, nullable=False, default="OPEN")
    entry_price     = Column(Real, nullable=False)
    exit_price      = Column(Real)
    quantity        = Column(Real, nullable=False)
    stop_loss_price = Column(Real)
    tp1_price       = Column(Real)
    tp2_price       = Column(Real)
    realized_pnl    = Column(Real)
    realized_pnl_pct = Column(Real)
    total_fees      = Column(Real)
    holding_bars    = Column(Integer)
    entry_time      = Column(Integer, nullable=False)
    exit_time       = Column(Integer)
    strategy_id     = Column(Text)
    market_regime   = Column(Text)
    created_at      = Column(Integer, nullable=False)
```

---

## 6. ANALYTICS LAYER — STATISTICAL QUERIES

### 6.1 `db/repositories/analytics_repo.py`
```python
# These are the complex SQL queries that power /analytics/* endpoints

# ── PERFORMANCE SUMMARY ──────────────────────────────────────────────────────
PERF_SUMMARY = """
    SELECT
        COUNT(*)                                    AS total_trades,
        SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate,
        AVG(pnl_pct)                               AS avg_trade_pct,
        SUM(pnl_usdt)                              AS total_pnl_usdt,
        AVG(r_multiple)                            AS avg_r_multiple,
        SUM(CASE WHEN pnl_usdt > 0 THEN pnl_usdt ELSE 0 END) /
        NULLIF(ABS(SUM(CASE WHEN pnl_usdt < 0 THEN pnl_usdt ELSE 0 END)), 0)
                                                   AS profit_factor,
        AVG(CASE WHEN pnl_pct > 0 THEN pnl_pct ELSE NULL END) AS avg_win_pct,
        AVG(CASE WHEN pnl_pct < 0 THEN pnl_pct ELSE NULL END) AS avg_loss_pct,
        AVG(exit_time - entry_time)                AS avg_hold_ms
    FROM trade_journal
    WHERE status = 'CLOSED'
"""

# ── RETURN DISTRIBUTION (for histogram) ─────────────────────────────────────
RETURN_DIST = """
    SELECT
        ROUND(pnl_pct / :bucket * :bucket, 4) AS bucket,
        COUNT(*) AS count
    FROM trade_journal
    WHERE status = 'CLOSED'
    GROUP BY 1
    ORDER BY 1
"""

# ── INDICATOR CORRELATION vs TRADE OUTCOME ───────────────────────────────────
# Reads indicator_snapshot JSON and computes Pearson r with pnl_pct
# Done in Python (pandas) after pulling the data, not pure SQL

# ── PERFORMANCE BY REGIME ────────────────────────────────────────────────────
PERF_BY_REGIME = """
    SELECT
        market_regime,
        COUNT(*)                                              AS trades,
        AVG(pnl_pct)                                          AS avg_pnl_pct,
        SUM(CASE WHEN pnl_pct > 0 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) AS win_rate,
        SUM(pnl_usdt)                                         AS total_pnl
    FROM trade_journal
    WHERE status = 'CLOSED'
    GROUP BY market_regime
"""

# ── ROLLING SHARPE (30-day window) ──────────────────────────────────────────
# Pull daily_pnl_pct series, then compute rolling Sharpe in pandas:
#   rolling_sharpe = returns.rolling(window).mean() /
#                    returns.rolling(window).std() * sqrt(252)

# ── MAX DRAWDOWN PERIODS ─────────────────────────────────────────────────────
DRAWDOWN_PERIODS = """
    SELECT
        timestamp,
        equity,
        drawdown_pct,
        peak_equity
    FROM equity_curve
    ORDER BY timestamp ASC
"""
# Drawdown period identification done in Python:
# find segments where drawdown_pct < -threshold, track start/end/depth

# ── SIGNAL QUALITY (precision / recall per strategy) ────────────────────────
SIGNAL_QUALITY = """
    SELECT
        j.strategy_id,
        COUNT(*)                                                  AS total_signals,
        SUM(CASE WHEN j.pnl_pct > 0 THEN 1 ELSE 0 END)          AS profitable,
        SUM(CASE WHEN j.pnl_pct > 0 THEN 1 ELSE 0 END) * 1.0 /
        NULLIF(COUNT(*), 0)                                       AS precision,
        AVG(j.r_multiple)                                         AS avg_r
    FROM trade_journal j
    WHERE j.status = 'CLOSED'
    GROUP BY j.strategy_id
"""
```

### 6.2 `analytics/performance_stats.py` — Python Computations
```python
import pandas as pd
import numpy as np
from typing import List

def compute_sharpe(returns: List[float], risk_free: float = 0.0,
                   periods_per_year: int = 252) -> float:
    r = pd.Series(returns)
    excess = r - risk_free / periods_per_year
    return float(excess.mean() / excess.std() * np.sqrt(periods_per_year)) \
        if excess.std() > 0 else 0.0

def compute_sortino(returns: List[float], risk_free: float = 0.0,
                    periods_per_year: int = 252) -> float:
    r = pd.Series(returns)
    excess = r - risk_free / periods_per_year
    downside = excess[excess < 0].std()
    return float(excess.mean() / downside * np.sqrt(periods_per_year)) \
        if downside > 0 else 0.0

def compute_max_drawdown(equity_series: List[float]) -> dict:
    eq = pd.Series(equity_series)
    peak = eq.cummax()
    dd = (eq - peak) / peak
    max_dd = float(dd.min())
    end_idx = int(dd.idxmin())
    start_idx = int(eq[:end_idx].idxmax())
    recovery = eq[end_idx:]
    recovered = recovery[recovery >= peak[end_idx]]
    duration = int(recovered.index[0] - end_idx) if len(recovered) > 0 else None
    return {
        "max_drawdown_pct": max_dd,
        "peak_idx": start_idx,
        "trough_idx": end_idx,
        "recovery_bars": duration,
    }

def compute_rolling_sharpe(daily_returns: pd.Series, window: int = 30) -> pd.Series:
    return (daily_returns.rolling(window).mean() /
            daily_returns.rolling(window).std() * np.sqrt(252))

def compute_expectancy(wins: List[float], losses: List[float]) -> float:
    """Expected PnL per trade in % terms"""
    if not wins and not losses:
        return 0.0
    win_rate = len(wins) / (len(wins) + len(losses))
    avg_win  = np.mean(wins)  if wins   else 0.0
    avg_loss = np.mean(losses) if losses else 0.0
    return float(win_rate * avg_win + (1 - win_rate) * avg_loss)

def compute_indicator_correlation(df: pd.DataFrame,
                                  target_col: str = "pnl_pct") -> pd.Series:
    """
    df: columns = indicator names + target_col
    Returns Pearson r of each indicator vs pnl_pct
    """
    numeric = df.select_dtypes(include=[float, int]).drop(columns=[target_col], errors="ignore")
    return numeric.corrwith(df[target_col]).sort_values(ascending=False)
```

---

## 7. DATA FLOW — DUAL PATH DESIGN

The key architectural principle: **hot path (in-memory)** for trading decisions, **cold path (SQLite)** for persistence and analytics. They run in parallel, never blocking each other.

```
Binance WebSocket tick
        │
        ▼
   Normalizer
        │
        ├──► [HOT PATH]  MarketDataStore (deque)
        │                     │
        │                     ▼
        │              IndicatorPipeline (numpy, fast)
        │                     │
        │                     ▼
        │              StrategyEngine → Signal
        │                     │
        │                     ▼
        │              RiskGuard → OrderIntent
        │                     │
        │                     ▼
        │              PaperBroker → Fill
        │                     │
        │                     ▼
        │              PortfolioManager (in-memory state)
        │
        └──► [COLD PATH]  AsyncWriteQueue (asyncio.Queue)
                               │
                           DB Writer Task (background)
                               │
                           SQLite writes:
                           candles → indicator_snapshots →
                           signals → fills → positions →
                           equity_curve
```

**Rule:** The hot path never touches the database. DB writes are queued and executed by a dedicated background async task. This prevents I/O latency from affecting strategy execution timing.

---

## 8. WEBSOCKET LIVE FEED — `/ws/live`

```python
# app/routers/ws.py
from fastapi import WebSocket, WebSocketDisconnect
from engine.trading_engine import trading_engine

class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

@router.websocket("/live")
async def live_feed(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # keep-alive ping handler
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Event types pushed to clients:
# { type: "candle",        payload: CandleResponse,         ts: int }
# { type: "indicator",     payload: IndicatorResponse,      ts: int }
# { type: "signal",        payload: SignalResponse,          ts: int }
# { type: "fill",          payload: FillResponse,            ts: int }
# { type: "equity_update", payload: { equity, drawdown_pct }, ts: int }
# { type: "alert",         payload: { level, message },     ts: int }
```

---

## 9. TRADING ENGINE ORCHESTRATOR

```python
# engine/trading_engine.py

class TradingEngine:
    def __init__(self):
        self.running = False
        self.feeds: list[BaseFeed] = []
        self.market_store = MarketDataStore()
        self.indicator_pipeline = IndicatorPipeline(self.market_store)
        self.strategy_engine = StrategyEngine()
        self.risk_guard = RiskGuard()
        self.paper_broker = PaperBroker()
        self.portfolio_manager = PortfolioManager()
        self.db_write_queue: asyncio.Queue = asyncio.Queue(maxsize=10_000)

    async def start(self):
        self.running = True
        # Bootstrap historical data
        await self._bootstrap_history()
        # Start background tasks
        asyncio.create_task(self._run_binance_ws())
        asyncio.create_task(self._run_coingecko_poller())
        asyncio.create_task(self._run_db_writer())
        asyncio.create_task(self._run_ws_broadcaster())

    async def _on_candle_closed(self, candle: Candle):
        # HOT PATH — no DB calls here
        self.market_store.append(candle)
        indicators = self.indicator_pipeline.compute(candle.symbol, candle.timeframe)
        signal = self.strategy_engine.evaluate(indicators)
        intent = self.risk_guard.evaluate(signal, self.portfolio_manager.state)
        if intent.approved:
            fill = await self.paper_broker.submit(intent)
            self.portfolio_manager.update(fill)
        # COLD PATH — queue for async DB write
        await self.db_write_queue.put({
            "candle": candle,
            "indicators": indicators,
            "signal": signal,
            "intent": intent,
            "fill": fill if intent.approved else None,
        })

    async def _run_db_writer(self):
        async with AsyncSessionLocal() as db:
            while self.running:
                try:
                    event = await asyncio.wait_for(
                        self.db_write_queue.get(), timeout=1.0
                    )
                    await self._persist_event(db, event)
                    await db.commit()
                except asyncio.TimeoutError:
                    continue
```

---

## 10. INDICATOR PIPELINE — FULL REFERENCE

### 10.1 Price-Based
| Indicator | Parameters | Purpose |
|-----------|-----------|---------|
| EMA | 9, 21, 50, 200 | Trend direction · crossover signals |
| VWAP | Session-reset | Intraday fair value; institutional reference price |
| Bollinger Bands | 20, 2σ | Volatility bands; mean reversion zone |
| Ichimoku Cloud | 9, 26, 52 | Multi-dimension trend + S/R |

### 10.2 Momentum
| Indicator | Parameters | Purpose |
|-----------|-----------|---------|
| RSI | 14 | Overbought / oversold; divergence signal |
| MACD | 12, 26, 9 | Trend momentum; histogram flip |
| Stochastic | 14, 3, 3 | Short-term reversal timing |
| MFI | 14 | Money Flow Index — volume-weighted RSI |

### 10.3 Volume
| Indicator | Parameters | Purpose |
|-----------|-----------|---------|
| OBV | — | Trend confirmation via cumulative volume |
| Volume Profile | Session bins | HVN / LVN identification |
| Taker Buy Ratio | — | Aggressor bias; buyer vs seller dominance |
| VWAP Deviation | ±1σ, ±2σ | Distance from institutional fair value |

### 10.4 Volatility & Trend Strength
| Indicator | Parameters | Purpose |
|-----------|-----------|---------|
| ATR | 14 | Stop sizing; position sizing denominator |
| ADX | 14 | Trend strength (>25 = trending) |
| Keltner Channel | 20, 1.5×ATR | Breakout filter |
| Historical Vol | 20 | Regime classification input |

### 10.5 On-Chain (CoinGecko Terminal)
| Indicator | Bull Signal | Bear Signal |
|-----------|-------------|-------------|
| Exchange Netflow | Large outflows (accumulation) | Large inflows (sell pressure building) |
| NVT Ratio | Falling (efficient network use) | Rising spike (overvalued vs usage) |
| Active Addresses | Rising 7d trend | Sustained decline |
| DEX TVL Delta | TVL growing (capital entering) | TVL rapidly declining |
| Pool Volume 24h | High DEX turnover (organic demand) | Low activity |

---

## 11. STRATEGY LOGIC BLUEPRINTS

### 11.1 Trend Following
```
ENTRY LONG:
  Price > EMA(50) > EMA(200)        [trend aligned]
  EMA(9) crosses above EMA(21)      [short-term momentum trigger]
  MACD histogram > 0 and rising     [momentum confirmation]
  RSI(14) between 45–65             [not overbought entry]
  Volume > 1.5× 20-bar avg         [volume confirmation]
  Exchange netflow negative (24h)   [on-chain macro support]

EXIT:
  EMA(9) crosses below EMA(21)  OR  SL hit (1.5×ATR)  OR  TP2 hit (2.5R)
```

### 11.2 Mean Reversion
```
ENTRY LONG:
  Price < BB lower band (20, 2σ)
  RSI(14) < 30
  MFI(14) < 25
  Price < VWAP − 1.5σ
  OBV trend still positive (sellers exhausted, not capitulating)

EXIT:
  Price returns to VWAP midline  OR  RSI > 55  OR  SL below swing low
```

### 11.3 Breakout
```
ENTRY LONG:
  Close above 20-bar high
  Volume > 2× 20-bar avg on breakout candle
  ATR expanding (volatility opening up)
  Price above Keltner Channel upper band
  NVT falling + netflow negative (real demand backing the breakout)

EXIT:
  Trailing stop: 1×ATR below highest close since entry
  OR price closes back inside Keltner Channel
```

### 11.4 Composite Combinator
```python
composite_score = (
    trend_signal.confidence     * 0.40 +
    reversion_signal.confidence * 0.25 +
    breakout_signal.confidence  * 0.25 +
    onchain_score               * 0.10
)
# Regime gate: if regime == RANGING → suppress trend weight by 0.5
# Direction: score ≥ 0.65 → BUY / score ≤ 0.35 → SELL / else HOLD
```

---

## 12. RISK MANAGEMENT DESIGN

### 12.1 Position Sizing — Kelly-Fractional
```
Kelly%   = (WinRate × AvgWin/AvgLoss − LossRate) / (AvgWin/AvgLoss)
Half-Kelly = Kelly × 0.5    (standard institutional adjustment for uncertainty)
Risk $   = Portfolio × min(Half-Kelly, MAX_RISK_PER_TRADE_PCT=0.01)
Size     = Risk $ / (ATR(14) × ATR_STOP_MULTIPLIER)
```

### 12.2 Stop & Target Levels
```
Default Stop:   ATR(14) × 1.5 below entry
Tight Stop:     ATR(14) × 1.0 (breakout entries)
Wide Stop:      ATR(14) × 2.0 (trend following on 1h+)
TP1 (40%):      Entry + 1.5R → partial close
TP2 (40%):      Entry + 2.5R → partial close
TP3 (20%):      Trailing 1×ATR → ride the trend
```

### 12.3 Portfolio Circuit Breakers
```python
MAX_OPEN_POSITIONS     = 5
MAX_SINGLE_ASSET_PCT   = 0.20       # 20% max in one asset
MAX_DAILY_LOSS_PCT     = 0.03       # 3% → halt for the day
MAX_DRAWDOWN_PCT       = 0.10       # 10% from peak → full halt
COOLDOWN_AFTER_SL      = 300        # 5 min lock after stop hit
MAX_CORRELATION        = 0.80       # block if new pos correlated > 0.8
```

---

## 13. PAPER BROKER DESIGN

### 13.1 Slippage Model
```python
def calculate_slippage(order_type, qty, avg_volume_24h):
    market_impact = (qty / avg_volume_24h) * 0.1
    noise = random.gauss(0, 0.0002)     # 0.02% σ
    return market_impact + abs(noise) if order_type == "MARKET" else noise * 0.5
```

### 13.2 Fill Rules
```
MARKET:       Fills at last_price × (1 + slippage); immediate
LIMIT BUY:    Fills when ask_price ≤ limit_price (checked every tick)
LIMIT SELL:   Fills when bid_price ≥ limit_price
STOP MARKET:  Triggers on price cross → market fill with slippage
PARTIAL:      If qty > 10% of 1-min volume → split across 3 ticks
```

### 13.3 Fees
```
Taker (MARKET): 0.10% of filled_qty × avg_price
Maker (LIMIT):  0.08% of filled_qty × avg_price
```

---

## 14. API INTEGRATION SPECS

### 14.1 Binance WebSocket Streams
```python
streams = [
    "{symbol}@kline_1m",          # 1m candles
    "{symbol}@kline_5m",          # 5m candles
    "{symbol}@kline_1h",          # 1h candles
    "{symbol}@trade",             # individual trades → VWAP feed
    "{symbol}@depth5@100ms",      # order book top-5 → slippage model
    "{symbol}@aggTrade",          # aggregated trades
]
# wss://stream.binance.com:9443/stream?streams=<stream1>/<stream2>/...
```

### 14.2 Binance REST Bootstrap
```python
GET /api/v3/klines
    ?symbol=BTCUSDT&interval=1h&limit=500
# 500 × 1h = ~20 days; sufficient for EMA(200) warm-up
```

### 14.3 CoinGecko Terminal (Free Tier)
```python
BASE = "https://api.geckoterminal.com/api/v2"
{
    "pool":    f"{BASE}/networks/{{chain}}/pools/{{address}}",
    "ohlcv":   f"{BASE}/networks/{{chain}}/pools/{{address}}/ohlcv/{{tf}}",
    "token":   f"{BASE}/networks/{{chain}}/tokens/{{address}}",
    "trades":  f"{BASE}/networks/{{chain}}/pools/{{address}}/trades",
}
# Rate: ~30 req/min free. Strategy: poll every 60s, stagger symbols,
# exponential backoff on 429, cache for 55s
```

---

## 15. PERFORMANCE METRICS TRACKED IN DB

```python
# All persisted in trade_journal + computable from equity_curve

total_return_pct        # (final_equity − start) / start
annualized_return       # total_return ^ (365 / days_elapsed) − 1
sharpe_ratio            # target > 1.5
sortino_ratio           # target > 2.0
calmar_ratio            # ann_return / abs(max_drawdown_pct)
max_drawdown_pct        # from peak to trough in equity_curve
avg_drawdown_pct
max_drawdown_duration   # bars from peak to recovery
total_trades
win_rate                # target > 55%
avg_win_pct
avg_loss_pct
profit_factor           # sum(wins) / abs(sum(losses)), target > 1.5
avg_r_multiple          # avg realized R per trade
expectancy              # win_rate × avg_win + loss_rate × avg_loss
avg_hold_bars
avg_slippage_pct
rejected_order_count
```

---

## 16. HOW INSTITUTIONAL ALGO DESKS DESIGN THEIR SYSTEMS

### 16.1 Separation of Concerns
Hedge funds rigidly separate **Alpha** (strategy), **Risk** (pre/post-trade), and **Execution** (order routing/TCA). Each layer is independently testable and deployable. This design mirrors it: `StrategyEngine → RiskGuard → PaperBroker`, with FastAPI as the observability and control plane sitting orthogonally to the hot path.

### 16.2 The Research-Production Parity Problem
Quant teams maintain two environments: a vectorized **research environment** (pandas/numpy, backtesting) and a **production event-driven loop** (asyncio, tick-by-tick). Most alpha decay happens in the gap between them. Our canonical `Candle` and `IndicatorSnapshot` dataclasses are shared between both paths to close that gap.

### 16.3 Multi-Timeframe Confluence
Prop desks never trade on one timeframe:
- **HTF (1h / 4h):** directional bias
- **MTF (15m / 5m):** entry zone and structure
- **LTF (1m):** precise trigger

`CompositeStrategy` enforces HTF agreement before executing LTF entries.

### 16.4 Market Regime Classification
```
TRENDING_UP   → weight trend strategies; suppress mean reversion
TRENDING_DOWN → allow short signals; suppress longs
RANGING       → weight mean reversion; suppress breakout
HIGH_VOL      → shrink all position sizes; widen stops
LOW_VOL_COIL  → watch for breakout; pre-position small
```
Detected via: ADX(14) threshold + ATR percentile rank + BB width percentile.

### 16.5 Walk-Forward Optimization (WFO)
Institutions never optimize on the full history. They use rolling in-sample / out-of-sample windows (e.g. 90 days in / 30 days out). Strategy parameters are re-evaluated periodically against the rolling window analytics our `/analytics/rolling` endpoint exposes.

### 16.6 The 3-Layer Risk Check
1. **Pre-signal** — regime compatible? correlation check against open positions?
2. **Pre-order** — size within limits? drawdown circuit closed?
3. **Post-fill** — slippage within bounds? alert if fill deviates > threshold

### 16.7 Transaction Cost Analysis (TCA)
Institutions obsess over execution quality. The `/analytics/slippage/report` endpoint is our TCA module — it tells you if the paper broker's simulated execution is realistic and, later, becomes the benchmark for comparing real Binance execution against the simulation.

### 16.8 On-Chain as Macro Filter (Crypto Edge)
Traditional quant funds can't read blockchain state. Crypto allows near-real-time observation of **institutional wallet behavior** — exchange netflows, whale accumulation windows, and NVT are leading indicators unavailable in equity markets. CoinGecko Terminal surfaces these for free. We use on-chain signals as a **10% weight macro filter** in the composite signal — it skews the direction but never overrides price-based timing.

### 16.9 The FastAPI Control Plane
Most institutional systems have a separate **ops/monitoring interface** from the trading core. FastAPI fills this role here — it exposes the engine state, allows runtime control (start/stop/reset), and serves all analytics to a potential dashboard, without ever being in the critical trading path. The WebSocket live feed mirrors the "blotter view" that traders watch on live desks.

---

## 17. IMPLEMENTATION PHASES

### Phase 1 — Data Foundation + DB Setup
- [ ] `db/base.py` — async SQLAlchemy engine, session factory, `init_db()`
- [ ] All ORM models in `db/models/`
- [ ] `BinanceWSFeed` — WebSocket kline + trade streams + reconnect logic
- [ ] `BinanceRESTFeed` — historical bootstrap (500 candles)
- [ ] `Normalizer` → canonical `Candle` schema
- [ ] `MarketDataStore` — in-memory rolling deque per symbol/TF
- [ ] `CoinGeckoFeed` — 60s polling loop with rate limit guard
- [ ] `AsyncWriteQueue` + DB writer background task

### Phase 2 — FastAPI Shell + Engine Control
- [ ] `main.py` + `app/lifespan.py`
- [ ] `GET /engine/status`, `POST /engine/start|stop`
- [ ] `GET /market/candles` (reads from DB)
- [ ] `WS /ws/live` (broadcasts from EventBus)

### Phase 3 — Indicator Engine
- [ ] EMA, RSI, MACD, ATR, ADX (core set, fast numpy)
- [ ] VWAP (running tick-level accumulator)
- [ ] Bollinger Bands, OBV, Keltner
- [ ] On-chain indicators (NVT, exchange netflow wrappers)
- [ ] `IndicatorPipeline` orchestrator
- [ ] `GET /indicators/{symbol}/{timeframe}/latest`

### Phase 4 — Strategy + Risk
- [ ] `RegimeDetector` (ADX + ATR percentile)
- [ ] `TrendFollowingStrategy`, `MeanReversionStrategy`, `BreakoutStrategy`
- [ ] `CompositeStrategy` with regime gate
- [ ] `RiskGuard` — all circuit breakers + Kelly sizer
- [ ] `GET /signals`

### Phase 5 — Paper Broker + Portfolio
- [ ] `VirtualWallet`, `OrderExecutor`, slippage + fee model
- [ ] `PortfolioManager` + `PositionTracker`
- [ ] `TradeJournal` persistence
- [ ] `GET /portfolio/summary`, `GET /trades`, `GET /portfolio/equity-curve`

### Phase 6 — Analytics Layer
- [ ] `analytics_repo.py` — all complex SQL queries
- [ ] `analytics/performance_stats.py` — Sharpe, Sortino, drawdown, correlation
- [ ] All `/analytics/*` endpoints
- [ ] `GET /analytics/indicators/correlation` (pandas Pearson r)
- [ ] `GET /analytics/rolling` (rolling Sharpe / win-rate decay detection)

### Phase 7 — Composite + Walk-Forward
- [ ] Multi-timeframe confluence gate
- [ ] Rolling parameter evaluation hooks
- [ ] Backtest runner (offline, uses same DB models, different data source)

---

## 18. KEY CONFIGURATION REFERENCE

```python
# config/settings.py  (pydantic BaseSettings — reads from .env)
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # App
    APP_NAME: str = "AlgoBot"
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite+aiosqlite:///./trading_bot.db"

    # Binance
    BINANCE_WS_URL: str = "wss://stream.binance.com:9443/stream"
    BINANCE_REST_URL: str = "https://api.binance.com"
    BINANCE_API_KEY: str = ""           # not needed for public streams
    BINANCE_SECRET: str = ""

    # CoinGecko Terminal
    COINGECKO_BASE_URL: str = "https://api.geckoterminal.com/api/v2"
    COINGECKO_POLL_INTERVAL: int = 60
    COINGECKO_RATE_LIMIT_PER_MIN: int = 25

    # Trading universe
    SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT"]
    TIMEFRAMES: list[str] = ["1m", "5m", "1h"]
    PRIMARY_TF: str = "1h"
    TRIGGER_TF: str = "5m"
    HISTORY_CANDLES: int = 500          # bootstrap candles per symbol/TF

    # Paper broker
    STARTING_BALANCE_USDT: float = 10_000.0
    TAKER_FEE: float = 0.001
    MAKER_FEE: float = 0.0008
    SLIPPAGE_NOISE_STD: float = 0.0002

    # Indicators
    EMA_PERIODS: list[int] = [9, 21, 50, 200]
    RSI_PERIOD: int = 14
    MACD_FAST: int = 12
    MACD_SLOW: int = 26
    MACD_SIGNAL_PERIOD: int = 9
    ATR_PERIOD: int = 14
    ADX_PERIOD: int = 14
    BB_PERIOD: int = 20
    BB_STD: float = 2.0

    # Risk
    MAX_RISK_PER_TRADE_PCT: float = 0.01
    ATR_STOP_MULTIPLIER: float = 1.5
    TP1_R: float = 1.5
    TP2_R: float = 2.5
    MAX_OPEN_POSITIONS: int = 5
    MAX_SINGLE_ASSET_PCT: float = 0.20
    MAX_DAILY_LOSS_PCT: float = 0.03
    MAX_DRAWDOWN_PCT: float = 0.10
    COOLDOWN_AFTER_SL_SEC: int = 300

    class Config:
        env_file = ".env"

settings = Settings()
```

---

## 19. REQUIREMENTS

```
# requirements.txt

# Web framework
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
websockets>=12.0

# Database
sqlalchemy>=2.0.0
aiosqlite>=0.20.0

# Data / math
numpy>=1.26.0
pandas>=2.2.0

# HTTP clients
httpx>=0.27.0
aiohttp>=3.9.0

# Config
pydantic>=2.7.0
pydantic-settings>=2.2.0
python-dotenv>=1.0.0

# Utilities
python-dateutil>=2.9.0
uuid>=1.30

# Dev / testing
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0          # for TestClient
```

---

*End of System Design Reference v2*  
*FastAPI layer is the observability + control plane. SQLite is the statistical memory. The hot trading path (feeds → indicators → strategy → risk → broker) never touches the DB directly — all writes are queued asynchronously. Build in phase order: DB models first, then FastAPI shell, then trading core.*

## 20. LIGHTWEIGHT FRONTEND DASHBOARD SPECIFICATIONS

### 20.1 Architecture

The dashboard is a zero-build Single Page Application delivered as one standalone `frontend/index.html` file. It uses Vue 3 from a CDN for reactive state and rendering, Tailwind CSS from its CDN distribution for utility styling, and Lightweight Charts from a CDN for the live candlestick chart. No npm installation, bundler, transpiler, or build step is required.

### 20.2 Components and Layout

- **Top Bar:** Engine start/stop controls, live engine status, uptime, WebSocket connection state, and the active market regime badge.
- **Summary Cards:** USDT balance, total equity, open-position count, and realized PnL.
- **Live Chart / Blotter:** A real-time candlestick chart beside a scrollable stream of incoming signals, broker fills, and alerts.
- **Open Positions Table:** A reactive table of open trades with symbol, side, quantity, entry/current prices, and dynamic green/red floating PnL coloring.

### 20.3 Data Binding

On startup, the SPA polls the standard REST control and portfolio endpoints, including `/engine/status` and `/portfolio/summary`, then loads recent candles from `/market/candles`. It subscribes directly to `WS /ws/live` for candle, indicator, signal, fill, alert, and order-intent events. WebSocket reconnects use a short exponential backoff so the dashboard remains useful during temporary network or server restarts.