import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Bybit spot taker fee rate
BYBIT_TAKER_FEE = 0.001  # 0.10%


class OrderExecutor:
    """
    Translates portfolio allocation targets into actual crypto market orders.

    Upgrades vs v1:
    - [1C] Allocation change threshold: only rebalances if allocation shifts >10%
    - [1B] Time-lock: minimum N hours between consecutive trades to stop flip-flopping
    - [2B] Fee-aware: skips trades where expected gain < fee cost
    - [2C] Returns rich trade result dict for PerformanceTracker
    """

    def __init__(self, broker_client: Any, risk_manager: Any, config: Dict[str, Any]):
        self.broker = broker_client
        self.risk = risk_manager

        exec_config = config.get('execution', {})
        self.symbol = exec_config.get('symbol', 'BTC/USDT')
        self.min_order_size_usd = exec_config.get('min_order_size_usd', 0.50)

        # [1C] Minimum allocation shift required to trigger a rebalance (10%)
        self.min_allocation_change = exec_config.get('min_allocation_change', 0.10)

        # [1B] Minimum hours between trades (prevents flip-flopping)
        min_hours = exec_config.get('min_hours_between_trades', 3)
        self.min_trade_interval = timedelta(hours=min_hours)
        self.last_trade_time: Optional[datetime] = None

        # Track last approved allocation to detect significant changes
        self.last_approved_allocation: float = -1.0

    def _is_time_locked(self) -> bool:
        """[1B] Return True if we are still within the minimum trade interval."""
        if self.last_trade_time is None:
            return False
        elapsed = datetime.now() - self.last_trade_time
        if elapsed < self.min_trade_interval:
            remaining_min = int((self.min_trade_interval - elapsed).total_seconds() / 60)
            logger.info(
                f"Time-lock active: {remaining_min}min remaining until next trade allowed "
                f"(min interval = {int(self.min_trade_interval.total_seconds()/3600)}h)"
            )
            return True
        return False

    def _allocation_changed_enough(self, new_allocation: float) -> bool:
        """[1C] Return True if allocation shifted enough to justify a rebalance."""
        if self.last_approved_allocation < 0:
            return True  # First ever trade — always allow
        change = abs(new_allocation - self.last_approved_allocation)
        if change < self.min_allocation_change:
            logger.info(
                f"Allocation change {change:.1%} < threshold {self.min_allocation_change:.1%}. "
                f"Holding position (last={self.last_approved_allocation:.0%}, new={new_allocation:.0%})."
            )
            return False
        return True

    def _estimate_fee(self, trade_usd_value: float) -> float:
        """Return estimated Bybit taker fee in USD for a given trade size."""
        return trade_usd_value * BYBIT_TAKER_FEE

    async def execute_allocation(
        self,
        target_allocation: float,
        current_total_exposure: float,
        current_positions_count: int,
        is_halted: bool,
        true_portfolio_value: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Takes the raw target allocation from the strategy, applies all guards,
        and executes the necessary market order.

        Returns a result dict with action, qty, usd_value, fee_paid, skip_reason.
        """
        result = {
            "action": "SKIP",
            "qty": 0.0,
            "usd_value": 0.0,
            "fee_paid": 0.0,
            "price": 0.0,
            "skip_reason": "",
            "approved_allocation": 0.0,
        }

        # ── Guard 1: Risk Manager Veto ──────────────────────────────────────
        approved_allocation = self.risk.veto_signal(
            requested_allocation=target_allocation,
            current_positions_count=current_positions_count,
            current_total_exposure=current_total_exposure,
            is_halted=is_halted,
        )
        result["approved_allocation"] = approved_allocation
        logger.info(f"Target: {target_allocation:.2%} | Risk-approved: {approved_allocation:.2%}")

        # ── Guard 2: Allocation Change Threshold [1C] ───────────────────────
        if not self._allocation_changed_enough(approved_allocation):
            result["skip_reason"] = (
                f"Alloc Δ{abs(approved_allocation - self.last_approved_allocation):.0%} "
                f"< {self.min_allocation_change:.0%} threshold"
            )
            return result

        # ── Guard 3: Time-Lock [1B] ─────────────────────────────────────────
        if self._is_time_locked():
            elapsed = datetime.now() - self.last_trade_time
            remaining = self.min_trade_interval - elapsed
            result["skip_reason"] = (
                f"Time-locked: {int(remaining.total_seconds()/60)}min until next trade allowed"
            )
            return result

        try:
            # ── Fetch live data ─────────────────────────────────────────────
            balance = await self.broker.get_balance()
            usdt_balance = balance.get('USDT', {}).get('total', 0.0)

            ticker = await self.broker.fetch_ticker(self.symbol)
            current_price = ticker.get('last', 0.0)
            result["price"] = current_price

            if usdt_balance <= 0 or current_price <= 0:
                result["skip_reason"] = "Zero balance or price unavailable"
                return result

            base_asset = self.symbol.split('/')[0]
            current_crypto_qty = balance.get(base_asset, {}).get('total', 0.0)

            # Use true portfolio value (USDT + BTC×price) as the base for allocation
            portfolio_base = true_portfolio_value if true_portfolio_value > 0 else usdt_balance
            target_usd_value = portfolio_base * approved_allocation
            target_crypto_qty = target_usd_value / current_price

            qty_diff = target_crypto_qty - current_crypto_qty
            usd_diff_value = abs(qty_diff) * current_price
            estimated_fee = self._estimate_fee(usd_diff_value)

            # ── Guard 4: Minimum Order Size ─────────────────────────────────
            if usd_diff_value < self.min_order_size_usd:
                result["skip_reason"] = f"Δ${usd_diff_value:.2f} < min ${self.min_order_size_usd}"
                return result

            # ── Guard 5: Fee-Aware Check [2B] ───────────────────────────────
            # Only trade if the rebalance delta is large enough to cover the fee
            # with some margin. Rule: trade only if |Δ| > 2× fee cost.
            if usd_diff_value < estimated_fee * 2:
                result["skip_reason"] = (
                    f"Fee-aware skip: Δ${usd_diff_value:.3f} ≤ 2× fee ${estimated_fee*2:.3f}"
                )
                logger.info(result["skip_reason"])
                return result

            # ── Execute with Bybit Skill (Spot Edition) ──────────
            side = 'buy' if qty_diff > 0 else 'sell'
            abs_qty = abs(qty_diff)
            
            # Note: Bybit Spot does not support attached stopLoss in createMarketOrder
            # The architecture handles risk via the hard_stop_loss_pct in main.py instead.
            params = {}

            logger.info(
                f"Executing {side.upper()} for {abs_qty:.8f} {self.symbol} "
                f"(${usd_diff_value:.2f}) → {approved_allocation:.0%} allocation. "
                f"Fee est: ${estimated_fee:.4f}"
            )
            
            # Use CCXT to pass the extra params to Bybit V5
            await self.broker._safe_execute(
                self.broker.exchange.create_market_order, 
                self.symbol, side, abs_qty, params=params
            )
            
            self.risk.daily_trades_count += 1

            # ── Record state for next cycle guards ──────────────────────────
            self.last_trade_time = datetime.now()
            self.last_approved_allocation = approved_allocation

            result["action"] = side.upper()
            result["qty"] = abs_qty
            result["usd_value"] = usd_diff_value
            result["fee_paid"] = estimated_fee
            return result

        except Exception as e:
            # [Skill Integration] Graceful Degradation & Error Mapping
            error_str = str(e)
            logger.error(f"Failed to execute allocation: {error_str}")
            
            if "10006" in error_str or "TOO_MANY_REQUESTS" in error_str:
                result["skip_reason"] = "Bybit Rate Limit Exceeded (Degrading gracefully)"
            elif "110004" in error_str or "170131" in error_str:
                result["skip_reason"] = "Insufficient wallet balance for trade"
            elif "170140" in error_str:
                result["skip_reason"] = "Order value below Bybit $5.00 minimum"
            else:
                result["skip_reason"] = f"Exception: {error_str[:80]}"
                
            return result
