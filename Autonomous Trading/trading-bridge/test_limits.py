import asyncio
import ccxt.async_support as ccxt
async def test():
    exchange = ccxt.bybit()
    await exchange.load_markets()
    market = exchange.market('BTC/USDT')
    print('Min Cost:', market['limits']['cost']['min'])
    print('Min Amount:', market['limits']['amount']['min'])
    await exchange.close()
asyncio.run(test())
