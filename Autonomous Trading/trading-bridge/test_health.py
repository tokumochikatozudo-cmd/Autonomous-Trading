import asyncio
from broker.ccxt_client import CryptoBrokerClient
from config_loader import CONFIG

async def main():
    CONFIG['broker']['exchange'] = 'bybit'
    b = CryptoBrokerClient()
    healthy = await b.check_health()
    print("Healthy result:", healthy)
    print("URLs:", b.exchange.urls['api'])
    await b.close()

if __name__ == "__main__":
    asyncio.run(main())
