import re

with open("src/core/ta_service.py", "r") as f:
    content = f.read()

# Fix returns
content = content.replace("return 0, [\"❌ Blocked: Daily trend is DOWNTREND — no long signals\"]", "return 0, [\"❌ Blocked: Daily trend is DOWNTREND — no long signals\"], {}")
content = content.replace("return 0, [\"❌ Blocked: Weekly + Daily DOWNTREND — macro bear market\"]", "return 0, [\"❌ Blocked: Weekly + Daily DOWNTREND — macro bear market\"], {}")
content = content.replace("return 0, [\"❌ Blocked: Daily trend is UPTREND — no short signals\"]", "return 0, [\"❌ Blocked: Daily trend is UPTREND — no short signals\"], {}")
content = content.replace("return 0, [\"❌ Blocked: Weekly + Daily UPTREND — macro bull market\"]", "return 0, [\"❌ Blocked: Weekly + Daily UPTREND — macro bull market\"], {}")

# Add breakdown dict
content = content.replace("score = 0\n        reasons: list[str] = []", "score = 0\n        reasons: list[str] = []\n        breakdown: dict = {}")

content = content.replace("return score, reasons", "return score, reasons, breakdown")

with open("src/core/ta_service.py", "w") as f:
    f.write(content)
