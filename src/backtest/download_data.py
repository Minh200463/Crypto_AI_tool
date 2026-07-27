import httpx
import asyncio
import pandas as pd
from datetime import datetime, timezone, timedelta
import os

BINANCE_URL = "https://api.binance.com/api/v3/klines"

async def fetch_klines(symbol: str, interval: str, start_time: int, end_time: int, limit: int = 1000):
    async with httpx.AsyncClient() as client:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_time,
            "endTime": end_time,
            "limit": limit
        }
        resp = await client.get(BINANCE_URL, params=params, timeout=20.0)
        resp.raise_for_status()
        return resp.json()

async def download_historical_data(symbol: str, interval: str, days: int):
    print(f"Downloading {days} days of {interval} data for {symbol}...")
    
    end_time_dt = datetime.now(timezone.utc)
    start_time_dt = end_time_dt - timedelta(days=days)
    
    end_time = int(end_time_dt.timestamp() * 1000)
    current_start = int(start_time_dt.timestamp() * 1000)
    
    all_klines = []
    
    while current_start < end_time:
        klines = await fetch_klines(symbol, interval, current_start, end_time)
        if not klines:
            break
            
        all_klines.extend(klines)
        
        # Move current_start to the close time of the last candle + 1ms
        current_start = klines[-1][6] + 1
        print(f"Fetched {len(all_klines)} candles... (up to {datetime.fromtimestamp(klines[-1][0]/1000, tz=timezone.utc)})")
        
        # Slight delay to avoid rate limits
        await asyncio.sleep(0.1)
        
    # Convert to DataFrame
    cols = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore']
    df = pd.DataFrame(all_klines, columns=cols)
    
    # Clean up types
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
        
    # Remove duplicates just in case
    df = df.drop_duplicates(subset=['open_time'])
    
    # Save to CSV
    os.makedirs('data', exist_ok=True)
    filename = f"data/{symbol}_{interval}.csv"
    df.to_csv(filename, index=False)
    print(f"Saved {len(df)} candles to {filename}")

if __name__ == "__main__":
    # Download 1.5 years of 4H data for backtesting
    asyncio.run(download_historical_data("BTCUSDT", "4h", 500))
    # Download 1.5 years of 1D data
    asyncio.run(download_historical_data("BTCUSDT", "1d", 500))
    # Download 1.5 years of 1W data
    asyncio.run(download_historical_data("BTCUSDT", "1w", 500))
