import pandas as pd
import numpy as np
from typing import Dict, Any

class RegimeStrategies:
    """Volatility-based allocation strategies tailored to current regime."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize with strategy configuration allocations."""
        strat_config = config.get('strategy', {})
        self.low_vol_alloc = strat_config.get('low_vol_allocation', 0.95)
        self.mid_vol_trend = strat_config.get('mid_vol_allocation_trend', 0.95)
        self.mid_vol_no_trend = strat_config.get('mid_vol_allocation_no_trend', 0.60)
        self.high_vol_alloc = strat_config.get('high_vol_allocation', 0.60) # Or even lower (e.g., 0.0) for pure cash
        self.low_vol_leverage = strat_config.get('low_vol_leverage', 1.25)
        self.uncertainty_mult = strat_config.get('uncertainty_size_mult', 0.50)

    def determine_volatility_tier(self, current_state: int, n_states: int) -> str:
        """
        Map the mathematical HMM state (0 to N-1) to a logical volatility tier.
        Since states are sorted by variance, 0 is always lowest, N-1 is highest.
        """
        if current_state == 0:
            return 'low'
        elif current_state == n_states - 1:
            return 'high'
        else:
            return 'mid'

    def has_uptrend(self, recent_data: pd.DataFrame) -> bool:
        """
        Determine if there is a prevailing uptrend.
        For crypto, a simple 200-period or 50-period SMA on the close price is effective.
        """
        if len(recent_data) < 50:
            return False
        
        # Simple trend definition: close > 50 SMA
        sma_50 = recent_data['close'].rolling(window=50).mean().iloc[-1]
        current_close = recent_data['close'].iloc[-1]
        
        return current_close > sma_50

    def get_allocation(self, current_state: int, n_states: int, state_probs: np.ndarray, recent_data: pd.DataFrame) -> Dict[str, float]:
        """
        Determine portfolio allocation percentage and leverage based on the regime.
        
        Returns:
            Dict containing 'allocation' (0.0 to 1.0) and 'leverage' (1.0+).
        """
        if current_state < 0 or n_states <= 0:
            return {'allocation': 0.0, 'leverage': 1.0}

        tier = self.determine_volatility_tier(current_state, n_states)
        trend = self.has_uptrend(recent_data)
        
        allocation = 0.0
        leverage = 1.0
        
        if tier == 'low':
            # Low Volatility: "Crypto trends upward in low-vol periods." Maximize exposure.
            allocation = self.low_vol_alloc
            leverage = self.low_vol_leverage
        elif tier == 'mid':
            # Mid Volatility: Check for trend. If trending, ride it. If sideways, reduce size.
            allocation = self.mid_vol_trend if trend else self.mid_vol_no_trend
        elif tier == 'high':
            # High Volatility: "Worst drawdowns cluster in high-vol spikes." Reduce exposure drastically.
            allocation = self.high_vol_alloc
            
        # Uncertainty Penalty: If the HMM is highly uncertain about the current state
        # (e.g., max probability is < 60%), we drastically cut the allocation to be safe.
        max_prob = np.max(state_probs) if len(state_probs) > 0 else 1.0
        if max_prob < 0.60:
            allocation *= self.uncertainty_mult
            leverage = 1.0 # Disable leverage in uncertain times
            
        return {
            'allocation': round(allocation, 3),
            'leverage': round(leverage, 3),
            'tier': tier,
            'trend': trend
        }

