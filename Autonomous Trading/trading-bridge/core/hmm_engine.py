import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from typing import Dict, Any, Tuple, List
import logging
from collections import deque

logger = logging.getLogger(__name__)

class HMMEngine:
    """Hidden Markov Model for detecting crypto market regimes based strictly on volatility."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the HMM engine with config parameters."""
        hmm_config = config.get('hmm', {})
        self.n_candidates = hmm_config.get('n_candidates', [3, 4, 5])
        self.n_init = hmm_config.get('n_init', 10)
        self.covariance_type = hmm_config.get('covariance_type', 'full')
        self.min_train_bars = hmm_config.get('min_train_bars', 500)
        self.flicker_window = hmm_config.get('flicker_window', 20)
        self.flicker_threshold = hmm_config.get('flicker_threshold', 4)
        
        self.model = None
        self.n_states = 0
        self.state_history = deque(maxlen=self.flicker_window)
        self.current_stable_state = -1
        
    def _calculate_bic(self, model: GaussianHMM, X: np.ndarray) -> float:
        """Calculate Bayesian Information Criterion to select the optimal number of states."""
        log_likelihood = model.score(X)
        n_features = X.shape[1]
        n_states = model.n_components
        
        # Number of parameters depends on covariance type
        if self.covariance_type == 'full':
            n_params = n_states * (n_states - 1) + 2 * n_states * n_features + n_states * n_features * (n_features - 1) / 2
        elif self.covariance_type == 'diag':
            n_params = n_states * (n_states - 1) + 2 * n_states * n_features
        elif self.covariance_type == 'tied':
            n_params = n_states * (n_states - 1) + n_states * n_features + n_features * (n_features + 1) / 2
        else: # spherical
            n_params = n_states * (n_states - 1) + n_states * n_features + n_states
            
        bic = -2 * log_likelihood + n_params * np.log(X.shape[0])
        return bic

    def _sort_states_by_volatility(self, model: GaussianHMM) -> GaussianHMM:
        """
        Sort states so that State 0 = Lowest Volatility, State N = Highest Volatility.
        We use the determinant (or trace) of the covariance matrix as a proxy for the 'volume' of the state's variance.
        """
        n_states = model.n_components
        variances = []
        
        for i in range(n_states):
            if self.covariance_type == 'full':
                # Trace of the covariance matrix
                variances.append(np.trace(model.covars_[i]))
            elif self.covariance_type == 'diag':
                variances.append(np.sum(model.covars_[i]))
            else:
                variances.append(np.sum(model.covars_[i])) # Simplified fallback
                
        # Get sorted indices
        sorted_indices = np.argsort(variances)
        
        # Create a new model and remap everything
        sorted_model = GaussianHMM(n_components=n_states, covariance_type=self.covariance_type)
        sorted_model.startprob_ = model.startprob_[sorted_indices]
        sorted_model.transmat_ = model.transmat_[sorted_indices][:, sorted_indices]
        sorted_model.means_ = model.means_[sorted_indices]
        sorted_model.covars_ = model.covars_[sorted_indices]
        
        return sorted_model

    def train(self, features: np.ndarray) -> None:
        """Train the HMM model on historical features, selecting the best n_components via BIC."""
        if len(features) < self.min_train_bars:
            logger.warning(f"Not enough data to train HMM. Need {self.min_train_bars}, got {len(features)}.")
            return

        best_bic = np.inf
        best_model = None

        logger.info(f"Training HMM across candidates: {self.n_candidates}")
        for n_states in self.n_candidates:
            try:
                model = GaussianHMM(n_components=n_states, covariance_type=self.covariance_type, 
                                    n_iter=100, init_params='stmc')
                model.fit(features)
                
                bic = self._calculate_bic(model, features)
                logger.debug(f"HMM with {n_states} states fitted. BIC: {bic:.2f}")
                
                if bic < best_bic:
                    best_bic = bic
                    best_model = model
            except Exception as e:
                logger.warning(f"Failed to fit HMM with {n_states} states: {e}")

        if best_model is None:
            logger.error("Failed to fit any HMM model.")
            return

        # Sort states by variance to ensure State 0 is calm and State N is turbulent
        self.model = self._sort_states_by_volatility(best_model)
        self.n_states = self.model.n_components
        logger.info(f"Optimal HMM selected with {self.n_states} states (BIC: {best_bic:.2f}).")

    def _apply_flicker_filter(self, raw_state: int) -> int:
        """Apply a rolling window filter to prevent rapid toggling between regimes."""
        self.state_history.append(raw_state)
        
        if len(self.state_history) < self.flicker_window:
            self.current_stable_state = raw_state
            return raw_state
            
        # Count occurrences of the raw_state in the recent window
        state_counts = pd.Series(list(self.state_history)).value_counts()
        most_common_state = state_counts.index[0]
        
        # If the most common state occurs >= flicker_threshold times, we consider it stable
        if state_counts.iloc[0] >= self.flicker_threshold:
            self.current_stable_state = most_common_state
            
        return self.current_stable_state

    def predict_regime(self, recent_features: np.ndarray) -> Tuple[int, np.ndarray]:
        """
        Predict the current market regime based on recent features.
        Returns the stable regime ID and the state probabilities.
        """
        if self.model is None:
            logger.warning("HMM Model is not trained yet.")
            return -1, np.array([])
            
        # Predict the hidden states (returns an array of states, we want the last one)
        _, states = self.model.decode(recent_features)
        raw_state = states[-1]
        
        # Get probabilities for the last observation
        probabilities = self.model.predict_proba(recent_features)[-1]
        
        stable_state = self._apply_flicker_filter(raw_state)
        return stable_state, probabilities

