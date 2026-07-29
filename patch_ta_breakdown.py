import re

with open("src/core/ta_service.py", "r") as f:
    content = f.read()

# For long setup
content = content.replace('score += 1\n            reasons.append("RSI Momentum: Bullish > 60")', 'score += 1\n            breakdown["rsi"] = breakdown.get("rsi", 0) + 1\n            reasons.append("RSI Momentum: Bullish > 60")')

content = content.replace('score += 1\n            reasons.append("Trend: MA20 > MA50 > MA200")', 'score += 1\n            breakdown["trend_ma"] = breakdown.get("trend_ma", 0) + 1\n            reasons.append("Trend: MA20 > MA50 > MA200")')

content = content.replace('score += 1\n            reasons.append("MACD: Bullish crossover & above 0")', 'score += 1\n            breakdown["macd"] = breakdown.get("macd", 0) + 1\n            reasons.append("MACD: Bullish crossover & above 0")')

content = content.replace('score += 1\n            reasons.append("Thanh khoản ủng hộ (Order Book & Funding tốt) 🌊")', 'score += 1\n            breakdown["liquidity"] = breakdown.get("liquidity", 0) + 1\n            reasons.append("Thanh khoản ủng hộ (Order Book & Funding tốt) 🌊")')

with open("src/core/ta_service.py", "w") as f:
    f.write(content)
