from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from data.market_store import MarketStore
from data.normalizer import Candle, OnChainSnapshot, normalize_market_event
from indicators.base_indicator import IndicatorSnapshot
from broker.paper_broker import Fill
from portfolio.trade_journal import JournalEntry
from risk.risk_guard import OrderIntent
from strategy.base_strategy import Signal


@dataclass(slots=True, frozen=True)
class DataEvent:
    topic: str
    payload: Any
    timestamp: int


def _topic_for(payload: Any) -> str:
    if isinstance(payload, Candle):
        return "candle"
    if isinstance(payload, OnChainSnapshot):
        return "onchain"
    if isinstance(payload, IndicatorSnapshot):
        return "indicator"
    if isinstance(payload, Signal):
        return "signal"
    if isinstance(payload, OrderIntent):
        return "order_intent"
    if isinstance(payload, Fill):
        return "fill"
    if isinstance(payload, JournalEntry):
        return "trade_journal"
    if isinstance(payload, dict):
        return str(payload.get("event_type", "market"))
    return "market"


class DataBus:
    def __init__(
        self,
        market_store: MarketStore | None = None,
        *,
        db_queue_size: int = 10_000,
    ) -> None:
        self.market_store = market_store or MarketStore()
        self.db_write_queue: asyncio.Queue[DataEvent] = asyncio.Queue(maxsize=db_queue_size)
        self._channels: dict[str, set[asyncio.Queue[DataEvent]]] = defaultdict(set)
        self.dropped_db_events = 0
        self.dropped_subscriber_events = 0

    def subscribe(self, topic: str, *, maxsize: int = 1_000) -> asyncio.Queue[DataEvent]:
        queue: asyncio.Queue[DataEvent] = asyncio.Queue(maxsize=maxsize)
        self._channels[topic].add(queue)
        return queue

    def unsubscribe(self, topic: str, queue: asyncio.Queue[DataEvent]) -> None:
        self._channels[topic].discard(queue)

    async def publish(self, event: Any, payload: Any | None = None) -> DataEvent:
        """Dispatch an event without waiting on cold-path or subscriber queues.

        ``publish(topic, payload)`` is accepted for compatibility with the original
        stub, while new callers should pass only the payload.
        """
        if isinstance(event, str) and payload is not None:
            topic = event
            raw_payload = payload
        else:
            raw_payload = event
            topic = _topic_for(raw_payload)

        normalized = self._normalize(raw_payload)
        if isinstance(normalized, Candle):
            self.market_store.append(normalized)
        elif isinstance(normalized, OnChainSnapshot):
            self.market_store.append_onchain(normalized)

        data_event = DataEvent(
            topic=topic,
            payload=normalized,
            timestamp=int(datetime.now(timezone.utc).timestamp() * 1000),
        )
        try:
            self.db_write_queue.put_nowait(data_event)
        except asyncio.QueueFull:
            self.dropped_db_events += 1
        subscriber_queues = tuple(self._channels.get(topic, ())) + tuple(self._channels.get("*", ()))
        for queue in subscriber_queues:
            try:
                queue.put_nowait(data_event)
            except asyncio.QueueFull:
                self.dropped_subscriber_events += 1
        return data_event

    @staticmethod
    def _normalize(event: Any) -> Any:
        if isinstance(event, (Candle, OnChainSnapshot, IndicatorSnapshot, Signal, OrderIntent, Fill, JournalEntry)):
            return event
        if isinstance(event, dict):
            # Known non-market trade events pass through unchanged
            if event.get("event_type") == "trade":
                return event
            # Try market-event normalisation; fall back to the original payload
            # for any other dict (decisions, signals, journal entries, etc.)
            try:
                return normalize_market_event(event)
            except ValueError:
                return event
        raise TypeError(
            "DataBus events must be Candle, OnChainSnapshot, IndicatorSnapshot, "
            "Signal, OrderIntent, Fill, JournalEntry, or a mapping"
        )
        if isinstance(event, dict):
            return normalize_market_event(event)
        raise TypeError("DataBus events must be Candle, OnChainSnapshot, or a mapping")
