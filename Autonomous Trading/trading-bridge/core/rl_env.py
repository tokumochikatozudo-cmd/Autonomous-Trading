import numpy as np
import gymnasium as gym
from gymnasium import spaces
import logging

logger = logging.getLogger(__name__)

class TradingEnv(gym.Env):
    """
    Custom Environment that follows gym interface.
    Trains the RL Agent to optimize allocations based on HMM state probabilities.
    """
    metadata = {'render_modes': ['human']}

    def __init__(self, price_data, hmm_states_history):
        super(TradingEnv, self).__init__()
        
        self.price_data = price_data
        self.hmm_states = hmm_states_history
        self.current_step = 0
        self.max_steps = len(self.price_data) - 1
        
        # Action space: continuous allocation from 0.0 to 0.95
        self.action_space = spaces.Box(low=0.0, high=0.95, shape=(1,), dtype=np.float32)
        
        # Observation space: 4 HMM state probabilities + current allocation
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(5,), dtype=np.float32)
        
        self.current_allocation = 0.0
        self.portfolio_value = 18.0  # Starting capital

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        self.current_step = 0
        self.current_allocation = 0.0
        self.portfolio_value = 18.0
        
        obs = np.append(self.hmm_states[self.current_step], self.current_allocation)
        return np.array(obs, dtype=np.float32), {}

    def step(self, action):
        # Action is the target allocation
        target_allocation = float(action[0])
        
        # Get prices
        current_price = self.price_data[self.current_step]
        next_price = self.price_data[self.current_step + 1]
        
        # Calculate P&L for this step
        # If we allocate X%, that portion grows by price change
        price_return = (next_price - current_price) / current_price
        
        # Minus trading fees for allocation shifts (0.10%)
        alloc_shift = abs(target_allocation - self.current_allocation)
        fee_penalty = alloc_shift * 0.001
        
        # Step return
        step_return = (target_allocation * price_return) - fee_penalty
        self.portfolio_value *= (1 + step_return)
        
        # Reward is the step return
        reward = step_return * 100  # Scale up for RL
        
        self.current_allocation = target_allocation
        self.current_step += 1
        
        terminated = self.current_step >= self.max_steps
        truncated = False
        
        if terminated:
            obs = np.zeros(5, dtype=np.float32)
        else:
            obs = np.append(self.hmm_states[self.current_step], self.current_allocation)
            
        return np.array(obs, dtype=np.float32), reward, terminated, truncated, {}
