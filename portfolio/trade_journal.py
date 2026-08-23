from __future__ import annotations

from dataclasses import dataclass, field

from broker.paper_broker import Fill
from risk.risk_guard import OrderIntent
from strategy.base_strategy import Signal


@dataclass(slots=True)
class JournalEntry:
    signal: Signal
    intent: OrderIntent
    fill: Fill | None = None
    outcome: dict = field(default_factory=dict)


class PortfolioTradeJournal:
    def __init__(self) -> None:
        self.entries: list[JournalEntry] = []

    def record(self, signal: Signal, intent: OrderIntent, fill: Fill | None = None, outcome: dict | None = None) -> JournalEntry:
        entry = JournalEntry(signal, intent, fill, outcome or {})
        self.entries.append(entry)
        return entry
