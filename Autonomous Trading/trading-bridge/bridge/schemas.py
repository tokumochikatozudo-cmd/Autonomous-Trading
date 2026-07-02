from pydantic import BaseModel
from typing import Dict, Any, Optional

class MarketTick(BaseModel):
    """Schema for a real-time market tick."""
    symbol: str
    price: float
    volume: float
    timestamp: float

class TradeSignal(BaseModel):
    """Schema for a trade signal emitted by the strategy."""
    symbol: str
    action: str  # 'buy', 'sell', 'hold'
    confidence: float
    metadata: Optional[Dict[str, Any]] = None
