from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from sqlalchemy.exc import IntegrityError

from broker.paper_broker import Fill, PaperBroker
from config.settings import get_settings
from data.data_bus import DataBus, DataEvent
from data.feeds.base_feed import BaseFeed
from data.feeds.binance_ws_feed import BinanceWebSocketFeed
from data.feeds.binance_rest_feed import BinanceRestFeed
from data.feeds.coingecko_feed import CoinGeckoFeed
from data.market_store import MarketStore
from data.normalizer import Candle, OnChainSnapshot
from db.base import AsyncSessionLocal
from db.models.candle import Candle as CandleRow
from db.models.indicator_snapshot import IndicatorSnapshot as IndicatorSnapshotRow
from db.models.onchain_snapshot import OnchainSnapshot as OnchainSnapshotRow
from db.models.order import Order as OrderRow
from db.models.fill import Fill as FillRow
from db.models.position import Position as PositionRow
from db.models.wallet_snapshot import WalletSnapshot as WalletSnapshotRow
from db.models.equity_curve import EquityCurve as EquityCurveRow
from db.models.trade_journal import TradeJournal as TradeJournalRow
from db.models.risk_event import RiskEvent as RiskEventRow
from db.models.signal import Signal as SignalRow
from indicators.base_indicator import IndicatorSnapshot
from indicators.pipeline import IndicatorPipeline
from risk.risk_guard import OrderIntent, RiskGuard
from strategy.base_strategy import Signal
from strategy.breakout import BreakoutStrategy
from strategy.composite import CompositeStrategy
from strategy.mean_reversion import MeanReversionStrategy
from strategy.trend_following import TrendFollowingStrategy
from portfolio.portfolio_manager import PortfolioManager
from portfolio.trade_journal import JournalEntry
from db.repositories.analytics_repo import AnalyticsRepository
from logs.file_logger import get_file_logger
from db.base import AsyncSessionLocal
from db.models.position import Position as PositionRow
from sqlalchemy import select, desc


logger = logging.getLogger(__name__)


class TradingEngine:
    """Own the long-lived feed, hot-path, and cold-path tasks."""

    def __init__(self) -> None:
        settings = get_settings()
        self.symbols = list(settings.symbols)
        self.timeframes = list(settings.timeframes)
        self.market_store = MarketStore(max_window=settings.history_candles)
        self.indicator_pipeline = IndicatorPipeline(self.market_store)
        self.strategy_engine = CompositeStrategy([
            TrendFollowingStrategy(),
            MeanReversionStrategy(),
            BreakoutStrategy(),
        ])
        self.risk_guard = RiskGuard()
        self.paper_broker = PaperBroker()
        self.portfolio_manager = PortfolioManager(self.paper_broker.wallet)
        self.event_bus = DataBus(self.market_store)
        self.db_write_queue = self.event_bus.db_write_queue
        self.feeds: list[BaseFeed] = []
        self._rest_feed: BinanceRestFeed | None = None
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._started_at: float | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._latest_indicators: dict[str, dict[str, IndicatorSnapshot]] = {}
        self.walk_forward_interval_sec = 3600.0
        self.auto_manage_positions = settings.auto_manage_positions
        self._bootstrap_complete = asyncio.Event()
        self._file_logger = get_file_logger("trading_engine")
        self._pending_entries: dict[str, dict] = {}   # symbol → pending entry data
        # di __init__
        self._task_restart_counts: dict[str, int] = {}
        self._max_task_restarts: int = 5
        self._restart_backoff_base: float = 2.0   # detik


    @property
    def running(self) -> bool:
        return self._running

    @property
    def uptime_sec(self) -> float:
        if not self._running or self._started_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self._started_at)

    @property
    def active_symbols(self) -> list[str]:
        return list(self.symbols)

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._running:
                return
            settings = get_settings()
            self.market_store.clear()
            self.event_bus = DataBus(self.market_store, db_queue_size=10_000)
            self._latest_indicators.clear()
            self.db_write_queue = self.event_bus.db_write_queue
            self.feeds = [
                BinanceWebSocketFeed(symbols=self.symbols, timeframes=self.timeframes),
                CoinGeckoFeed(),
            ]
            self._rest_feed = BinanceRestFeed()
            self._running = True
            self._task_restart_counts.clear()
            self._started_at = time.monotonic()
            self._bootstrap_complete.clear()
            await self._restore_open_positions()
            await self._restore_wallet_state()
            self._tasks = [
                asyncio.create_task(self._run_feed(feed), name=f"feed:{feed.__class__.__name__}")
                for feed in self.feeds
            ]
            self._tasks.append(asyncio.create_task(self._bootstrap_history(), name="binance-rest-bootstrap"))
            self._tasks.append(asyncio.create_task(self._run_db_writer(), name="db-writer"))
            # self._tasks.append(asyncio.create_task(self._run_walk_forward(), name="walk-forward-evaluator"))

            for task in self._tasks:
                logger.info("Started task: %s", task.get_name())
                task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        name = task.get_name()

        if task.cancelled():
            logger.warning("Task cancelled: %s", name)
            return

        exc = task.exception()
        if exc is None:
            logger.info("Task finished normally: %s", name)
            return

        # Task gagal
        logger.error("Task failed: %s – %s", name, exc)

        if not self._running:
            return

        # Hanya restart task kritis
        critical_prefixes = ("feed:", "db-writer")
        is_critical = any(name.startswith(p) for p in critical_prefixes)

        if not is_critical:
            logger.warning("Non-critical task died (%s). Not restarting.", name)
            return

        # Hitung berapa kali sudah di-restart
        count = self._task_restart_counts.get(name, 0) + 1
        self._task_restart_counts[name] = count

        if count > self._max_task_restarts:
            logger.critical(
                "Task %s failed %d times. Hard-stopping engine.",
                name, count,
            )
            # Jadwalkan stop di event loop (karena kita di dalam callback)
            asyncio.create_task(self.stop())
            return

        backoff = self._restart_backoff_base * (2 ** (count - 1))
        logger.warning(
            "Scheduling restart of %s in %.1fs (attempt %d/%d)",
            name, backoff, count, self._max_task_restarts,
        )
        asyncio.create_task(self._restart_task(name, backoff))

    async def _restart_task(self, name: str, delay: float) -> None:
        await asyncio.sleep(delay)

        if not self._running:
            logger.info("Engine stopped – skip restart of %s", name)
            return

        logger.info("Restarting task: %s", name)

        try:
            if name.startswith("feed:"):
                # Cari class feed yang sesuai
                feed_cls_name = name.split(":", 1)[1]
                feed = next(
                    (f for f in self.feeds if f.__class__.__name__ == feed_cls_name),
                    None,
                )
                if feed is None:
                    # Buat ulang feed jika hilang
                    if feed_cls_name == "BinanceWebSocketFeed":
                        feed = BinanceWebSocketFeed(
                            symbols=self.symbols,
                            timeframes=self.timeframes,
                        )
                        self.feeds.append(feed)
                    elif feed_cls_name == "CoinGeckoFeed":
                        feed = CoinGeckoFeed()
                        self.feeds.append(feed)
                    else:
                        logger.error("Unknown feed type for restart: %s", feed_cls_name)
                        return

                new_task = asyncio.create_task(
                    self._run_feed(feed),
                    name=name,
                )

            elif name == "db-writer":
                new_task = asyncio.create_task(
                    self._run_db_writer(),
                    name=name,
                )

            else:
                logger.error("No restart handler for task: %s", name)
                return

            # Ganti task lama di list
            self._tasks = [t for t in self._tasks if t.get_name() != name]
            self._tasks.append(new_task)
            new_task.add_done_callback(self._task_done)

            logger.info("Task %s successfully restarted", name)

        except Exception as e:
            logger.exception("Failed to restart task %s: %s", name, e)
            # Kalau restart sendiri gagal, anggap sebagai failure lagi
            self._task_restart_counts[name] = self._task_restart_counts.get(name, 0) + 1
        

    async def switch_timeframe(self, timeframe: str) -> None:
        allowed = {"1m", "5m", "15m", "1h"}
        if timeframe not in allowed:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        was_running = self._running
        if was_running:
            await self.stop()
        self.timeframes = [timeframe]
        if was_running:
            await self.start()

    async def _restore_open_positions(self) -> None:


        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(PositionRow).where(PositionRow.status == "OPEN")
            )
            rows = result.scalars().all()

        self.portfolio_manager.position_tracker.restore_positions(rows)

        # Optional but useful: also restore realized PnL total
        # (you can sum CLOSED positions if you want exact number)

    async def _restore_wallet_state(self) -> None:

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(WalletSnapshotRow)
                .order_by(desc(WalletSnapshotRow.timestamp))
                .limit(1)
            )
            row = result.scalar_one_or_none()

        if row is None:
            self._file_logger.info("No wallet snapshot found – starting with default balance")
            return

        self.portfolio_manager.wallet.cash = row.usdt_balance
        # Optional: restore realized PnL if you store it
        # self.portfolio_manager.realized_pnl_total = ...

        self._file_logger.info(
            "Restored wallet: cash=%.2f | equity=%.2f",
            row.usdt_balance, row.total_equity
        )

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if not self._running and not self._tasks:
                return
            self._running = False
            for feed in self.feeds:
                await feed.close()
            tasks = self._tasks
            self._tasks = []
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self.feeds = []
            if self._rest_feed is not None:
                await self._rest_feed.close()
                self._rest_feed = None
            self._started_at = None

    async def _bootstrap_history(self) -> None:
        if self._rest_feed is None:
            self._bootstrap_complete.set()
            return
        try:
            candles = await self._rest_feed.bootstrap(self.symbols, self.timeframes)
            for candle in candles:
                if self._running:
                    self.market_store.append(candle)
            logger.info("Binance REST bootstrap loaded %d candles", len(candles))
            logger.info("Warm-up is ready")
            logger.info(
                "Bootstrap complete: %d candles loaded for %s %s",
                len(candles), self.symbols, self.timeframes,
            )
            self._bootstrap_complete.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Binance REST bootstrap unavailable: %s", exc)
            self._bootstrap_complete.set()

    async def _publish_hold_decision(self, candle: Candle, reason: str = "NON_PRIMARY_TF") -> None:
        decision_event = {
            "type": "candle_decision",
            "ts": candle.open_time,
            "payload": {
                "candle_close": candle.close,
                "symbol": candle.symbol,
                "timeframe": candle.timeframe,
                "direction": "HOLD",
                "confidence": 0.0,
                "regime": None,
                "risk_status": reason,
                "rejection_reason": reason,
            },
        }
        await self.event_bus.publish(decision_event)

    async def _try_fill_pending_entry(self, symbol: str, price: float) -> None:
        pending = self._pending_entries.pop(symbol, None)
        if pending is None:
            return

        intent: OrderIntent = pending["intent"]
        signal: Signal = pending["signal"]

        self._file_logger.info(
            "FILLING PENDING ENTRY %s %s at next price=%.2f (signal was on closed candle)",
            symbol, intent.direction, price,
        )

        fill = await self.paper_broker.submit(intent, price=price, order_type="MARKET")
        if fill is None:
            self._file_logger.warning("Pending entry submit returned None for %s", symbol)
            return

        self.portfolio_manager.update(
            fill,
            stop_loss_price=intent.stop_loss_price,
            tp1_price=intent.tp1_price,
            tp2_price=intent.tp2_price,
        )

        journal_entry = self.portfolio_manager.journal.record(signal, intent, fill)
        await self.event_bus.publish(fill)
        if journal_entry:
            await self.event_bus.publish(journal_entry)

    async def _run_feed(self, feed: BaseFeed) -> None:
        await feed.connect()
        logger.info("Feed connected: %s", feed.__class__.__name__)
        async for event in feed.events():
            if not self._running:
                logger.warning("Engine not running – dropping event")
                return

            try:
                if isinstance(event, dict) and event.get("event_type") == "trade":
                    await self._on_tick(str(event["symbol"]), float(event["price"]), None, high=None, low=None, is_raw_tick=True)
                elif isinstance(event, Candle):
                    logger.info(
                        "Candle event: %s %s closed=%s close=%.2f t=%s",
                        event.symbol,
                        event.timeframe,
                        event.is_closed,
                        event.close,
                        event.open_time,
                    )
                    if event.is_closed:
                        logger.info(">>> ABOUT TO DISPATCH closed candle %s %s", event.symbol, event.timeframe)
                        try:
                            await self.event_bus.publish(event)
                            await self._on_candle_closed(event)
                            logger.info(">>> FINISHED _on_candle_closed %s %s", event.symbol, event.timeframe)
                        except Exception:
                            logger.exception(
                                "FAILED closed candle %s %s",
                                event.symbol,
                                event.timeframe,
                            )
                    else:
                        # Forming candle → price update / exits only
                        await self._on_tick(event.symbol, event.close, event.timeframe, high=event.high, low=event.low,)

                elif isinstance(event, OnChainSnapshot):
                    await self.event_bus.publish(event)

            finally:
                if hasattr(feed, "events_queue") and hasattr(feed.events_queue, "task_done"):
                    feed.events_queue.task_done()

    async def _on_tick(self, symbol: str, price: float, timeframe: str | None, high: float | None = None, low: float | None = None, is_raw_tick: bool = False,) -> None:
        self.portfolio_manager.mark_price(symbol, price)
        if self.auto_manage_positions:
            await self._execute_exits(symbol, price, timeframe, high=high, low=low, is_raw_tick=is_raw_tick,)

        await self._try_fill_pending_entry(symbol, price)

    async def _on_candle_closed(self, candle: Candle) -> None:
        logger.info("=== ENTER _on_candle_closed %s %s ===", candle.symbol, candle.timeframe)

        # ── Gate: bootstrap still running ────────────────────────────────
        if not self._bootstrap_complete.is_set():
            self.market_store.append(candle)
            return

        settings = get_settings()
        primary_tf = settings.primary_tf

        # ── Auto-exits on this closed candle ─────────────────────────────


        # ── Indicators ───────────────────────────────────────────────────
        logger.info("ON_CLOSED enter %s %s", candle.symbol, candle.timeframe)
        snapshot = self.indicator_pipeline.compute(candle.symbol, candle.timeframe)
        logger.info("ON_CLOSED snapshot=%s", snapshot is not None)
        if snapshot is None:
            logger.info(
                "Indicator snapshot is None for %s %s — not enough candles yet",
                candle.symbol, candle.timeframe,
            )
            return

        logger.debug(
            "Indicators %s %s | ema9=%.2f ema50=%.2f ema200=%.2f rsi=%.1f "
            "macd_hist=%.4f atr=%.4f adx=%.1f",
            candle.symbol, candle.timeframe,
            snapshot.ema_9 or 0, snapshot.ema_50 or 0, snapshot.ema_200 or 0,
            snapshot.rsi_14 or 0, snapshot.macd_hist or 0,
            snapshot.atr_14 or 0, getattr(snapshot, "adx_14", 0) or 0,
        )

        self._latest_indicators.setdefault(candle.symbol, {})[candle.timeframe] = snapshot
        await self.event_bus.publish(snapshot)


        if candle.timeframe!= primary_tf:
            logger.info(
                "non-Primary TF Closed (%s) → indicators updated, skip signal generation",
                candle.timeframe,
            )
            
            await self._publish_hold_decision(candle, reason="NON_PRIMARY_TF")
            return

        logger.info("PRIMARY TF closed → running full strategy evaluation")

        # ── Current position (if any) ────────────────────────────────────
        current_position = next(
            (
                p for p in self.portfolio_manager.position_tracker.open_positions()
                if p.symbol == candle.symbol
            ),
            None,
        )

        # ── Strategy evaluation (never let it kill the candle path) ──────
        try:
            signal = self.strategy_engine.evaluate(
                self._latest_indicators[candle.symbol],
                position=current_position,
            )
            if not getattr(signal, "signal_uuid", None):
                signal.signal_uuid = str(uuid.uuid4())
        except Exception as exc:
            logger.exception(
                "Strategy evaluation failed for %s %s: %s",
                candle.symbol, candle.timeframe, exc,
            )
            signal = Signal(
                symbol=candle.symbol,
                timeframe=candle.timeframe,
                direction="HOLD",
                confidence=0.0,
                strategy_id="error",
                signal_uuid=str(uuid.uuid4()),
                market_regime=getattr(snapshot, "market_regime", "UNKNOWN") or "UNKNOWN",
                reasoning={"error": str(exc)},
            )

        self._file_logger.info(
            "POST-STRATEGY %s %s | direction=%s", 
            candle.symbol,
            candle.timeframe,
            signal.direction,
        )

        # Always publish the signal (even HOLD / error)
        await self.event_bus.publish(signal)

        # ── Prepare decision fields ──────────────────────────────────────
        intent: OrderIntent | None = None
        risk_status = "SKIPPED"
        rejection_reason = None
        stop_loss = None
        tp1 = None
        tp2 = None

        # ── EXIT signal from strategy ────────────────────────────────
        if signal.direction == "EXIT" and current_position is not None:
            self._file_logger.info(
                "Strategy triggered EXIT for %s due to trend reversal.",
                candle.symbol,
            )
            # Sanity check
            if current_position.status != "OPEN":
                self._file_logger.warning(
                    "EXIT ignored – position %s already %s",
                    current_position.position_uuid, current_position.status,
                )
                return  # atau return dari blok ini

            if current_position.quantity <= 0:
                self._file_logger.warning(
                    "EXIT ignored – invalid quantity %.6f for %s",
                    current_position.quantity, current_position.symbol,
                )
                return

            intent = OrderIntent(
                approved=True,
                signal_uuid=signal.signal_uuid,
                symbol=candle.symbol,
                direction="SELL" if current_position.side == "LONG" else "BUY",
                quantity=current_position.quantity,
                entry_price=candle.close,
            )

            # Optional: log audit
            self._file_logger.info(
                "STRATEGY EXIT approved | %s %s qty=%.6f",
                current_position.symbol, current_position.side, current_position.quantity,
            )
            risk_status = "EXIT_TRIGGERED"
            await self.event_bus.publish(intent)

            fill = await self.paper_broker.submit(
                intent, price=candle.close, order_type="MARKET"
            )
            if fill is not None:
                self.portfolio_manager.update(fill)
                if hasattr(self.portfolio_manager.journal, "record_exit"):
                    journal_entry = self.portfolio_manager.journal.record_exit(
                        current_position, fill, signal
                    )
                    if journal_entry:
                        await self.event_bus.publish(journal_entry)
                await self.event_bus.publish(fill)

        # ── Standard ENTRY (BUY / SELL) ──────────────────────────────
        elif signal.direction in ("BUY", "SELL"):
            intent = self.risk_guard.evaluate(
                signal,
                {
                    "entry_price": candle.close,
                    "atr": snapshot.atr_14 or 0.0,
                    "balance_usdt": self.portfolio_manager.summary()["balance_usdt"],
                    "open_positions": self.portfolio_manager.summary()["open_positions"],
                },
                snapshot,
            )

            if intent.approved:
                risk_status = "APPROVED"
                self._file_logger.info(
                    "RiskGuard APPROVED: %s %s qty=%.6f entry=%.2f sl=%.2f tp1=%.2f",
                    intent.symbol,
                    intent.direction,
                    intent.quantity,
                    intent.entry_price or 0,
                    intent.stop_loss_price or 0,
                    intent.tp1_price or 0,
                )
            else:
                risk_status = "REJECTED"
                rejection_reason = intent.rejection_reason
                self._file_logger.info(
                    "RiskGuard REJECTED: %s %s reason=%s | balance_usdt=%.2f atr=%.4f entry=%.2f",
                    intent.symbol,
                    intent.direction,
                    intent.rejection_reason,
                    self.portfolio_manager.summary().get("balance_usdt", 0),
                    snapshot.atr_14 or 0,
                    candle.close,
                )

            stop_loss = intent.stop_loss_price
            tp1 = intent.tp1_price
            tp2 = intent.tp2_price

            await self.event_bus.publish(intent)

            if intent.approved:
                if intent.stop_loss_price is None or intent.tp1_price is None:
                    intent.approved = False
                    intent.rejection_reason = "missing_sl_or_tp"
                    risk_status = "REJECTED"
                    rejection_reason = intent.rejection_reason
                    self._file_logger.warning(
                        "RiskGuard forced REJECT: missing SL/TP for %s", intent.symbol
                    )
                else:
                    risk_status = "APPROVED"
                    # ✅ JANGAN submit sekarang. Simpan sebagai pending (Issue 2)
                    self._pending_entries[candle.symbol] = {
                        "intent": intent,
                        "signal": signal,
                        "created_at": candle.open_time,
                    }
                    self._file_logger.info(
                        "ENTRY QUEUED (pending next price) %s %s qty=%.6f",
                        intent.symbol, intent.direction, intent.quantity,
                    )
            else:
                risk_status = "REJECTED"
                rejection_reason = intent.rejection_reason

            stop_loss = intent.stop_loss_price
            tp1 = intent.tp1_price
            tp2 = intent.tp2_price
            await self.event_bus.publish(intent)
                    
 #               self._file_logger.info("ABOUT TO SUBMIT: approved=%s price=%s qty=%s", 
 #                           intent.approved, candle.close, intent.quantity)
 #               fill = await self.paper_broker.submit(intent, price=candle.close)
 #               self._file_logger.info("SUBMIT RESULT: fill is None = %s", fill is None)
 #               if fill is not None:
 #                   self._file_logger.info("FILL CREATED: %s %s qty=%.6f", fill.symbol, fill.side, fill.filled_qty)
 #                   self.portfolio_manager.update(
 #                       fill,
 #                       stop_loss_price=intent.stop_loss_price,
 #                       tp1_price=intent.tp1_price,
 #                       tp2_price=intent.tp2_price,
 #                   )
 #                   journal_entry = self.portfolio_manager.journal.record(
 #                       signal, intent, fill
 #                   )
 #                   await self.event_bus.publish(fill)
 #                   await self.event_bus.publish(journal_entry)

        # ── Always emit candle_decision (frontend + history) ─────────────
        decision_event = {
            "type": "candle_decision",
            "ts": candle.open_time,
            "payload": {
                "candle_close": candle.close,
                "symbol": candle.symbol,
                "timeframe": candle.timeframe,
                "direction": signal.direction,
                "confidence": signal.confidence,
                "regime": signal.market_regime,
                "components": signal.reasoning.get("components", {}) if isinstance(signal.reasoning, dict) else {},
                "htf_bias": signal.reasoning.get("htf_bias") if isinstance(signal.reasoning, dict) else None,
                "risk_status": risk_status,
                "rejection_reason": rejection_reason,
                "stop_loss": stop_loss,
                "tp1": tp1,
                "tp2": tp2,
            },
        }
        await self.event_bus.publish(decision_event)

    async def _execute_exits(self, symbol: str, price: float, timeframe: str | None, high: float | None = None, low: float | None = None, is_raw_tick: bool = False,) -> bool:
        exits = self.portfolio_manager.check_exits(symbol, price, timeframe or "", high=high, low=low, is_raw_tick=is_raw_tick,)
        self._file_logger.info("check_exits returned %d signals for %s @ %.2f", len(exits), symbol, price)
        if not exits:
            return False

        for signal in exits:
            position = next(
                (
                    item
                    for item in self.portfolio_manager.position_tracker.open_positions()
                    if item.position_uuid == signal.reasoning.get("position_uuid")
                ),
                None,
            )
            if position is None or position.status != "OPEN":
                continue
            if position.quantity <= 0:
                self._file_logger.warning("Skip exit – bad quantity on %s", position.position_uuid)
                continue

            intent = OrderIntent(
                approved=True,
                signal_uuid=str(uuid.uuid4()),
                symbol=symbol,
                direction="SELL" if position.side == "LONG" else "BUY",
                quantity=position.quantity,
                entry_price=price,
            )
            await self.event_bus.publish(signal)
            await self.event_bus.publish(intent)

            

            fill = await self.paper_broker.submit(intent, price=price, order_type="MARKET")
            if fill is not None:
                self.portfolio_manager.update(fill)
                if hasattr(self.portfolio_manager.journal, "record_exit"):
                    journal_entry = self.portfolio_manager.journal.record_exit(
                        position, fill, signal
                    )
                    if journal_entry:
                        await self.event_bus.publish(journal_entry)
                await self.event_bus.publish(fill)
        return True

    async def _run_walk_forward(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.walk_forward_interval_sec)
                if self._running:
                    await self._evaluate_parameters_hook()
            except asyncio.CancelledError:
                raise

    async def _evaluate_parameters_hook(self) -> list[dict]:
        """Adjust strategy weights from recent 30-day metrics, then normalize."""
        async with AsyncSessionLocal() as session:
            metrics = await AnalyticsRepository(session).rolling_strategy_metrics(days=30)

        for metric in metrics:
            sharpe = float(metric.get("sharpe", 0.0))
            win_rate = float(metric.get("win_rate", 0.0))
            strategy_id = str(metric["strategy_id"])

            if sharpe < 0.0 or win_rate < 0.40:
                self.strategy_engine.adjust_strategy_weight(strategy_id, 0.75)
            elif sharpe >= 0.5 and win_rate >= 0.50:
                self.strategy_engine.adjust_strategy_weight(strategy_id, 1.10)

        weights = self.strategy_engine.strategy_weights
        total_weight = sum(weights.values())

        if total_weight > 0:
            for sid in weights:
                weights[sid] = (weights[sid] / total_weight) * 0.90

        for sid in weights:
            if weights[sid] < 0.05:
                weights[sid] = 0.05

        return metrics

    async def _run_db_writer(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(self.db_write_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self._persist_event(event)
            finally:
                self.db_write_queue.task_done()

    async def _persist_event(self, event: DataEvent) -> None:
        payload = event.payload

        # decision_event is a plain dict → ignore for DB (live only)
        if not isinstance(
            payload,
            (Candle, OnChainSnapshot, IndicatorSnapshot, Signal, OrderIntent, Fill, JournalEntry),
        ):
            logger.debug("DB writer ignoring unhandled payload type: %s", type(payload).__name__)
            return

        async with AsyncSessionLocal() as session:
            try:
                if isinstance(payload, Candle):
                    session.add(
                        CandleRow(
                            symbol=payload.symbol,
                            timeframe=payload.timeframe,
                            open_time=payload.open_time,
                            open=payload.open,
                            high=payload.high,
                            low=payload.low,
                            close=payload.close,
                            volume=payload.volume,
                            quote_volume=payload.quote_volume,
                            trades=payload.trades,
                            taker_buy_vol=payload.taker_buy_vol,
                            created_at=event.timestamp,
                        )
                    )
                elif isinstance(payload, IndicatorSnapshot):
                    session.add(IndicatorSnapshotRow(**payload.as_dict()))
                elif isinstance(payload, Signal):
                    session.add(
                        SignalRow(
                            signal_uuid=payload.signal_uuid,
                            symbol=payload.symbol,
                            timeframe=payload.timeframe,
                            timestamp=payload.timestamp,
                            direction=payload.direction,
                            confidence=payload.confidence,
                            strategy_id=payload.strategy_id,
                            reasoning=json.dumps(payload.reasoning or {}),
                            market_regime=payload.market_regime,
                            created_at=event.timestamp,
                        )
                    )
                elif isinstance(payload, OrderIntent):
                    session.add(
                        RiskEventRow(
                            signal_uuid=payload.signal_uuid,
                            symbol=payload.symbol,
                            timestamp=event.timestamp,
                            decision="APPROVED" if payload.approved else "REJECTED",
                            rejection_reason=payload.rejection_reason,
                            position_size=payload.quantity,
                            risk_pct=payload.risk_pct,
                            stop_loss_price=payload.stop_loss_price,
                            tp1_price=payload.tp1_price,
                            tp2_price=payload.tp2_price,
                            created_at=event.timestamp,
                        )
                    )
                elif isinstance(payload, Fill):
                    order = self.paper_broker.orders.get(payload.order_uuid)
                    session.add(
                        FillRow(
                            fill_uuid=payload.fill_uuid,
                            order_uuid=payload.order_uuid,
                            symbol=payload.symbol,
                            side=payload.side,
                            filled_qty=payload.filled_qty,
                            avg_price=payload.avg_price,
                            fee=payload.fee,
                            fee_asset=payload.fee_asset,
                            slippage_pct=payload.slippage_pct,
                            timestamp=payload.timestamp,
                            created_at=event.timestamp,
                        )
                    )
                    if order is not None:
                        session.add(
                            OrderRow(
                                order_uuid=order.order_uuid,
                                signal_uuid=order.signal_uuid,
                                symbol=order.symbol,
                                order_type=order.order_type,
                                side=order.side,
                                quantity=order.quantity,
                                limit_price=order.limit_price,
                                stop_price=order.stop_price,
                                status=order.status,
                                created_at=order.created_at,
                                updated_at=event.timestamp,
                            )
                        )
# Find the position that this fill belongs to (entry or exit)
                    position = next(
                        (
                            item
                            for item in list(self.portfolio_manager.position_tracker.positions())
                            + list(self.portfolio_manager.position_tracker.closed)
                            if item.entry_fill_uuid == payload.fill_uuid
                            or item.exit_fill_uuid == payload.fill_uuid
                        ),
                        None,
                    )
                    if position is not None:
                        # Try to load existing row
                        result = await session.execute(
                            select(PositionRow).where(PositionRow.position_uuid == position.position_uuid)
                        )
                        row = result.scalar_one_or_none()
                        if row is None:
                            session.add(
                                PositionRow(
                                    position_uuid=position.position_uuid,
                                    symbol=position.symbol,
                                    side=position.side,
                                    status=position.status,
                                    entry_fill_uuid=position.entry_fill_uuid,
                                    exit_fill_uuid=position.exit_fill_uuid,
                                    entry_price=position.entry_price,
                                    exit_price=position.exit_price,
                                    quantity=position.quantity,
                                    realized_pnl=position.realized_pnl,
                                    total_fees=position.total_fees,
                                    entry_time=position.entry_time,
                                    exit_time=payload.timestamp if position.status == "CLOSED" else None,
                                    stop_loss_price=position.stop_loss_price,   # ← add
                                    tp1_price=position.tp1_price,               # ← add
                                    tp2_price=position.tp2_price,               # ← add
                                    created_at=event.timestamp,
                                )
                            )
                        else:
                            # Update existing row
                            row.status = position.status
                            row.exit_fill_uuid = position.exit_fill_uuid
                            row.exit_price = position.exit_price
                            row.realized_pnl = position.realized_pnl
                            row.total_fees = position.total_fees
                            row.exit_time = payload.timestamp if position.status == "CLOSED" else None
                            
                    summary = self.portfolio_manager.summary()
                    point = self.portfolio_manager.performance.snapshot(
                        self.portfolio_manager.prices, payload.timestamp
                    )
                    session.add(
                        WalletSnapshotRow(
                            timestamp=point.timestamp,
                            usdt_balance=summary["balance_usdt"],
                            total_equity=summary["total_equity"],
                            open_positions=summary["open_positions"],
                            created_at=event.timestamp,
                        )
                    )
                    session.add(
                        EquityCurveRow(
                            timestamp=point.timestamp,
                            equity=point.equity,
                            drawdown_pct=point.drawdown_pct,
                            peak_equity=point.peak_equity,
                            created_at=event.timestamp,
                        )
                    )
                elif isinstance(payload, JournalEntry):
                    position = (
                        next(
                            (
                                item
                                for item in self.portfolio_manager.position_tracker.positions()
                                if item.entry_fill_uuid == payload.fill.fill_uuid
                            ),
                            None,
                        )
                        if payload.fill
                        else None
                    )
                    if position is not None:
                        session.add(
                            TradeJournalRow(
                                position_uuid=position.position_uuid,
                                symbol=payload.signal.symbol,
                                strategy_id=payload.signal.strategy_id,
                                market_regime=payload.signal.market_regime,
                                entry_time=position.entry_time,
                                entry_price=position.entry_price,
                                entry_signal_direction=payload.signal.direction,
                                entry_confidence=payload.signal.confidence,
                                entry_reasoning=json.dumps(payload.signal.reasoning or {}),
                                fees_usdt=payload.fill.fee if payload.fill else None,
                                slippage_pct=payload.fill.slippage_pct if payload.fill else None,
                                created_at=event.timestamp,
                            )
                        )
                elif isinstance(payload, OnChainSnapshot):
                    session.add(
                        OnchainSnapshotRow(
                            symbol=payload.symbol,
                            chain=payload.chain,
                            timestamp=payload.timestamp,
                            pool_tvl_usd=payload.pool_tvl_usd,
                            pool_volume_24h=payload.pool_volume_24h,
                            exchange_netflow_24h=payload.exchange_netflow_24h,
                            nvt_ratio=payload.nvt_ratio,
                            active_addresses_24h=payload.active_addresses_24h,
                            top10_holder_pct=payload.top10_holder_pct,
                            created_at=payload.created_at,
                        )
                    )
                else:
                    logger.warning("Unhandled DB payload type: %s", type(payload).__name__)
                    return

                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.debug(
                    "Skipped duplicate / integrity error for topic=%s type=%s",
                    getattr(event, "topic", "?"),
                    type(payload).__name__,
                )