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

logger = logging.getLogger(__name__)


class TradingEngine:
    """Own the long-lived feed, hot-path, and cold-path tasks."""

    def __init__(self) -> None:
        settings = get_settings()
        self.symbols = list(settings.symbols)
        self.timeframes = list(settings.timeframes)
        self.market_store = MarketStore(max_window=settings.history_candles)
        self.indicator_pipeline = IndicatorPipeline(self.market_store)
        self.strategy_engine = CompositeStrategy([TrendFollowingStrategy(), MeanReversionStrategy(), BreakoutStrategy()])
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
            self._started_at = time.monotonic()
            self._tasks = [
                asyncio.create_task(self._run_feed(feed), name=f"feed:{feed.__class__.__name__}")
                for feed in self.feeds
            ]
            self._tasks.append(asyncio.create_task(self._bootstrap_history(), name="binance-rest-bootstrap"))
            self._tasks.append(asyncio.create_task(self._run_db_writer(), name="db-writer"))
            self._tasks.append(asyncio.create_task(self._run_walk_forward(), name="walk-forward-evaluator"))

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
            return
        try:
            candles = await self._rest_feed.bootstrap(self.symbols, self.timeframes)
            for candle in candles:
                if self._running:
                    await self.event_bus.publish(candle)
            logger.info("Binance REST bootstrap loaded %d candles", len(candles))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Binance REST bootstrap unavailable: %s", exc)

    async def _run_feed(self, feed: BaseFeed) -> None:
        await feed.connect()
        async for event in feed.events():
            if not self._running:
                return
            await self.event_bus.publish(event)
            if isinstance(event, dict) and event.get("event_type") == "trade":
                await self._on_tick(str(event["symbol"]), float(event["price"]), self.timeframes[0])
            elif isinstance(event, Candle) and event.is_closed:
                await self._on_candle_closed(event)

    async def _on_tick(self, symbol: str, price: float, timeframe: str) -> None:
        self.portfolio_manager.mark_price(symbol, price)
        if self.auto_manage_positions:
            await self._execute_exits(symbol, price, timeframe)

    async def _on_candle_closed(self, candle: Candle) -> None:
        if self.auto_manage_positions and await self._execute_exits(candle.symbol, candle.close, candle.timeframe):
            return
        snapshot = self.indicator_pipeline.compute(candle.symbol, candle.timeframe)
        if snapshot is not None:
            self._latest_indicators.setdefault(candle.symbol, {})[candle.timeframe] = snapshot
            await self.event_bus.publish(snapshot)
            signal = self.strategy_engine.evaluate(self._latest_indicators[candle.symbol])
            if not signal.signal_uuid:
                signal.signal_uuid = str(uuid.uuid4())
            await self.event_bus.publish(signal)
            intent = self.risk_guard.evaluate(
                signal,
                {
                    "entry_price": candle.close,
                    "atr": snapshot.atr_14 or 0.0,
                    "equity": self.portfolio_manager.summary()["total_equity"],
                    "open_positions": self.portfolio_manager.summary()["open_positions"],
                },
                snapshot,
            )
            await self.event_bus.publish(intent)
            if intent.approved:
                fill = await self.paper_broker.submit(intent, price=candle.close)
                if fill is not None:
                    self.portfolio_manager.update(
                        fill,
                        stop_loss_price=intent.stop_loss_price,
                        tp1_price=intent.tp1_price,
                        tp2_price=intent.tp2_price,
                    )
                    journal_entry = self.portfolio_manager.journal.record(signal, intent, fill)
                    await self.event_bus.publish(fill)
                    await self.event_bus.publish(journal_entry)

    async def _execute_exits(self, symbol: str, price: float, timeframe: str) -> bool:
        exits = self.portfolio_manager.check_exits(symbol, price, timeframe)
        if not exits:
            return False
        for signal in exits:
            position = next(
                (item for item in self.portfolio_manager.position_tracker.open_positions()
                 if item.position_uuid == signal.reasoning.get("position_uuid")),
                None,
            )
            if position is None:
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
        """Reduce strategy weights when recent 30-day metrics fall below baseline."""
        async with AsyncSessionLocal() as session:
            metrics = await AnalyticsRepository(session).rolling_strategy_metrics(days=30)
        for metric in metrics:
            if float(metric.get("sharpe", 0.0)) < 0.0 or float(metric.get("win_rate", 0.0)) < 0.40:
                self.strategy_engine.adjust_strategy_weight(str(metric["strategy_id"]), 0.75)
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
        if not isinstance(payload, (Candle, OnChainSnapshot, IndicatorSnapshot, Signal, OrderIntent, Fill, JournalEntry)):
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
                            reasoning=json.dumps(payload.reasoning),
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
                    position = next((item for item in self.portfolio_manager.position_tracker.positions() if item.entry_fill_uuid == payload.fill_uuid or item.exit_fill_uuid == payload.fill_uuid), None)
                    if position is not None:
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
                                created_at=event.timestamp,
                            )
                        )
                    summary = self.portfolio_manager.summary()
                    point = self.portfolio_manager.performance.snapshot(self.portfolio_manager.prices, payload.timestamp)
                    session.add(WalletSnapshotRow(timestamp=point.timestamp, usdt_balance=summary["balance_usdt"], total_equity=summary["total_equity"], open_positions=summary["open_positions"], created_at=event.timestamp))
                    session.add(EquityCurveRow(timestamp=point.timestamp, equity=point.equity, drawdown_pct=point.drawdown_pct, peak_equity=point.peak_equity, created_at=event.timestamp))
                elif isinstance(payload, JournalEntry):
                    position = next((item for item in self.portfolio_manager.position_tracker.positions() if item.entry_fill_uuid == payload.fill.fill_uuid), None) if payload.fill else None
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
                                entry_reasoning=json.dumps(payload.signal.reasoning),
                                fees_usdt=payload.fill.fee if payload.fill else None,
                                slippage_pct=payload.fill.slippage_pct if payload.fill else None,
                                created_at=event.timestamp,
                            )
                        )
                else:
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
                await session.commit()
            except IntegrityError:
                await session.rollback()
                logger.debug("Skipped duplicate market event for %s", event.topic)
