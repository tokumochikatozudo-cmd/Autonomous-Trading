import pandas as pd
import numpy as np
from typing import Dict, Any

class PerformanceMetrics:
    """Calculates Sharpe, max drawdown, and regime breakdowns."""
    
    @staticmethod
    def calculate_sharpe(returns: pd.Series, risk_free_rate: float = 0.0, periods_per_year: int = 8760) -> float:
        """
        Calculate the annualized Sharpe ratio.
        Default periods_per_year is 8760 for hourly crypto data (24 * 365).
        """
        if returns.std() == 0:
            return 0.0
            
        excess_returns = returns - (risk_free_rate / periods_per_year)
        annualized_mean = excess_returns.mean() * periods_per_year
        annualized_std = returns.std() * np.sqrt(periods_per_year)
        
        return annualized_mean / annualized_std
        
    @staticmethod
    def calculate_max_drawdown(equity_curve: pd.Series) -> float:
        """Calculate maximum drawdown from peak."""
        roll_max = equity_curve.cummax()
        drawdowns = (equity_curve - roll_max) / roll_max
        max_dd = drawdowns.min()
        return abs(max_dd)
        
    @staticmethod
    def regime_breakdown(df: pd.DataFrame) -> Dict[str, Any]:
        """Summarize strategy performance metrics per regime."""
        if 'regime' not in df.columns or 'strategy_return' not in df.columns:
            return {}
            
        breakdown = {}
        grouped = df.groupby('regime')
        
        for regime, group in grouped:
            breakdown[f"Regime {regime}"] = {
                'bars_spent': len(group),
                'percent_time': len(group) / len(df),
                'avg_return': group['strategy_return'].mean(),
                'volatility': group['strategy_return'].std(),
                'avg_allocation': group['target_allocation'].mean() if 'target_allocation' in group else 0.0
            }
            
        return breakdown

