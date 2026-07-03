import sys
import asyncio
import ccxt.async_support as ccxt
import traceback

async def test():
    exchange = ccxt.bybit()
    print('Testing Bybit connection...')
    try:
        res = await exchange.fetch_time()
        print('Success:', res)
    except Exception as e:
        print('Error:', type(e).__name__)
        traceback.print_exc()
    finally:
        await exchange.close()

asyncio.run(test())
