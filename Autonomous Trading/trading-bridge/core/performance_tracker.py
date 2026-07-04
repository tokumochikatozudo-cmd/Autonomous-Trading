import json
import os
import logging
from datetime import datetime, date
from typing import Dict, List, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)


class PerformanceTracker:
    """
    Tracks live trading performance with per-regime analytics.
    Persists a trade journal to monitoring/trades_[mode].json.
    Provides Sharpe ratio, win rate, and regime-level P&L breakdowns.
    """

    def __init__(self, mode: str = "live"):
        self.mode = mode
        self.JOURNAL_PATH = os.path.join("monitoring", f"trades_{self.mode}.json")
        self.trades: List[Dict[str, Any]] = []
        self.regime_stats: Dict[str, Dict] = {}
        self._load_journal()

    # ─── Persistence ────────────────────────────────────────────────────────────

    def _load_journal(self):
        """Load persisted trade journal from disk on startup."""
        try:
            if os.path.exists(self.JOURNAL_PATH):
                with open(self.JOURNAL_PATH, "r") as f:
                    data = json.load(f)
                self.trades = data.get("trades", [])
                logger.info(f"PerformanceTracker: Loaded {len(self.trades)} historical trades.")
        except Exception as e:
            logger.warning(f"PerformanceTracker: Could not load journal: {e}")
            self.trades = []

    def _save_journal(self):
        """Persist trade journal to disk."""
        try:
            os.makedirs("monitoring", exist_ok=True)
            with open(self.JOURNAL_PATH, "w") as f:
                json.dump({"trades": self.trades, "last_updated": datetime.now().isoformat()}, f, indent=2)
        except Exception as e:
            logger.error(f"PerformanceTracker: Could not save journal: {e}")

    # ─── Trade Logging ───────────────────────────────────────────────────────────

    def record_trade(
        self,
        action: str,
        regime: str,
        allocation: float,
        entry_price: float,
        qty: float,
        usd_value: float,
        fee_paid: float,
        portfolio_value_before: float,
        notes: str = "",
    ):
        """Record a completed trade into the journal."""
        trade = {
            "id": len(self.trades) + 1,
            "timestamp": datetime.now().isoformat(),
            "date": date.today().isoformat(),
            "action": action,
            "regime": regime,
            "allocation": round(allocation, 4),
            "entry_price": round(entry_price, 2),
            "qty": round(qty, 8),
            "usd_value": round(usd_value, 4),
            "fee_paid": round(fee_paid, 6),
            "portfolio_before": round(portfolio_value_before, 4),
            "pnl": None,  # Filled in on next cycle
            "notes": notes,
        }
        self.trades.append(trade)
        self._save_journal()
        logger.info(f"PerformanceTracker: Recorded {action} trade #{trade['id']} in {regime} regime.")
        return trade["id"]

    def close_last_trade(self, exit_price: float, portfolio_value_after: float):
        """Mark the most recent open trade as closed and calculate P&L."""
        for trade in reversed(self.trades):
            if trade.get("pnl") is None and trade["action"] in ("BUY", "SELL"):
                direction = 1 if trade["action"] == "BUY" else -1
                price_change_pct = direction * (exit_price - trade["entry_price"]) / trade["entry_price"]
                pnl_usd = price_change_pct * trade["usd_value"] - trade["fee_paid"]
                trade["exit_price"] = round(exit_price, 2)
                trade["pnl"] = round(pnl_usd, 6)
                trade["pnl_pct"] = round(price_change_pct * 100, 4)
                trade["portfolio_after"] = round(portfolio_value_after, 4)
                trade["closed_at"] = datetime.now().isoformat()
                self._save_journal()
                logger.info(f"PerformanceTracker: Closed trade #{trade['id']}: P&L = ${pnl_usd:.4f} ({price_change_pct*100:.2f}%)")
                return

    # ─── Analytics ───────────────────────────────────────────────────────────────

    def get_closed_trades(self) -> List[Dict]:
        """Return all trades with a calculated P&L."""
        return [t for t in self.trades if t.get("pnl") is not None]

    def win_rate(self) -> float:
        """Fraction of closed trades that were profitable."""
        closed = self.get_closed_trades()
        if not closed:
            return 0.0
        wins = sum(1 for t in closed if t["pnl"] > 0)
        return round(wins / len(closed), 4)

    def total_pnl_usd(self) -> float:
        """Total realized P&L in USD across all closed trades."""
        return round(sum(t["pnl"] for t in self.get_closed_trades()), 4)

    def total_fees_paid(self) -> float:
        """Total fees paid across all trades (open + closed)."""
        return round(sum(t.get("fee_paid", 0) for t in self.trades), 6)

    def sharpe_ratio(self, periods_per_year: int = 8760) -> float:
        """
        Annualized Sharpe ratio from per-trade P&L% returns.
        Uses hourly periods (8760/year) as default for hourly rebalancing.
        """
        closed = self.get_closed_trades()
        if len(closed) < 5:
            return 0.0
        returns = np.array([t["pnl_pct"] / 100 for t in closed])
        if returns.std() == 0:
            return 0.0
        annualized_mean = returns.mean() * periods_per_year
        annualized_std = returns.std() * np.sqrt(periods_per_year)
        return round(annualized_mean / annualized_std, 4)

    def per_regime_stats(self) -> Dict[str, Dict]:
        """Break down win rate, avg P&L, and trade count per regime."""
        stats: Dict[str, Dict] = {}
        for trade in self.get_closed_trades():
            regime = trade.get("regime", "Unknown")
            if regime not in stats:
                stats[regime] = {"trades": 0, "wins": 0, "total_pnl": 0.0, "total_fees": 0.0}
            stats[regime]["trades"] += 1
            stats[regime]["total_pnl"] += trade["pnl"]
            stats[regime]["total_fees"] += trade.get("fee_paid", 0)
            if trade["pnl"] > 0:
                stats[regime]["wins"] += 1
        for regime, s in stats.items():
            s["win_rate"] = round(s["wins"] / s["trades"], 4) if s["trades"] > 0 else 0.0
            s["avg_pnl"] = round(s["total_pnl"] / s["trades"], 6) if s["trades"] > 0 else 0.0
        return stats

    def summary(self) -> Dict[str, Any]:
        """Full performance summary for dashboard and logging."""
        closed = self.get_closed_trades()
        return {
            "total_trades": len(self.trades),
            "closed_trades": len(closed),
            "win_rate": self.win_rate(),
            "total_pnl_usd": self.total_pnl_usd(),
            "total_fees_paid": self.total_fees_paid(),
            "sharpe_ratio": self.sharpe_ratio(),
            "per_regime": self.per_regime_stats(),
        }
