from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import uvicorn
import os
import json

app = FastAPI(title="Trading Bridge Dashboard")

# Resolve paths relative to this file so it works from any working directory
_HERE = os.path.dirname(os.path.abspath(__file__))
templates_dir = os.path.join(_HERE, "templates")
os.makedirs(templates_dir, exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

def get_live_state(mode: str = "live") -> dict:
    """Load the state written by main.py's _update_dashboard_state."""
    _STATE_CANDIDATES = [
        os.path.join(_HERE, f"state_{mode}.json"),
        os.path.join(os.getcwd(), "monitoring", f"state_{mode}.json"),
    ]
    
    for path in _STATE_CANDIDATES:
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    return json.load(f)
            except Exception:
                pass

    # Default skeleton if no state file exists yet
    return {
        "regime": "Waiting for main.py...",
        "allocation": "0%",
        "portfolio_value": "$0.00",
        "status": "INITIALIZING",
        "trading_mode": "LIVE",
        "regime_index": 0,
        "n_states": 3,
        "regime_prob": 0.0,
        "state_probs": [0.33, 0.33, 0.34],
        "stability_bars": 0,
        "flicker_count": 0,
        "flicker_window": 20,
        "btc_price": 0.0,
        "btc_balance": 0.0,
        "vol_tier": "",
        "trend_signal": False,
        "leverage": 1.0,
        "daily_pnl": 0.0,
        "daily_dd_pct": 0.0,
        "peak_dd_pct": 0.0,
        "daily_trades_count": 0,
        "is_halted": False,
        "system_health": {"data": False, "api": False, "hmm": False, "executor": False, "risk": False},
        "cycle_count": 0,
        "last_cycle_time": "—",
        "seconds_to_next_cycle": 3600,
        "recent_trades": [],
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, mode: str = "live"):
    """Render the main dashboard."""
    current_state = get_live_state(mode)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"request": request, "state": current_state, "mode": mode}
    )


@app.get("/api/state")
async def get_state_api(mode: str = "live"):
    """JSON API endpoint — polled by dashboard JS every 5 seconds."""
    return get_live_state(mode)


@app.get("/health")
async def health():
    return {"status": "ok"}


def run_server():
    """Run the FastAPI server."""
    port = int(os.environ.get("PORT", 8080))
    host = "0.0.0.0"
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
