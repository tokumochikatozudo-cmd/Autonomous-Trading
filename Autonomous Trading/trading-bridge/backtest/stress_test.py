import pandas as pd
import numpy as np

class StressTester:
    """Injects market crashes and gaps to test system robustness."""
    
    @staticmethod
    def simulate_flash_crash(data: pd.DataFrame, index_to_crash: int, drop_pct: float) -> pd.DataFrame:
        """
        Modify data to simulate an instant flash crash at a specific index.
        The close price will drop by drop_pct, simulating a liquidity gap.
        """
        df_stressed = data.copy()
        
        if index_to_crash < 0 or index_to_crash >= len(df_stressed):
            return df_stressed
            
        crash_multiplier = 1.0 - drop_pct
        
        # Apply the crash to the specific candle
        df_stressed.iloc[index_to_crash, df_stressed.columns.get_loc('close')] *= crash_multiplier
        df_stressed.iloc[index_to_crash, df_stressed.columns.get_loc('low')] = min(
            df_stressed.iloc[index_to_crash]['low'], 
            df_stressed.iloc[index_to_crash]['close']
        )
        
        # Adjust all subsequent prices down to maintain continuity of the timeseries chart
        # (Otherwise the next candle open would gap up magically)
        for i in range(index_to_crash + 1, len(df_stressed)):
            df_stressed.iloc[i, df_stressed.columns.get_loc('open')] *= crash_multiplier
            df_stressed.iloc[i, df_stressed.columns.get_loc('high')] *= crash_multiplier
            df_stressed.iloc[i, df_stressed.columns.get_loc('low')] *= crash_multiplier
            df_stressed.iloc[i, df_stressed.columns.get_loc('close')] *= crash_multiplier
            
        return df_stressed
        
    @staticmethod
    def inject_random_gaps(data: pd.DataFrame, num_gaps: int, max_gap_pct: float) -> pd.DataFrame:
        """Inject random overnight/weekend style gaps (though rare in crypto, good for stress testing)."""
        df_stressed = data.copy()
        indices = np.random.choice(range(1, len(df_stressed)), size=num_gaps, replace=False)
        
        for idx in indices:
            gap = np.random.uniform(-max_gap_pct, max_gap_pct)
            multiplier = 1.0 + gap
            # Adjust subsequent prices to lock in the gap
            for i in range(idx, len(df_stressed)):
                df_stressed.iloc[i, df_stressed.columns.get_loc('open')] *= multiplier
                df_stressed.iloc[i, df_stressed.columns.get_loc('high')] *= multiplier
                df_stressed.iloc[i, df_stressed.columns.get_loc('low')] *= multiplier
                df_stressed.iloc[i, df_stressed.columns.get_loc('close')] *= multiplier
                
        return df_stressed

