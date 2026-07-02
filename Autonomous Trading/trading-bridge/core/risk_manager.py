from typing import Dict, Any, Tuple
import logging

logger = logging.getLogger(__name__)

class RiskManager:
    """
    Handles position sizing, leverage limits, and drawdown protections.
    Operates INDEPENDENTLY of the HMM as a defense-in-depth circuit breaker.
    Has ABSOLUTE VETO POWER over any signal.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize risk management constraints from settings."""
        risk_cfg = config.get('risk', {})
        self.max_risk_per_trade = risk_cfg.get('max_risk_per_trade', 0.01)
        self.max_exposure = risk_cfg.get('max_exposure', 0.80)
        self.max_leverage = risk_cfg.get('max_leverage', 1.25)
        self.max_single_pos = risk_cfg.get('max_single_position', 0.15)
        self.max_concurrent = risk_cfg.get('max_concurrent', 5)
        self.max_daily_trades = risk_cfg.get('max_daily_trades', 20)
        
        # Drawdown Circuit Breakers
        self.daily_dd_reduce = risk_cfg.get('daily_dd_reduce', 0.02)
        self.daily_dd_halt = risk_cfg.get('daily_dd_halt', 0.03)
        self.weekly_dd_reduce = risk_cfg.get('weekly_dd_reduce', 0.05)
        self.weekly_dd_halt = risk_cfg.get('weekly_dd_halt', 0.07)
        self.max_dd_from_peak = risk_cfg.get('max_dd_from_peak', 0.10)
        
        # Tracking State
        self.daily_trades_count = 0
        self.current_exposure = 0.0

    def evaluate_drawdowns(self, current_equity: float, peak_equity: float, 
                           daily_start_equity: float, weekly_start_equity: float) -> Tuple[bool, float]:
        """
        Evaluate all drawdown conditions independently of the HMM.
        Returns:
            Tuple: (is_halted (bool), allocation_multiplier (float))
        """
        if current_equity <= 0 or peak_equity <= 0:
            return True, 0.0 # Absolute halt
            
        peak_dd = (peak_equity - current_equity) / peak_equity
        daily_dd = (daily_start_equity - current_equity) / daily_start_equity if daily_start_equity > 0 else 0
        weekly_dd = (weekly_start_equity - current_equity) / weekly_start_equity if weekly_start_equity > 0 else 0
        
        # 1. Absolute Halts (Veto Power)
        if peak_dd >= self.max_dd_from_peak:
            logger.critical(f"CIRCUIT BREAKER: Max peak drawdown reached ({peak_dd:.2%}). HALTING TRADING.")
            return True, 0.0
            
        if daily_dd >= self.daily_dd_halt:
            logger.critical(f"CIRCUIT BREAKER: Daily drawdown limit reached ({daily_dd:.2%}). HALTING TRADING FOR DAY.")
            return True, 0.0
            
        if weekly_dd >= self.weekly_dd_halt:
            logger.critical(f"CIRCUIT BREAKER: Weekly drawdown limit reached ({weekly_dd:.2%}). HALTING TRADING FOR WEEK.")
            return True, 0.0
            
        # 2. Reduction Multipliers (Defense in Depth)
        allocation_multiplier = 1.0
        
        if daily_dd >= self.daily_dd_reduce:
            logger.warning(f"Risk Warning: Daily drawdown ({daily_dd:.2%}). Reducing size by 50%.")
            allocation_multiplier *= 0.5
            
        if weekly_dd >= self.weekly_dd_reduce:
            logger.warning(f"Risk Warning: Weekly drawdown ({weekly_dd:.2%}). Reducing size by 50%.")
            allocation_multiplier *= 0.5
            
        return False, allocation_multiplier

    def veto_signal(self, requested_allocation: float, current_positions_count: int, 
                    current_total_exposure: float, is_halted: bool) -> float:
        """
        The Absolute Veto Power function.
        Modifies or outright rejects an allocation request from the Strategy Layer.
        Returns the APPROVED allocation (which may be 0.0).
        """
        if is_halted:
            return 0.0
            
        if self.daily_trades_count >= self.max_daily_trades and requested_allocation > 0:
            logger.warning("VETO: Maximum daily trades exceeded.")
            return 0.0
            
        if current_positions_count >= self.max_concurrent and requested_allocation > 0:
            logger.warning("VETO: Maximum concurrent positions reached.")
            return 0.0
            
        # Hard limits on exposure and leverage
        approved_allocation = min(requested_allocation, self.max_single_pos)
        
        if current_total_exposure + approved_allocation > self.max_exposure * self.max_leverage:
            # Scale down to fit within max exposure
            available_room = (self.max_exposure * self.max_leverage) - current_total_exposure
            approved_allocation = min(approved_allocation, max(0.0, available_room))
            if approved_allocation > 0:
                logger.warning(f"VETO: Scaled down allocation to {approved_allocation:.2f} to prevent over-exposure.")
                
        return approved_allocation

    def reset_daily_counters(self) -> None:
        """Called at midnight UTC to reset daily tracking."""
        self.daily_trades_count = 0
