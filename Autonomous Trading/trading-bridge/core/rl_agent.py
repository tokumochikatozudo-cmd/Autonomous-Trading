import os
import logging
import numpy as np
from stable_baselines3 import PPO
from .rl_env import TradingEnv

logger = logging.getLogger(__name__)

class RLAgent:
    """
    Manages the PPO Reinforcement Learning model to dynamically determine 
    the optimal portfolio allocation based on HMM state probabilities.
    """
    def __init__(self, model_path='monitoring/ppo_agent.zip'):
        self.model_path = model_path
        self.model = None
        self._load_model()
        
    def _load_model(self):
        if os.path.exists(self.model_path):
            try:
                self.model = PPO.load(self.model_path)
                logger.info(f"Loaded existing RL model from {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load RL model: {e}")
                self.model = None
        else:
            logger.info("No existing RL model found. Need to train first.")
            
    def train(self, price_data: np.ndarray, hmm_states: np.ndarray, total_timesteps=50000):
        """
        Train the PPO model offline using historical price data and HMM states.
        """
        logger.info(f"Starting RL training with {len(price_data)} historical bars...")
        env = TradingEnv(price_data, hmm_states)
        
        if self.model is None:
            self.model = PPO("MlpPolicy", env, verbose=0, learning_rate=0.0003)
        else:
            self.model.set_env(env)
            
        self.model.learn(total_timesteps=total_timesteps)
        
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        self.model.save(self.model_path)
        logger.info(f"RL training complete. Model saved to {self.model_path}")
        
    def get_allocation(self, hmm_probs: list, current_allocation: float) -> float:
        """
        Predict the optimal allocation for the current cycle.
        If untrained, fallback to HMM heuristics.
        """
        if self.model is None:
            # Fallback heuristic: 0.90 for low vol (state 0 usually), 0.20 for high vol
            # We assume index with max prob is the current regime
            max_state = np.argmax(hmm_probs)
            if max_state in [0, 1]:  # Assuming 0,1 are calmer
                return 0.90
            else:
                return 0.20
                
        # Format observation: [prob0, prob1, prob2, prob3, current_allocation]
        obs = np.array(hmm_probs + [current_allocation], dtype=np.float32)
        
        action, _states = self.model.predict(obs, deterministic=True)
        # Action is between 0.0 and 0.95
        target_allocation = float(np.clip(action[0], 0.0, 0.95))
        
        logger.info(f"RL Agent output allocation: {target_allocation:.2%}")
        return target_allocation
