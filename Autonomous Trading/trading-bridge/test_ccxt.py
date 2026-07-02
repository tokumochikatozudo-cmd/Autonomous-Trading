import asyncio
import ccxt.async_support as ccxt

async def test():
    config = {
        'hostname': 'bybit.nl'
    }
    ex = ccxt.bybit(config)
    print("Testing CCXT Bybit Time Fetch on bybit.nl...")
    try:
        time = await ex.fetch_time()
        print("Success! Time:", time)
    except Exception as e:
        print("Error:", e)
    finally:
        await ex.close()

if __name__ == "__main__":
    asyncio.run(test())
