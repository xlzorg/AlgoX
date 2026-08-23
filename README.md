# Trading Bot

FastAPI-based paper trading bot scaffold with async SQLite persistence, market data adapters, indicator and strategy layers, risk controls, portfolio tracking, and analytics extension points.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

The API is available at `http://127.0.0.1:8000` and its OpenAPI docs at `/docs`.

API keys belong in `.env`; do not commit them.
