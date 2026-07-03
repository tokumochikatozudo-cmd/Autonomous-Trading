import asyncio
import traceback
import aiohttp
import requests

def test_sync():
    print("--- Testing Sync (requests) ---")
    try:
        r = requests.get("https://api.bytick.com/v5/market/time", timeout=5)
        print("Sync Success! Status:", r.status_code)
        return True
    except Exception as e:
        print("Sync Failed:", e)
        return False

async def test_async():
    print("\n--- Testing Async (aiohttp) ---")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.bytick.com/v5/market/time", timeout=5) as response:
                print("Async Success! Status:", response.status)
                return True
    except Exception as e:
        print("Async Failed:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    sync_ok = test_sync()
    async_ok = asyncio.run(test_async())
    print(f"\nFinal Result -> Sync: {sync_ok}, Async: {async_ok}")
