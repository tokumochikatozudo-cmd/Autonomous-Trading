import asyncio
from broker.ccxt_client import CryptoBrokerClient
import sys

async def test():
    client = CryptoBrokerClient('bybit', paper_trading=True)
    health = await client.check_health()
    print("Health:", health)
    try:
        await client.exchange.load_markets()
        print('Markets loaded successfully')
    except Exception as e:
        print(f'Error loading markets: {e}')
    await client.close()

if __name__ == "__main__":
    asyncio.run(test())
