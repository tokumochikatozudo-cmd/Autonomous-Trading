import pandas as pd
import numpy as np
from typing import Dict, Any
import logging
from tqdm import tqdm

logger = logging.getLogger(__name__)

class WalkForwardBacktester:
    """Executes walk-forward, allocation-based backtesting for the regime strategy."""
    
    def __init__(self, hmm_engine: Any, strategy: Any, feature_engineer: Any, config: Dict[str, Any]):
        """Initialize the backtester configuration."""
        self.hmm_engine = hmm_engine
        self.strategy = strategy
        self.feature_engineer = feature_engineer
        
        bt_config = config.get('backtest', {})
        self.initial_capital = bt_config.get('initial_capital', 100000)
        self.slippage_pct = bt_config.get('slippage_pct', 0.0005)
        self.train_window = bt_config.get('train_window', 500)
        self.test_window = bt_config.get('test_window', 168)
        self.step_size = bt_config.get('step_size', 168)
        
        # Pull strategy threshold from config
        self.rebalance_threshold = config.get('strategy', {}).get('rebalance_threshold', 0.10)

    def run(self, data: pd.DataFrame) -> Dict[str, Any]:
        """
        Run the allocation-based backtest.
        Iterates over the dataset, re-training the HMM periodically, 
        and determining target allocations for the test window.
        """
        if len(data) < self.train_window + self.test_window:
            raise ValueError("Dataset too small for the configured train/test windows.")
            
        # 1. Feature Engineering (compute features for the whole dataset first for speed)
        logger.info("Computing HMM features for the entire dataset...")
        df = self.feature_engineer.add_technical_indicators(data)
        
        results = []
        
        # Walk-forward iteration
        num_steps = (len(df) - self.train_window) // self.step_size
        logger.info(f"Starting Walk-Forward Backtest ({num_steps} steps expected)...")
        
        current_allocation = 0.0
        
        for start_idx in tqdm(range(0, len(df) - self.train_window, self.step_size)):
            train_end = start_idx + self.train_window
            test_end = min(train_end + self.test_window, len(df))
            
            # Slice Data
            train_df = df.iloc[start_idx:train_end]
            test_df = df.iloc[train_end:test_end]
            
            # Extract Features & Train HMM
            train_features = self.feature_engineer.extract_hmm_features(train_df)
            self.hmm_engine.train(train_features)
            
            if self.hmm_engine.model is None:
                logger.warning(f"Skipping window ending at index {train_end} due to HMM failure.")
                continue
                
            n_states = self.hmm_engine.n_states
            
            # Walk through the test window bar-by-bar
            for i in range(len(test_df)):
                # We can only use data up to the current bar for prediction
                current_bar_idx = train_end + i
                # Take recent context for HMM (e.g., last 50 bars)
                recent_context = df.iloc[current_bar_idx - 50 : current_bar_idx + 1]
                recent_features = self.feature_engineer.extract_hmm_features(recent_context)
                
                # Predict Regime
                regime, probs = self.hmm_engine.predict_regime(recent_features)
                
                # Get Target Allocation
                alloc_info = self.strategy.get_allocation(regime, n_states, probs, recent_context)
                target_allocation = alloc_info['allocation'] * alloc_info['leverage']
                
                # Rebalancing Logic
                bar_data = test_df.iloc[i]
                log_ret = bar_data['log_return']
                
                # If target allocation differs from current by more than threshold, rebalance
                slippage_cost = 0.0
                if abs(target_allocation - current_allocation) >= self.rebalance_threshold:
                    allocation_diff = abs(target_allocation - current_allocation)
                    slippage_cost = allocation_diff * self.slippage_pct
                    current_allocation = target_allocation
                    
                # Calculate Strategy Return for this bar
                # strategy_return = (allocation * asset_return) - slippage_from_rebalancing
                # Using log return approximation: return = exp(log_ret) - 1
                asset_return = np.exp(log_ret) - 1.0
                strategy_return = (current_allocation * asset_return) - slippage_cost
                
                results.append({
                    'timestamp': bar_data.name if hasattr(bar_data, 'name') else current_bar_idx,
                    'close': bar_data['close'],
                    'regime': regime,
                    'target_allocation': target_allocation,
                    'asset_return': asset_return,
                    'strategy_return': strategy_return,
                    'slippage_paid': slippage_cost,
                    'tier': alloc_info['tier']
                })
                
        # Aggregate Results
        results_df = pd.DataFrame(results)
        if results_df.empty:
            return {}
            
        results_df.set_index('timestamp', inplace=True)
        results_df['equity_curve'] = self.initial_capital * (1 + results_df['strategy_return']).cumprod()
        results_df['bh_equity'] = self.initial_capital * (1 + results_df['asset_return']).cumprod()
        
        return {
            'final_equity': results_df['equity_curve'].iloc[-1],
            'bh_equity': results_df['bh_equity'].iloc[-1],
            'timeseries': results_df
        }

