import asyncio
import os
import ccxt.async_support as ccxt
from dotenv import load_dotenv

load_dotenv('c:/Autonomous Trading/trading-bridge/.env')

async def test():
    api_key = os.getenv('BYBIT_API_KEY')
    priv_path = os.getenv('BYBIT_API_PRIVATE_KEY_PATH')
    
    with open(priv_path, 'r') as f:
        secret = f.read()
        
    exchange = ccxt.bybit({
        'apiKey': api_key,
        'secret': secret,
    })
    
    try:
        bal = await exchange.fetch_balance()
        print('Auth Success! USDT Balance:', bal.get('USDT', {}).get('free'))
    except Exception as e:
        print('Auth Error:', e)
    finally:
        await exchange.close()

asyncio.run(test())
