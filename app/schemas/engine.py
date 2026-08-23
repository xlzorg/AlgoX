from pydantic import BaseModel


class EngineActionResponse(BaseModel):
    running: bool


class EngineStatusResponse(BaseModel):
    running: bool
    uptime_sec: float
    symbols: list[str]
    active_tfs: list[str]


class TimeframeRequest(BaseModel):
    timeframe: str


class TimeframeResponse(BaseModel):
    timeframe: str
    running: bool