import asyncio
import httpx
from src.data.binance_client import BinanceClient

async def main():
    client = BinanceClient()
    try:
        res = await client.get_klines('XAGUSDT', interval='4h', limit=200)
        print(f"Klines length: {len(res)}")
    except Exception as e:
        print(f"Error fetching klines: {e}")
    
    try:
        res = await client.get_ticker('XAGUSDT')
        print(f"Ticker: {res}")
    except Exception as e:
        print(f"Error fetching ticker: {e}")
        
    await client.close()

if __name__ == '__main__':
    asyncio.run(main())
