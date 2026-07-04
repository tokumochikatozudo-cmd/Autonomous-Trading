import ccxt.async_support as ccxt
import os
import asyncio
import logging
import json
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class CryptoBrokerClient:
    """
    Robust CCXT wrapper for crypto exchanges (Binance, Bybit, etc.).
    Handles authentication, live/paper modes, and automatic retries.
    """
    
    def __init__(self, exchange_id: str = 'binance', paper_trading: bool = True):
        self.exchange_id = exchange_id
        self.paper_trading = paper_trading
        self.exchange = None
        self._init_exchange()
        
    def _init_exchange(self):
        """Initialize the CCXT exchange instance using .env credentials."""
        # [Phase 7] Use DEMO keys if in paper_trading mode
        prefix = f"{self.exchange_id.upper()}_DEMO" if self.paper_trading else self.exchange_id.upper()
        
        api_key = os.getenv(f"{prefix}_API_KEY")
        
        # [Skill Integration] Path A/B: Check for RSA Private Key Path first, fallback to HMAC Secret
        priv_path = os.getenv(f"{prefix}_API_PRIVATE_KEY_PATH")
        priv_content = os.getenv(f"{prefix}_API_PRIVATE_KEY")
        secret = os.getenv(f"{prefix}_API_SECRET")
        
        actual_secret = None
        if priv_content:
            actual_secret = priv_content.replace("\\n", "\n")
            logger.info(f"Loaded RSA Private Key for {self.exchange_id} directly from environment variable (RSA Auth)")
        elif priv_path and os.path.exists(priv_path):
            try:
                with open(priv_path, 'r') as f:
                    actual_secret = f.read()
                logger.info(f"Loaded RSA Private Key for {self.exchange_id} from {os.path.basename(priv_path)} (RSA Auth)")
            except Exception as e:
                logger.critical(f"Private key path set but file unreadable: {priv_path}. {e}")
                raise
        elif secret:
            actual_secret = secret
            logger.info(f"Loaded HMAC API Secret for {self.exchange_id} (HMAC Auth)")
            
        if not api_key or not actual_secret:
            logger.warning(f"No API keys found for {self.exchange_id}. Running in read-only/unauthenticated mode if possible.")
            
        exchange_class = getattr(ccxt, self.exchange_id)
        
        config = {
            'apiKey': api_key,
            'secret': actual_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'swap',  # [Phase 7] USDT Perpetuals
                'adjustForTimeDifference': True,
                'recvWindow': 10000,
            }
        }
        
        self.exchange = exchange_class(config)
        
        # [Phase 7 Fix] Bybit Cloudflare blocks public endpoints from Datacenter IPs (Railway, Heroku)
        # To bypass this, we load the markets and currencies from offline JSON files.
        # This prevents CCXT from triggering a Cloudflare WAF ban during load_markets().
        try:
            with open('bybit_markets.json', 'r') as f:
                offline_markets = json.load(f)
            self.exchange.set_markets(offline_markets)
            
            with open('bybit_currencies.json', 'r') as f:
                offline_currencies = json.load(f)
            self.exchange.currencies = offline_currencies
            logger.info("Successfully loaded offline Bybit markets to bypass Cloudflare WAF.")
        except Exception as e:
            logger.warning(f"Could not load offline markets cache, falling back to public endpoints: {e}")
                
        if self.paper_trading:
            self.exchange.set_sandbox_mode(True)
            # Bybit's Demo API does not support v5/asset/coin/query-info, so we disable it
            if self.exchange_id == 'bybit':
                self.exchange.has['fetchCurrencies'] = False
            logger.info(f"Initialized {self.exchange_id} in PAPER TRADING (Sandbox) mode.")
        else:
            # Live Trading confirmed by user
            logger.critical("!!! INITIALIZING IN LIVE TRADING MODE !!!")
            logger.warning(f"Initialized {self.exchange_id} in LIVE TRADING mode. Real funds are at risk.")

    async def _safe_execute(self, func, *args, **kwargs) -> Any:
        """Execute CCXT async calls with exponential backoff for rate limits and network errors."""
        max_retries = kwargs.pop('max_retries', 3)
        base_delay = kwargs.pop('base_delay', 1.0)
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except ccxt.RateLimitExceeded as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Rate limit exceeded. Retrying in {delay}s... ({attempt+1}/{max_retries})")
                await asyncio.sleep(delay)
            except ccxt.NetworkError as e:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Network error: {e}. Retrying in {delay}s... ({attempt+1}/{max_retries})")
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error(f"Unexpected broker error: {e}")
                raise
        logger.error("Max retries exceeded for broker operation.")
        raise ccxt.RequestTimeout("Max retries exceeded.")

    async def check_health(self) -> bool:
        """Perform a startup health check and dynamically discover working API domains."""
        
        # If we are using Bybit, we loop through all official fallback domains
        # because Indonesian ISPs block some, and Bybit blocks some VPN IPs.
        domains_to_try = [None]
        if self.exchange_id == 'bybit':
            if self.paper_trading:
                domains_to_try = ['demo.bybit.com']
            else:
                domains_to_try = ['bytick.com', 'bybit.nl', 'bybit.com.hk', 'bybit.com']
            
        for domain in domains_to_try:
            if domain:
                logger.info(f"Trying Bybit API domain: {domain}...")
                self.exchange.hostname = domain
                # If the domain is demo, Bybit uses api-demo.bybit.com, otherwise api.bytick.com
                prefix = "api-" if "demo" in domain else "api."
                base_url = f'https://{prefix}{domain}'
                if "demo.bybit.com" in domain:
                    base_url = 'https://api-demo.bybit.com'
                else:
                    base_url = f'https://api.{domain}'

                self.exchange.urls['api'] = {
                    'spot': base_url,
                    'futures': base_url,
                    'v2': base_url,
                    'public': base_url,
                    'private': base_url,
                }
            
            try:
                # [Phase 7 Fix] Use authenticated fetch_balance instead of public fetch_time 
                # because shared Railway/Cloud IPs often get rate-limited/Cloudflare-blocked on public endpoints.
                await self._safe_execute(self.exchange.fetch_balance, max_retries=1, base_delay=0.5)
                
                logger.info(f"Broker health check passed{f' using {domain}' if domain else ''}.")
                return True
            except Exception as e:
                logger.warning(f"Domain {domain or 'default'} failed: {e}")
                continue
                
        logger.error("Broker health check failed: Exhausted all domain fallbacks.")
        return False

    async def get_balance(self) -> Dict[str, Any]:
        """Fetch total account balance and available margin."""
        return await self._safe_execute(self.exchange.fetch_balance)
        
    async def get_positions(self) -> list:
        """Fetch all open positions (for derivative exchanges)."""
        if self.exchange.has['fetchPositions']:
            return await self._safe_execute(self.exchange.fetch_positions)
        return []
        
    async def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fetch current price and ticker info for a symbol."""
        return await self._safe_execute(self.exchange.fetch_ticker, symbol)
        
    async def create_market_order(self, symbol: str, side: str, amount: float) -> Dict[str, Any]:
        """Execute a market order."""
        logger.info(f"Creating market {side} order for {amount} {symbol}")
        return await self._safe_execute(self.exchange.create_market_order, symbol, side, amount)

    async def close(self):
        """Clean up the CCXT session."""
        if self.exchange:
            await self.exchange.close()
