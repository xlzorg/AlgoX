from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AlgoBot"
    debug: bool = False
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./trading_bot.db"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    binance_ws_url: str = "wss://data-stream.binance.vision/stream"
    binance_rest_url: str = "https://data-api.binance.vision"
    binance_api_key: str = ""
    binance_secret: str = Field(
        default="",
        validation_alias=AliasChoices("BINANCE_SECRET", "BINANCE_API_SECRET"),
    )

    coingecko_base_url: str = "https://api.geckoterminal.com/api/v2"
    coingecko_poll_interval: int = 60
    coingecko_rate_limit_per_min: int = 25

    symbols: list[str] = ["BTCUSDT", "ETHUSDT"]
    timeframes: list[str] = ["1m", "5m", "1h"]
    primary_tf: str = "1h"
    trigger_tf: str = "5m"
    history_candles: int = 500

    starting_balance_usdt: float = 10_000.0
    taker_fee: float = 0.001
    maker_fee: float = 0.0008
    slippage_noise_std: float = 0.0002

    ema_periods: list[int] = [9, 21, 50, 200]
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal_period: int = 9
    atr_period: int = 14
    adx_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0

    max_risk_per_trade_pct: float = 0.01
    atr_stop_multiplier: float = 1.5
    tp1_r: float = 1.5
    tp2_r: float = 2.5
    max_open_positions: int = 5
    max_single_asset_pct: float = 0.20
    max_daily_loss_pct: float = 0.03
    max_drawdown_pct: float = 0.10
    cooldown_after_sl_sec: int = 300
    auto_manage_positions: bool = Field(
        default=True,
        validation_alias=AliasChoices("AUTO_MANAGE_POSITIONS", "auto_manage_positions"),
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def binance_api_secret(self) -> str:
        """Backward-compatible name used by the initial application scaffold."""
        return self.binance_secret


@lru_cache
def get_settings() -> Settings:
    return Settings()
