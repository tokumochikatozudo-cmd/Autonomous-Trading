import asyncio
import logging
import json
import numpy as np
import pandas as pd
from datetime import datetime, date
from typing import Dict, Any, Optional

from core.hmm_engine import HMMEngine
from core.risk_manager import RiskManager
from core.regime_strategies import RegimeStrategies
from core.performance_tracker import PerformanceTracker
from core.rl_agent import RLAgent
from data.feature_engineering import FeatureEngineer
from broker.ccxt_client import CryptoBrokerClient
from broker.order_executor import OrderExecutor

# Setup Basic Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MainOrchestrator")


class NumpyEncoder(json.JSONEncoder):
    """
    Custom JSON encoder that converts numpy/pandas scalar types to Python-native types.
    Fix for: 'Object of type bool_ is not JSON serializable'
    """
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


# ─── CONFIG ──────────────────────────────────────────────────────────────────
CONFIG = {
    'hmm': {
        'n_candidates': [3, 4],
        'min_train_bars': 100,
    },
    'risk': {
        # [2A] Raised from 0.80 → 0.95 so the regime strategy can freely set
        # allocations. Previously 0.80 was acting as a floor AND ceiling,
        # blocking the HMM's de-risking logic completely.
        'max_exposure': 0.95,
        'max_leverage': 1.0,
        'max_single_position': 0.95,
    },
    'strategy': {
        'low_vol_allocation': 0.90,   # Calm regime: accumulate more
        'high_vol_allocation': 0.20,  # Turbulent regime: protect capital
    },
    'execution': {
        'symbol': 'BTC/USDT',
        # Bybit's minimum order size for BTC/USDT is 5.0 USDT
        'min_order_size_usd': 5.50,
        # [1C] Only rebalance when allocation shifts by >10%
        'min_allocation_change': 0.10,
        # [1B] Minimum hours between consecutive trades (stops flip-flopping)
        # Reduced to 1 to keep architecture actively working per user request
        'min_hours_between_trades': 1,
        # Hard stop-loss if price drops >8% in 1 hour
        'hard_stop_loss_pct': 0.08,
    },
}


# ─── ORCHESTRATOR ─────────────────────────────────────────────────────────────
class TradingBridgeOrchestrator:

    def __init__(self, mode: str = "live"):
        self.mode = mode
        logger.info(f"Initializing Trading Bridge Orchestrator in {self.mode.upper()} mode...")

        self.feature_eng = FeatureEngineer()
        self.hmm_engine = HMMEngine(CONFIG)
        self.risk_manager = RiskManager(CONFIG)
        self.strategy = RegimeStrategies(CONFIG)

        # [2C] Performance tracker — persists trade journal to monitoring/trades_[mode].json
        self.perf = PerformanceTracker(mode=self.mode)
        
        # [Phase 6] RL Agent Initialization
        self.rl_agent = RLAgent()

        self.broker = CryptoBrokerClient(exchange_id='bybit', paper_trading=(self.mode == "demo"))
        self.executor = OrderExecutor(self.broker, self.risk_manager, CONFIG)

        self.is_running = False
        self._prev_btc_price: float = 0.0  # For closing previous trade P&L

    # ─── Data Fetching ───────────────────────────────────────────────────────

    async def fetch_historical_data(self) -> pd.DataFrame:
        """
        Fetch historical OHLCV data. 
        [Phase 7 Fix] Bybit Cloudflare WAF aggressively blocks public endpoints like fetch_ohlcv from Railway/Datacenter IPs.
        To bypass this, we fetch identical BTC/USDT historical data from Binance's public API, which does not block Railway.
        """
        import ccxt.async_support as ccxt_async
        
        symbol = CONFIG['execution']['symbol']
        timeframe = CONFIG['data']['timeframe']
        limit = 500

        logger.info(f"Fetching {limit} bars of {timeframe} data for {symbol} via Binance (WAF Bypass)...")
        binance = ccxt_async.binance({'enableRateLimit': True})
        try:
            # We use safe_execute manually for Binance
            ohlcv = await binance.fetch_ohlcv(symbol, timeframe, limit=limit)
        except Exception as e:
            logger.error(f"Failed to fetch historical data from Binance: {e}")
            await binance.close()
            return pd.DataFrame()
            
        await binance.close()

        if not ohlcv:
            logger.error(f"No data returned for {symbol}")
            return pd.DataFrame()

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    # ─── True Portfolio Value ────────────────────────────────────────────────

    @staticmethod
    def compute_true_portfolio(balance: dict, btc_price: float) -> float:
        """
        [1A] Fix: true portfolio = USDT in account + BTC holdings × current price.
        Previously the system only read USDT, ignoring the BTC balance entirely.
        This caused wrong P&L calculations and the dashboard to show ~$9 instead of ~$18.
        """
        usdt = balance.get('USDT', {}).get('total', 0.0) or 0.0
        btc = balance.get('BTC', {}).get('total', 0.0) or 0.0
        return usdt + (btc * btc_price)

    # ─── Dashboard State ─────────────────────────────────────────────────────

    def _update_dashboard_state(
        self,
        regime_str: str,
        allocation: float,
        true_portfolio_value: float,
        usdt_balance: float,
        regime_index: int = 0,
        n_states: int = 3,
        state_probs=None,
        vol_tier: str = "mid",
        trend_signal: bool = False,
        leverage: float = 1.0,
        btc_balance: float = 0.0,
        btc_price: float = 0.0,
        trade_entry: Optional[dict] = None,
        perf_summary: Optional[dict] = None,
    ):
        """Dump rich live state + performance analytics to monitoring/state_[mode].json."""
        import os
        now = datetime.now()
        state_path = os.path.join("monitoring", f"state_{self.mode}.json")

        # Preserve trade history and equity bookmarks across cycles
        existing_trades = []
        existing_equity_start = true_portfolio_value
        existing_cycle_count = 0
        existing_peak_equity = true_portfolio_value
        try:
            if os.path.exists(state_path):
                with open(state_path, "r") as f:
                    old = json.load(f)
                existing_trades = old.get("recent_trades", [])
                # Reset day_start at midnight
                saved_date = old.get("day_date", "")
                if saved_date == date.today().isoformat():
                    existing_equity_start = old.get("day_start_equity", true_portfolio_value)
                else:
                    existing_equity_start = true_portfolio_value  # New day
                existing_cycle_count = old.get("cycle_count", 0)
                existing_peak_equity = max(old.get("peak_equity", true_portfolio_value), true_portfolio_value)
        except Exception:
            pass

        # P&L metrics (now based on true portfolio value)
        daily_pnl_pct = (
            (true_portfolio_value - existing_equity_start) / existing_equity_start * 100
            if existing_equity_start > 0 else 0.0
        )
        daily_dd_pct = max(
            0, (existing_equity_start - true_portfolio_value) / existing_equity_start * 100
            if existing_equity_start > 0 else 0.0
        )
        peak_dd_pct = max(
            0, (existing_peak_equity - true_portfolio_value) / existing_peak_equity * 100
            if existing_peak_equity > 0 else 0.0
        )

        if trade_entry:
            existing_trades.append(trade_entry)
            if len(existing_trades) > 50:
                existing_trades = existing_trades[-50:]

        probs_list = [float(p) for p in (state_probs if state_probs is not None else [])]
        regime_prob = max(probs_list) if probs_list else 0.0

        # Performance summary from PerformanceTracker
        ps = perf_summary or {}

        state = {
            # Core identity
            "regime": regime_str,
            "allocation": f"{allocation:.0%}",
            "portfolio_value": f"${true_portfolio_value:.2f}",
            "usdt_balance": round(usdt_balance, 4),
            "status": f"RUNNING ({self.mode.upper()})",
            "trading_mode": self.mode.upper(),

            # Regime detail
            "regime_index": int(regime_index),
            "n_states": int(n_states),
            "regime_prob": round(regime_prob, 4),
            "state_probs": probs_list,
            "stability_bars": int(len(self.hmm_engine.state_history)),
            "flicker_count": int(sum(
                1 for s in list(self.hmm_engine.state_history) if s != regime_index
            )),
            "flicker_window": int(self.hmm_engine.flicker_window),

            # Portfolio (true values)
            "btc_price": round(btc_price, 2),
            "btc_balance": round(btc_balance, 8),
            "btc_usd_value": round(btc_balance * btc_price, 4),
            "vol_tier": vol_tier,
            "trend_signal": bool(trend_signal),
            "leverage": round(float(leverage), 2),

            # P&L / Risk
            "daily_pnl": round(daily_pnl_pct, 3),
            "daily_dd_pct": round(daily_dd_pct, 3),
            "peak_dd_pct": round(peak_dd_pct, 3),
            "day_start_equity": round(existing_equity_start, 4),
            "day_date": date.today().isoformat(),
            "peak_equity": round(existing_peak_equity, 4),
            "daily_trades_count": self.risk_manager.daily_trades_count,
            "is_halted": False,

            # System health
            "system_health": {
                "data": True,
                "api": True,
                "hmm": self.hmm_engine.model is not None,
                "executor": True,
                "risk": True,
            },

            # Cycle info
            "cycle_count": existing_cycle_count + 1,
            "last_cycle_time": now.strftime("%H:%M:%S"),
            "seconds_to_next_cycle": 3600,

            # Trades log
            "recent_trades": existing_trades,

            # [2C] Live performance analytics
            "performance": {
                "total_trades": ps.get("total_trades", 0),
                "closed_trades": ps.get("closed_trades", 0),
                "win_rate": ps.get("win_rate", 0.0),
                "total_pnl_usd": ps.get("total_pnl_usd", 0.0),
                "total_fees_paid": ps.get("total_fees_paid", 0.0),
                "sharpe_ratio": ps.get("sharpe_ratio", 0.0),
                "per_regime": ps.get("per_regime", {}),
            },
        }

        os.makedirs("monitoring", exist_ok=True)
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2, cls=NumpyEncoder)

    # ─── Main Loop ───────────────────────────────────────────────────────────

    async def run_loop(self):
        """The main continuous execution loop."""
        self.is_running = True
        logger.info("Starting Main Trading Loop...")

        is_healthy = await self.broker.check_health()
        if not is_healthy:
            logger.critical("Broker is unhealthy. Halting.")
            return

        while self.is_running:
            try:
                # ── Fetch Data ──────────────────────────────────────────────
                raw_data = await self.fetch_historical_data()

                balance = await self.broker.get_balance()
                usdt_balance = balance.get('USDT', {}).get('total', 0.0) or 0.0
                btc_balance = balance.get('BTC', {}).get('total', 0.0) or 0.0

                symbol = CONFIG['execution']['symbol']
                ticker = await self.broker.fetch_ticker(symbol)
                btc_price = ticker.get('last', 0.0)

                # [1A] True portfolio = USDT + BTC×price
                true_portfolio_value = self.compute_true_portfolio(balance, btc_price)
                logger.info(
                    f"Portfolio: ${true_portfolio_value:.2f} total "
                    f"(${usdt_balance:.2f} USDT + {btc_balance:.8f} BTC @ ${btc_price:.2f})"
                )

                # [2C] Close previous trade P&L if we have one open
                if self._prev_btc_price > 0:
                    self.perf.close_last_trade(btc_price, true_portfolio_value)
                self._prev_btc_price = btc_price

                # ── Feature Engineering & HMM ───────────────────────────────
                featured_data = self.feature_eng.add_technical_indicators(raw_data)
                hmm_features = self.feature_eng.extract_hmm_features(featured_data)
                self.hmm_engine.train(hmm_features)

                if self.hmm_engine.model is not None:
                    recent_features = hmm_features[-1:]
                    regime, probs = self.hmm_engine.predict_regime(recent_features)
                    n_states = self.hmm_engine.n_states

                    regime_labels = [
                        "Calm (Low Volatility)",
                        "Choppy (Moderate)",
                        "Turbulent (High Volatility)",
                    ]
                    regime_str = (
                        regime_labels[regime] if regime < len(regime_labels)
                        else f"State {regime}"
                    )
                    logger.info(
                        f"Current Regime Detected: {regime}/{n_states - 1} — "
                        f"{regime_str} (Probs: {probs})"
                    )

                    # ── Strategy ────────────────────────────────────────────
                    alloc_info = self.strategy.get_allocation(
                        regime, n_states, probs, featured_data
                    )
                    vol_tier = alloc_info.get('tier', 'mid')
                    trend_signal = alloc_info.get('trend', False)
                    leverage = alloc_info.get('leverage', 1.0)
                    
                    # [Phase 6] Ask RL Agent for the true target allocation
                    current_alloc = 0.0
                    if len(self.perf.trades) > 0:
                        current_alloc = self.perf.trades[-1].get('allocation', 0.0)
                    
                    target_allocation = self.rl_agent.get_allocation(probs, current_alloc)

                    # ── Hard Stop-Loss Check ────────────────────────────────
                    # If BTC drops > 8% in the last hour, force target allocation to 0%
                    if len(raw_data) >= 2:
                        last_close = raw_data['close'].iloc[-1]
                        prev_close = raw_data['close'].iloc[-2]
                        hourly_drop = (last_close - prev_close) / prev_close
                        if hourly_drop < -CONFIG['execution'].get('hard_stop_loss_pct', 0.08):
                            logger.critical(f"HARD STOP-LOSS TRIGGERED! Price dropped {hourly_drop:.2%} in 1 hour. Liquidating to Cash.")
                            target_allocation = 0.0
                            vol_tier = 'CRASH'

                    # ── Execute (with all guards) ────────────────────────────
                    exec_result = await self.executor.execute_allocation(
                        target_allocation=target_allocation,
                        current_total_exposure=0.0,
                        current_positions_count=1,
                        is_halted=False,
                        true_portfolio_value=true_portfolio_value,
                    )

                    action = exec_result["action"]
                    approved_alloc = exec_result["approved_allocation"]
                    skip_reason = exec_result.get("skip_reason", "")
                    usd_diff = exec_result["usd_value"]
                    qty_diff = exec_result["qty"]
                    fee_paid = exec_result["fee_paid"]

                    # [2C] Record to performance journal if it was a real trade
                    if action in ("BUY", "SELL") and qty_diff > 0:
                        self.perf.record_trade(
                            action=action,
                            regime=regime_str,
                            allocation=approved_alloc,
                            entry_price=btc_price,
                            qty=qty_diff,
                            usd_value=usd_diff,
                            fee_paid=fee_paid,
                            portfolio_value_before=true_portfolio_value,
                            notes=f"{vol_tier.upper()} vol | {regime_str[:12]}",
                        )

                    # ── Build dashboard trade entry ───────────────────────────
                    if action in ("BUY", "SELL"):
                        notes = f"Regime→{regime_str[:10]} | {vol_tier.upper()} vol"
                    else:
                        # Show which guard fired
                        notes = skip_reason if skip_reason else f"Δ${usd_diff:.2f} < min"

                    trade_entry = {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "action": action,
                        "asset": "BTC/USDT",
                        "amount": f"{qty_diff:.8f}" if action in ("BUY", "SELL") else "—",
                        "usd_value": f"{usd_diff:.2f}" if action in ("BUY", "SELL") else "—",
                        "price": f"{btc_price:.2f}",
                        "regime": regime_str,
                        "allocation": f"{approved_alloc:.0%}",
                        "notes": notes,
                    }

                    # ── Update Dashboard ─────────────────────────────────────
                    self._update_dashboard_state(
                        regime_str=regime_str,
                        allocation=target_allocation,
                        true_portfolio_value=true_portfolio_value,
                        usdt_balance=usdt_balance,
                        regime_index=regime,
                        n_states=n_states,
                        state_probs=probs.tolist() if hasattr(probs, 'tolist') else list(probs),
                        vol_tier=vol_tier,
                        trend_signal=trend_signal,
                        leverage=leverage,
                        btc_balance=btc_balance,
                        btc_price=btc_price,
                        trade_entry=trade_entry,
                        perf_summary=self.perf.summary(),
                    )

                else:
                    logger.warning("HMM Model failed to train. Skipping execution cycle.")
                    self._update_dashboard_state(
                        regime_str="Training...",
                        allocation=0.0,
                        true_portfolio_value=true_portfolio_value,
                        usdt_balance=usdt_balance,
                        btc_price=btc_price,
                        btc_balance=btc_balance,
                    )

            except Exception as e:
                logger.error(f"Error in main loop cycle: {e}", exc_info=True)

            logger.info("Cycle complete. Sleeping for 1 hour...")
            await asyncio.sleep(3600)


async def main(mode: str):
    orchestrator = TradingBridgeOrchestrator(mode=mode)
    try:
        await orchestrator.run_loop()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await orchestrator.broker.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Autonomous Trading Bridge")
    parser.add_argument("--demo", action="store_true", help="Run in Demo Trading mode (Paper Trading)")
    parser.add_argument("--live", action="store_true", help="Run in LIVE mode (Real Funds)")
    args = parser.parse_args()

    mode = "demo" if args.demo else "live"
    asyncio.run(main(mode))
