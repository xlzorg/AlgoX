from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
import logging
from pydantic import BaseModel, ConfigDict, Field


def _number(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    return float(value)


def _integer(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    return int(value)


def _timestamp(value: Any) -> int:
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    if isinstance(value, str) and not value.isdigit():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return int(parsed.timestamp() * 1000)
    return int(value)


class Candle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: Literal["candle"] = "candle"
    symbol: str
    timeframe: str
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int | None = None
    taker_buy_vol: float | None = None
    close_time: int | None = None
    is_closed: bool = True

    @classmethod
    def from_binance_ws(cls, payload: dict[str, Any]) -> Candle:
        data = payload.get("data", payload)
        kline = data.get("k", data.get("kline", {}))
        if not kline:
            raise ValueError("Binance WebSocket payload does not contain a kline")

            # temporary debug — remove later
        
        raw_x = kline.get("x")

        logging.getLogger(__name__).info(
            "KLINE raw x=%s i=%s t=%s c=%s",
            raw_x, kline.get("i"), kline.get("t"), kline.get("c"),
        )
        return cls(
            symbol=str(kline.get("s", data.get("s", ""))).upper(),
            timeframe=str(kline.get("i", "")),
            open_time=_timestamp(kline["t"]),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            quote_volume=float(kline.get("q", 0.0)),
            trades=_integer(kline.get("n")),
            taker_buy_vol=_number(kline.get("V")),
            close_time=_integer(kline.get("T")),
            is_closed=bool(raw_x) if raw_x is not None else False,
        )

    @classmethod
    def from_binance_rest(
        cls,
        payload: list[Any],
        *,
        symbol: str,
        timeframe: str,
    ) -> Candle:
        if len(payload) < 11:
            raise ValueError("Binance REST kline must contain at least 11 fields")
        return cls(
            symbol=symbol.upper(),
            timeframe=timeframe,
            open_time=_timestamp(payload[0]),
            open=float(payload[1]),
            high=float(payload[2]),
            low=float(payload[3]),
            close=float(payload[4]),
            volume=float(payload[5]),
            close_time=_timestamp(payload[6]),
            quote_volume=float(payload[7]),
            trades=_integer(payload[8]),
            taker_buy_vol=_number(payload[9]),
            is_closed=True,
        )


class OnChainSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_type: Literal["onchain"] = "onchain"
    symbol: str
    chain: str
    timestamp: int
    pool_tvl_usd: float | None = None
    pool_volume_24h: float | None = None
    exchange_netflow_24h: float | None = None
    nvt_ratio: float | None = None
    active_addresses_24h: int | None = None
    top10_holder_pct: float | None = None
    created_at: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp() * 1000))

    @classmethod
    def from_coingecko_terminal(
        cls,
        payload: dict[str, Any],
        *,
        symbol: str,
        chain: str,
        timestamp: int | None = None,
    ) -> OnChainSnapshot:
        data = payload.get("data", payload)
        attributes = data.get("attributes", data)
        now = timestamp if timestamp is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
        return cls(
            symbol=symbol.upper(),
            chain=chain,
            timestamp=now,
            pool_tvl_usd=_number(
                attributes.get("reserve_in_usd", attributes.get("pool_tvl_usd"))
            ),
            pool_volume_24h=_number(
                attributes.get("volume_usd", {}).get("h24")
                if isinstance(attributes.get("volume_usd"), dict)
                else attributes.get("volume_24h", attributes.get("pool_volume_24h"))
            ),
            exchange_netflow_24h=_number(
                attributes.get("exchange_netflow_24h", attributes.get("netflow_24h"))
            ),
            nvt_ratio=_number(attributes.get("nvt_ratio")),
            active_addresses_24h=_integer(
                attributes.get("active_addresses_24h", attributes.get("active_addresses"))
            ),
            top10_holder_pct=_number(attributes.get("top10_holder_pct")),
        )


def normalize_market_event(event: dict[str, Any]) -> Candle | OnChainSnapshot:
    """Normalize a raw feed event into one of the canonical market models."""
    data = event.get("data", event)
    if "k" in data or data.get("e") == "kline":
        return Candle.from_binance_ws(event)
    if event.get("event_type") == "candle":
        return Candle.model_validate(event)
    if event.get("event_type") == "onchain":
        return OnChainSnapshot.model_validate(event)
    raise ValueError("Unsupported market event payload")
