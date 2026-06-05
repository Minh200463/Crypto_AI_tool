# CryptoAI Tool — Master Build Prompt
> Copy & paste this entire document into your AI agent (Antigravity or any coding agent) to analyze and build the project.

---

## 1. PROJECT OVERVIEW

Build a **personal crypto trading assistant system** — starting as a Telegram Bot (Phase 1), scaling to a Web Dashboard (Phase 2), and eventually a Mobile App (Phase 3). The system helps a beginner crypto trader (F0) monitor, analyze, and manage risk for cryptocurrency positions on Binance, with AI-powered insights delivered in real time.

**Core philosophy:**
- Not a trading bot that executes orders automatically (Phase 1)
- An intelligent assistant that provides analysis, alerts, and risk management tools
- AI is used only where truly necessary — most logic is pure code
- Designed to scale: one backend serves all interfaces (Telegram, Web, Mobile)
- Language: **English** (UI, AI outputs, code, comments)

---

## 2. SYSTEM ARCHITECTURE

### Architecture Pattern: Layered Architecture + Clean Architecture principles

```
┌─────────────────────────────────────────────┐
│         LAYER 1 — PRESENTATION              │
│  Telegram Bot (P1) │ Web (P2) │ Mobile (P3) │
└─────────────────────────────────────────────┘
                      ↕ REST / WebSocket
┌─────────────────────────────────────────────┐
│         LAYER 2 — APPLICATION CORE          │
│  API Gateway │ Alert Engine │ TA Service    │
│  Risk Manager │ Scheduler │ News Aggregator │
│  Portfolio Tracker │ Notification Service   │
└─────────────────────────────────────────────┘
                      ↕ API calls
┌─────────────────────────────────────────────┐
│         LAYER 3 — AI LAYER                  │
│  Claude Client │ Prompt Templates           │
│  Context Builder │ Provider Abstraction     │
└─────────────────────────────────────────────┘
                      ↕ query / store
┌─────────────────────────────────────────────┐
│         LAYER 4 — DATA LAYER                │
│  Binance API │ CryptoPanic │ Alternative.me  │
│  PostgreSQL │ Redis │ Supabase              │
└─────────────────────────────────────────────┘
```

### Design Patterns to implement:
1. **Repository Pattern** — `UserRepo`, `AlertRepo`, `TradeRepo` (swap DB without touching business logic)
2. **Observer Pattern** — Alert Engine: price stream → observers → fire on match
3. **Strategy Pattern** — AI prompts: `NewsStrategy`, `AnalysisStrategy`, `RiskStrategy`
4. **Factory Pattern** — `NotificationFactory.create("telegram")` → easy add Zalo/Email later
5. **Circuit Breaker** — Wrap all external API calls (Binance, Claude) with retry + fallback
6. **Cache-Aside** — Redis: check cache → hit: return, miss: fetch API → store TTL 5min → return

---

## 3. PROJECT STRUCTURE

```
crypto-ai-tool/
├── src/
│   ├── core/                    # Business logic — no framework dependency
│   │   ├── alert_service.py     # Alert trigger logic
│   │   ├── ta_service.py        # Technical analysis computation
│   │   ├── risk_service.py      # Position sizing, TP/SL calculation
│   │   ├── news_service.py      # News aggregation + processing
│   │   ├── portfolio_service.py # P&L tracking
│   │   └── scheduler_service.py # Cron job definitions
│   ├── ai/
│   │   ├── base.py              # AIProvider abstract interface
│   │   ├── claude_provider.py   # Claude implementation
│   │   ├── openai_provider.py   # OpenAI fallback implementation
│   │   ├── gemini_provider.py   # Gemini (cheap batch) implementation
│   │   ├── factory.py           # get_provider() — reads from config
│   │   ├── context_builder.py   # Build prompt context from raw data
│   │   └── prompts/             # Jinja2 prompt templates
│   │       ├── morning_brief.j2
│   │       ├── technical_analysis.j2
│   │       ├── trade_journal_review.j2
│   │       └── risk_explanation.j2
│   ├── interfaces/
│   │   ├── telegram/
│   │   │   ├── bot.py           # Bot setup + polling
│   │   │   └── handlers.py      # Command handlers (/price, /analyze, etc.)
│   │   ├── web/
│   │   │   └── routes.py        # FastAPI REST + WebSocket routes
│   │   └── scheduler/
│   │       └── jobs.py          # APScheduler job definitions
│   └── data/
│       ├── models/              # SQLAlchemy ORM models
│       │   ├── user.py
│       │   ├── alert.py
│       │   ├── trade.py
│       │   └── portfolio.py
│       ├── repositories/        # Repository pattern implementations
│       │   ├── base.py
│       │   ├── user_repo.py
│       │   ├── alert_repo.py
│       │   └── trade_repo.py
│       └── cache.py             # Redis cache-aside helpers
├── tests/
│   ├── unit/
│   └── integration/
├── config/
│   ├── settings.py              # Pydantic settings from .env
│   └── .env.example
├── migrations/                  # Alembic migrations
├── docker/
│   └── docker-compose.yml       # PostgreSQL + Redis + App
└── requirements.txt
```

---

## 4. FULL TECH STACK

### Backend & Core
| Package | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Main language |
| FastAPI | latest | REST API + WebSocket |
| APScheduler | 3.x | Cron jobs (morning brief, price fetch) |
| Pydantic v2 | latest | Data validation everywhere |
| tenacity | latest | Retry + Circuit Breaker for external APIs |

### Database & Storage
| Package | Purpose |
|---|---|
| PostgreSQL 15+ | Primary DB — users, alerts, trades, portfolio |
| SQLAlchemy 2.0 (async) | ORM — Repository pattern |
| Alembic | Database migrations |
| Redis 7+ | Cache (TTL 5min) + Alert queue |
| Supabase | Managed PostgreSQL + Auth (free tier for MVP) |

### Crypto Data Sources (all free)
| Source | Purpose |
|---|---|
| `python-binance` | Binance REST API wrapper |
| `ccxt` | Multi-exchange support (future: OKX, Bybit) |
| Binance WebSocket | Realtime price stream (ticker, kline, aggTrade) |
| CryptoPanic API | Crypto news aggregator — filter by coin |
| Alternative.me API | Fear & Greed Index — completely free |
| `feedparser` | RSS feeds — CoinDesk, Decrypt, Cointelegraph |

### Technical Analysis
| Package | Purpose |
|---|---|
| `pandas` | Time-series data processing |
| `pandas-ta` | RSI, MACD, Bollinger Bands, MA, ATR — 1 line |
| `numpy` | Fast numerical operations |
| `scipy` | Swing high/low detection for support/resistance |

### AI Layer
| Component | Model/Tool | Use Case | Cost |
|---|---|---|---|
| Anthropic SDK | claude-haiku-4-5 | Morning brief, news summary, alert messages | ~$0.80/1M tokens |
| Anthropic SDK | claude-sonnet-4-6 | On-demand analysis, trade journal review, chat | ~$3/1M tokens |
| OpenAI SDK | gpt-4o-mini | Fallback when Claude API is down | ~$0.15/1M tokens |
| finBERT | Local model | News sentiment classification — financial domain | $0 free |
| spaCy NER | Local model | Extract coin names from news articles | $0 free |

**AI Provider Abstraction** — implement `AIProvider` abstract base class so any provider can be swapped via `AI_PROVIDER=claude` in `.env`.

### Interfaces
**Phase 1 — Telegram Bot:**
- `python-telegram-bot` 20+ (async)
- Telegram Bot API (free, unlimited users)

**Phase 2 — Web Dashboard:**
- Next.js 14 (App Router, TypeScript)
- TradingView Lightweight Charts (free, professional candlestick charts)
- Tailwind CSS
- shadcn/ui components
- Zustand (state management)

**Phase 3 — Mobile (future):**
- React Native + Expo
- Expo Push Notifications

### Auth, Payment, DevOps
| Tool | Purpose |
|---|---|
| Supabase Auth | JWT + OAuth (Google) |
| python-jose | JWT validation in FastAPI |
| passlib + bcrypt | Password hashing |
| Stripe | International subscription payments |
| VNPay / MoMo | Vietnamese payment (Phase 2+) |
| Railway | Deploy FastAPI + Redis (free tier) |
| Vercel | Deploy Next.js frontend (free tier) |
| Docker + Compose | Local dev environment |
| Sentry | Error tracking in production |
| pytest + pytest-asyncio | Unit + integration testing |

---

## 5. CORE FEATURES (Phase 1 — Telegram Bot)

### 5.1 Realtime Price & Watchlist
- Command: `/price BTC` → returns current price, 24h change %, volume
- Command: `/watchlist` → shows all tracked coins with live prices
- Command: `/watch BTC ETH SOL` → add coins to watchlist
- Data source: Binance WebSocket stream (ticker endpoint)
- Cache: Redis TTL 30 seconds

### 5.2 Technical Analysis on Demand
- Command: `/analyze BTC` (default 4H timeframe)
- Command: `/analyze ETH 1h` (specify timeframe: 1m, 5m, 15m, 1h, 4h, 1d)
- **Logic (NO AI involved):**
  - Fetch 200 candles from `GET /api/v3/klines`
  - Compute: RSI(14), MACD(12,26,9), Bollinger Bands(20,2), MA20/50/200, ATR(14)
  - Detect: trend direction, BB position, MACD signal (bullish/bearish crossover)
  - Fetch: Funding Rate (Futures endpoint), Fear & Greed Index
- **AI involvement:** Claude Sonnet receives computed numbers + interprets in natural language
- Output format:
  ```
  📊 BTC/USDT — 4H Analysis
  Price: $67,240 | RSI: 58 (neutral) | MACD: bullish crossover
  MA20: $65,800 | Bollinger: mid-band
  Volume: $28.4B (+35% vs avg) | Funding: 0.012%
  
  🤖 AI Insight: [Claude's interpretation in plain English]
  ⚠️ For reference only — not financial advice
  ```

### 5.3 TP/SL Suggestion
- Command: `/tpsl BTC 67000` → entry price
- Command: `/tpsl BTC 67000 short` → for short positions
- **Logic (pure code — no AI):**
  - ATR(14) from 4H candles → SL = entry − 1.5×ATR (long) or entry + 1.5×ATR (short)
  - Resistance levels: swing highs in last 50 candles (scipy.signal.find_peaks)
  - Support levels: swing lows in last 50 candles
  - TP1 = nearest resistance above entry
  - TP2 = second resistance level
  - TP3 = ATH distance target
  - R:R ratio = (TP - entry) / (entry - SL)
- **AI involvement:** Claude explains the levels in plain English (why this SL, what TP2 means)
- Output: table with TP1/TP2/TP3/SL prices, % change, R:R ratio

### 5.4 Risk Manager / Position Sizing
- Command: `/risk 1000 BTC 67000 63850` → (capital, coin, entry, stop_loss)
- Command: `/risk 1000 BTC 67000 63850 10` → with leverage
- **Logic (pure math — no AI needed):**
  ```python
  risk_amount = capital * 0.02  # 2% rule
  sl_distance = entry_price - stop_loss
  position_size_usd = (risk_amount / sl_distance) * entry_price
  quantity = position_size_usd / entry_price
  # With leverage:
  margin_required = position_size_usd / leverage
  liquidation_price = entry * (1 - 1/leverage + 0.005)  # approx
  ```
- Output: max quantity, total position USD, margin required, liquidation price, risk %

### 5.5 Fee Calculator
- Command: `/fee BTC 67000 0.01 buy` → (coin, price, quantity, side)
- **Logic (pure math):**
  ```python
  # Binance standard fees
  maker_fee = 0.001   # 0.1%
  taker_fee = 0.001
  trade_value = price * quantity
  fee = trade_value * taker_fee
  breakeven_price = entry * (1 + taker_fee * 2 + 0.001)  # includes sell fee + tax approx
  ```

### 5.6 Smart Alerts (24/7 background)
- Command: `/setalert BTC 70000` → price above
- Command: `/setalert BTC 60000 below` → price below
- Command: `/setalert ETH 5pct` → 5% move in 1 hour
- Command: `/alerts` → list active alerts
- Command: `/clear BTC` → remove alerts for BTC
- **Alert types (all pure code):**
  1. **Price threshold** — coin crosses set price
  2. **% change alert** — coin moves >X% in 1 hour
  3. **Volume spike** — volume > 3× 24h average
  4. **Funding rate extreme** — funding rate > 0.1% or < -0.05%
  5. **RSI extreme** — RSI drops below 30 or above 70
- **Anti-spam logic:** max 3 alerts/coin/hour, 30-minute cooldown per trigger, rate limit Redis
- **AI involvement:** Claude Haiku generates the alert message with brief context (1-2 sentences)

### 5.7 AI Morning Brief
- Automatic: every day at 7:00 AM (user's timezone)
- **Data assembled (no AI):**
  - BTC/ETH/top coins 24h performance
  - Fear & Greed Index value + trend
  - BTC Dominance change
  - User's watchlist performance
  - Funding rates snapshot
  - Top 5 news from CryptoPanic (last 12h, importance=high)
- **AI involvement:** Claude Haiku synthesizes all data into a 150-200 word brief
- Prompt context includes: market data + news titles + user's watchlist

### 5.8 Trade Journal
- Command: `/log BTC buy 67000 0.01` → log a trade (coin, side, price, qty)
- Command: `/log BTC sell 68500 0.01` → close trade
- Command: `/history` → last 10 trades with P&L
- Command: `/report` → weekly summary
- **Weekly report logic:**
  - Win rate, total P&L, best/worst trade, avg R:R
  - **AI involvement:** Claude Sonnet analyzes patterns in trade history and identifies behavioral mistakes
  - Example insight: "You cut losses earlier than your set SL 60% of the time. Your ETH trades outperform BTC trades significantly."

### 5.9 Trade Signal Suggestion (Entry / TP / SL Recommendation)

> **Scope:** Personal use tool only. All outputs must include mandatory disclaimer. Never market this as financial advice.

- Command: `/signal BTC` → full signal on default 4H timeframe
- Command: `/signal ETH 1h` → signal on specific timeframe
- Command: `/signal BTC long` → bias-filtered signal (only long setups)
- Command: `/signal BTC short` → bias-filtered signal (only short setups)

#### Data Inputs Required (fetch before AI call)
```
1. OHLCV candles (200 candles, specified timeframe) → from Binance /api/v3/klines
2. Indicators (computed via pandas-ta, no AI):
   - RSI(14), MACD(12,26,9), Bollinger Bands(20,2)
   - MA20, MA50, MA200
   - ATR(14) → used for SL/TP distance
3. Swing highs/lows (last 50 candles) → scipy.signal.find_peaks → support/resistance levels
4. Order book depth → GET /api/v3/depth (top 20 bids/asks) → detect bid/ask wall
5. Funding rate → GET /fapi/v1/premiumIndex → sentiment proxy
6. Fear & Greed Index → Alternative.me API (cached Redis 1h)
7. Volume vs 20-period average → detect volume confirmation
```

#### Signal Logic — Rule-Based Scoring (pure code, no AI)

Implement a **confluence scoring system** (0–7 points). Signal fires only if score ≥ 4.

```python
def score_long_setup(indicators: dict) -> tuple[int, list[str]]:
    score = 0
    reasons = []

    # 1. RSI
    if indicators["rsi"] < 35:
        score += 2
        reasons.append(f"RSI oversold ({indicators['rsi']:.1f})")
    elif indicators["rsi"] < 45:
        score += 1
        reasons.append(f"RSI approaching oversold ({indicators['rsi']:.1f})")

    # 2. MACD
    if indicators["macd_crossover"] == "bullish":
        score += 2
        reasons.append("MACD bullish crossover")
    elif indicators["macd_histogram"] > 0:
        score += 1
        reasons.append("MACD histogram positive")

    # 3. Bollinger Band position
    if indicators["price"] <= indicators["bb_lower"]:
        score += 2
        reasons.append("Price at/below Bollinger lower band")
    elif indicators["price"] <= indicators["bb_mid"]:
        score += 1
        reasons.append("Price below Bollinger midband")

    # 4. MA trend filter
    if indicators["ma20"] > indicators["ma50"] > indicators["ma200"]:
        score += 1
        reasons.append("MA20 > MA50 > MA200 (uptrend structure)")

    # 5. Volume confirmation
    if indicators["volume"] > indicators["avg_volume_20"] * 1.5:
        score += 1
        reasons.append("Volume spike confirms momentum")

    # 6. Funding rate — negative = shorts paying longs (bullish)
    if indicators["funding_rate"] < -0.01:
        score += 1
        reasons.append(f"Negative funding rate ({indicators['funding_rate']:.3f}%) favors long")

    return score, reasons

# Mirror logic for short setup (reverse all conditions)
```

#### Entry / TP / SL Calculation (pure code)

```python
def calculate_trade_levels(side: str, entry: float, indicators: dict, swing_levels: dict) -> dict:
    atr = indicators["atr"]

    if side == "long":
        # Stop Loss: below nearest swing low - 0.5×ATR buffer
        sl = swing_levels["nearest_support"] - (atr * 0.5)
        sl = min(sl, entry - atr * 1.5)  # floor: at least 1.5×ATR away

        # Take Profits: use swing highs / resistance levels
        tp1 = swing_levels["resistance_1"]    # nearest resistance
        tp2 = swing_levels["resistance_2"]    # second resistance
        tp3 = entry + (entry - sl) * 3        # 1:3 R:R target

    elif side == "short":
        sl = swing_levels["nearest_resistance"] + (atr * 0.5)
        sl = max(sl, entry + atr * 1.5)

        tp1 = swing_levels["support_1"]
        tp2 = swing_levels["support_2"]
        tp3 = entry - (sl - entry) * 3

    rr1 = (tp1 - entry) / (entry - sl) if side == "long" else (entry - tp1) / (sl - entry)
    rr2 = (tp2 - entry) / (entry - sl) if side == "long" else (entry - tp2) / (sl - entry)

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "sl_pct": abs(entry - sl) / entry * 100,
        "tp1_pct": abs(tp1 - entry) / entry * 100,
        "tp2_pct": abs(tp2 - entry) / entry * 100,
        "rr1": rr1,
        "rr2": rr2,
    }
```

#### AI Involvement (Claude Sonnet)

After rule-based scoring, pass results to Claude Sonnet for natural language interpretation:

```
Prompt context includes:
- Score: X/7, side: LONG/SHORT/NO SIGNAL
- All indicator values (numbers only)
- Confluence reasons list
- Calculated levels (entry, SL, TP1, TP2, TP3)
- Market context: Fear & Greed value, funding rate

Claude's role:
- Explain WHY each level was chosen (not just what)
- Flag any conflicting signals (e.g. bullish TA but bearish funding)
- Assess setup quality: "strong", "moderate", "weak confluence"
- Suggest partial entry strategy if score is borderline (4-5/7)
- NEVER say "buy" or "sell" — use "potential long setup", "entry zone", "invalidation level"
```

#### Output Format

```
🎯 BTC/USDT — Signal Analysis (4H)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 Bias: LONG  |  Confluence: 5/7 (Moderate)

📍 Levels:
   Entry zone : $66,800 – $67,200
   Stop Loss  : $64,900  (-3.1%)
   TP1        : $69,500  (+3.4%)  R:R = 1:1.1
   TP2        : $72,000  (+7.1%)  R:R = 1:2.3
   TP3        : $75,400 (+12.2%)  R:R = 1:3.9

✅ Confluence signals:
   • RSI oversold (32.4)
   • MACD bullish crossover
   • Price at Bollinger lower band
   • Volume spike confirms momentum
   • Negative funding rate (-0.015%)

⚠️  Conflicting: MA structure not fully aligned (MA50 < MA200)

🤖 AI Insight:
   [Claude's 3-4 sentence natural language interpretation]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚠️  Kỹ thuật tham khảo — không phải tư vấn tài chính.
    Quyết định giao dịch là trách nhiệm của bạn.
```

If score < 4:
```
⛔ BTC/USDT — No Clear Signal (4H)
Confluence: 2/7 — conditions not aligned for a high-probability setup.
[Brief reason: what's missing]
```

#### New Telegram Commands

```
/signal BTC               → signal on 4H (default)
/signal ETH 1h            → signal on 1H
/signal BTC long          → only evaluate long conditions
/signal BTC short         → only evaluate short conditions
/signal BTC 4h full       → signal + detailed breakdown of all 7 conditions
```

#### What Uses AI vs What Doesn't (updated table row)

| Feature | AI? | Tool/Model |
|---|---|---|
| Confluence score calculation | ❌ No | Python rule-based |
| Entry / TP / SL level math | ❌ No | pandas + scipy |
| Signal interpretation & explanation | ✅ LLM | Claude Sonnet |

#### Implementation Rules for This Feature

1. **Minimum score gate:** Never show a directional signal if score < 4/7 — output "No clear signal" instead
2. **R:R filter:** If best R:R (TP1) < 1.0, do not suggest entry — risk not justified
3. **Disclaimer mandatory:** Every `/signal` response must end with the disclaimer block, non-removable
4. **No guarantee language:** Claude prompt must explicitly forbid words like "will", "definitely", "guaranteed"
5. **Rate limit:** Max 10 `/signal` calls per user per hour (prevent abuse / AI cost control)
6. **Timeframe note:** Signals on 1m/5m timeframes are marked as "high noise — low reliability"
7. **Log all signals:** Store every generated signal in DB (`signals` table) for future backtesting
8. **New DB table:**

```sql
CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    side VARCHAR(10) NOT NULL,           -- long | short | none
    confluence_score INTEGER NOT NULL,
    entry_price DECIMAL(30,10),
    sl_price DECIMAL(30,10),
    tp1_price DECIMAL(30,10),
    tp2_price DECIMAL(30,10),
    tp3_price DECIMAL(30,10),
    rr_tp1 DECIMAL(6,2),
    rr_tp2 DECIMAL(6,2),
    indicator_snapshot JSONB,            -- full indicators at time of signal
    ai_interpretation TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON signals (user_id, symbol, created_at DESC);
```

---

## 6. AI LAYER IMPLEMENTATION

### 6.1 AIProvider Abstract Interface
```python
# src/ai/base.py
from abc import ABC, abstractmethod

class AIProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str, system: str, max_tokens: int = 1000) -> str:
        """High-quality model — use for on-demand analysis"""
        ...

    @abstractmethod
    async def complete_fast(self, prompt: str, system: str = "", max_tokens: int = 500) -> str:
        """Fast/cheap model — use for batch tasks (news summary, alert messages)"""
        ...
```

### 6.2 Provider selection logic
```python
# src/ai/factory.py
def get_provider() -> AIProvider:
    provider = settings.AI_PROVIDER  # "claude" | "openai" | "gemini"
    if provider == "claude":
        return ClaudeProvider()
    if provider == "openai":
        return OpenAIProvider()
    raise ValueError(f"Unknown provider: {provider}")

# Fallback wrapper
async def complete_with_fallback(prompt, system):
    try:
        return await primary.complete(prompt, system)
    except APIError:
        return await fallback.complete(prompt, system)  # auto-switch to OpenAI
```

### 6.3 What uses AI vs what doesn't
| Feature | AI? | Tool/Model |
|---|---|---|
| Realtime price | ❌ No | Binance WebSocket |
| RSI / MACD / Bollinger | ❌ No | pandas-ta |
| Price alerts / volume alerts | ❌ No | Redis + cron logic |
| Position sizing calculation | ❌ No | Python math |
| TP/SL levels calculation | ❌ No | pandas + scipy |
| Fee calculation | ❌ No | Python math |
| P&L tracking | ❌ No | PostgreSQL |
| News sentiment classify | 🟡 Small AI | finBERT (local, $0) |
| Extract coin names from news | 🟡 Small AI | spaCy NER (local, $0) |
| Morning brief generation | ✅ LLM | Claude Haiku |
| Technical analysis interpretation | ✅ LLM | Claude Sonnet |
| Alert message generation | ✅ LLM | Claude Haiku |
| Trade journal analysis | ✅ LLM | Claude Sonnet |
| Free chat | ✅ LLM | Claude Sonnet |
| Signal confluence scoring | ❌ No | Python rule-based |
| Signal entry/TP/SL calculation | ❌ No | pandas + scipy |
| Signal interpretation & explanation | ✅ LLM | Claude Sonnet |

### 6.4 System prompt for all AI calls
Every AI call must include in system prompt:
```
You are a crypto market analysis assistant. You provide factual technical analysis 
based on data provided to you. You NEVER recommend buying or selling specific assets. 
You NEVER predict prices. You present analysis as reference information only.
Always end responses with: "This is for informational purposes only, not financial advice."
Keep responses concise and in plain English.
```

---

## 7. DATA MODELS (PostgreSQL)

```sql
-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    telegram_id BIGINT UNIQUE,
    username VARCHAR(100),
    timezone VARCHAR(50) DEFAULT 'UTC',
    plan VARCHAR(20) DEFAULT 'free',  -- free | pro | pro_plus
    capital DECIMAL(20,2),            -- user's stated capital for risk calc
    risk_per_trade DECIMAL(5,4) DEFAULT 0.02,  -- 2% default
    morning_brief_enabled BOOLEAN DEFAULT true,
    morning_brief_time TIME DEFAULT '07:00:00',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Watchlist
CREATE TABLE watchlist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    symbol VARCHAR(20) NOT NULL,  -- "BTCUSDT"
    added_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, symbol)
);

-- Alerts
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    symbol VARCHAR(20) NOT NULL,
    alert_type VARCHAR(30) NOT NULL,  -- price_above | price_below | pct_change | volume_spike | rsi_extreme | funding_extreme
    threshold DECIMAL(30,10),
    direction VARCHAR(10),            -- above | below
    is_active BOOLEAN DEFAULT true,
    triggered_at TIMESTAMPTZ,
    cooldown_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Trades (trade journal)
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,        -- buy | sell
    entry_price DECIMAL(30,10) NOT NULL,
    exit_price DECIMAL(30,10),
    quantity DECIMAL(30,10) NOT NULL,
    leverage INTEGER DEFAULT 1,
    stop_loss DECIMAL(30,10),
    take_profit DECIMAL(30,10),
    status VARCHAR(20) DEFAULT 'open', -- open | closed
    pnl DECIMAL(20,4),
    pnl_pct DECIMAL(10,4),
    notes TEXT,
    entry_at TIMESTAMPTZ DEFAULT NOW(),
    exit_at TIMESTAMPTZ
);

-- Price snapshots (for backtesting alerts, historical charts)
CREATE TABLE price_snapshots (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    price DECIMAL(30,10) NOT NULL,
    volume_24h DECIMAL(30,10),
    change_pct_24h DECIMAL(10,4),
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON price_snapshots (symbol, recorded_at DESC);
```

---

## 8. BINANCE API ENDPOINTS TO USE

```
Market Data (no auth required):
GET /api/v3/ticker/24hr          → 24h price stats for all symbols
GET /api/v3/klines               → candlestick data (OHLCV)
  params: symbol=BTCUSDT, interval=4h, limit=200
GET /api/v3/depth                → order book
GET /fapi/v1/fundingRate          → futures funding rate history
GET /fapi/v1/premiumIndex         → current funding rate + mark price

WebSocket streams (no auth):
wss://stream.binance.com/ws/{symbol}@ticker     → realtime price
wss://stream.binance.com/ws/{symbol}@kline_1m   → 1min candles
wss://stream.binance.com/ws/{symbol}@aggTrade   → realtime trades

Account (API key required — Phase 2):
GET  /api/v3/account             → balances
POST /api/v3/order               → place order
GET  /api/v3/myTrades            → trade history

Testnet base URL: https://testnet.binance.vision
```

---

## 9. TELEGRAM BOT COMMANDS

```
/start          → Welcome message + setup wizard (timezone, capital, risk %)
/help           → List all commands

PRICE & MARKET
/price BTC                    → current price + 24h stats
/market                       → top 10 coins overview + Fear & Greed
/watchlist                    → show all watched coins
/watch BTC ETH SOL            → add to watchlist
/unwatch BTC                  → remove from watchlist

ANALYSIS
/analyze BTC                  → full TA on 4H (default)
/analyze ETH 1h               → TA on specific timeframe
/news BTC                     → latest news for coin (AI summarized)
/sentiment BTC                → market sentiment summary
/signal BTC                   → trade signal with entry/TP/SL (4H default)
/signal ETH 1h                → trade signal on specific timeframe
/signal BTC long              → long-only signal evaluation
/signal BTC short             → short-only signal evaluation
/signal BTC 4h full           → signal + full confluence breakdown

TRADING TOOLS
/tpsl BTC 67000               → TP/SL levels for long at $67,000
/tpsl BTC 67000 short         → TP/SL for short
/risk 1000 BTC 67000 63850    → position size (capital, coin, entry, sl)
/risk 1000 BTC 67000 63850 10 → with 10x leverage
/fee BTC 67000 0.01           → calculate trading fees

ALERTS
/setalert BTC 70000           → alert when BTC > $70,000
/setalert BTC 60000 below     → alert when BTC < $60,000
/setalert ETH 5pct            → alert on 5% move in 1h
/alerts                       → list all active alerts
/clear BTC                    → remove all BTC alerts
/clearall                     → remove all alerts

JOURNAL
/log BTC buy 67000 0.01       → log trade entry
/log BTC sell 68500 0.01      → log trade exit
/history                      → last 10 trades
/report                       → weekly P&L report with AI insights

SETTINGS
/settings                     → view current settings
/capital 5000                 → set trading capital (USD)
/risk 2                       → set risk per trade (%)
/timezone Asia/Ho_Chi_Minh    → set timezone
/brief on|off                 → toggle morning brief
/brieftime 07:00              → set morning brief time
```

---

## 10. SCHEDULER JOBS

```python
# Every 5 minutes (market hours)
job_fetch_prices()         → fetch all watchlist prices → store Redis + DB snapshot

# Every 30 minutes
job_fetch_news()           → CryptoPanic API → finBERT sentiment → store DB
job_check_alerts()         → compare prices vs all active alerts → trigger if match

# Every hour
job_update_fear_greed()    → Alternative.me API → store Redis
job_check_rsi_alerts()     → compute RSI for all watchlist coins → trigger extremes
job_scan_signals()         → run confluence scoring on all watchlist coins → cache top signals in Redis (optional: auto-notify if score ≥ 6/7)

# Daily 7:00 AM (per user timezone)
job_morning_brief()        → assemble market data + news → Claude Haiku → send Telegram

# Weekly Sunday 9:00 AM
job_weekly_report()        → aggregate user trades → Claude Sonnet → send Telegram
```

---

## 11. PHASE 2 — WEB DASHBOARD (build after Phase 1 validated)

### Tech Stack
- **Frontend:** Next.js 14 (App Router, TypeScript, Tailwind CSS, shadcn/ui)
- **Charts:** TradingView Lightweight Charts (free)
- **State:** Zustand
- **Backend:** same FastAPI — just add new route handlers

### Dashboard Pages
1. **Overview** — watchlist prices, Fear & Greed, P&L summary, active alerts count
2. **Analysis** — coin selector → full chart with indicators + AI analysis panel
3. **Screener** — filter all coins: RSI < 30, volume spike, MACD crossover, etc.
4. **Journal** — trade log table, P&L chart over time, win rate stats
5. **Alerts** — manage all alerts visually (add/remove/status)
6. **Settings** — capital, risk %, timezone, notification preferences, plan

### Subscription Tiers (Phase 2)
```
Free:
  - Watchlist: 5 coins max
  - Alerts: 3 active max
  - Morning brief: delayed 2 hours
  - AI analysis: 5 requests/day

Pro ($5-10/month):
  - Watchlist: unlimited
  - Alerts: unlimited, realtime
  - Morning brief: realtime 7AM
  - AI analysis: 50 requests/day
  - Trade journal + weekly AI report
  - Screener access

Pro+ ($15-20/month):
  - Everything in Pro
  - Backtesting engine
  - AI chat (unlimited)
  - Export reports PDF
  - API access
```

---

## 12. ENVIRONMENT VARIABLES

```env
# App
APP_ENV=development
SECRET_KEY=your-secret-key-here
LOG_LEVEL=INFO

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/cryptoai
REDIS_URL=redis://localhost:6379/0

# Supabase (managed DB option)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=your-anon-key

# Telegram
TELEGRAM_BOT_TOKEN=your-bot-token

# AI Providers
AI_PROVIDER=claude          # claude | openai | gemini
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx       # fallback
GOOGLE_API_KEY=xxx          # optional

# Binance
BINANCE_API_KEY=xxx         # optional for Phase 1 (market data is public)
BINANCE_SECRET_KEY=xxx
BINANCE_TESTNET=true        # use testnet for development

# External APIs
CRYPTOPANIC_API_KEY=xxx     # free tier available
# Fear & Greed: no key needed (Alternative.me)

# Payment (Phase 2)
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

---

## 13. IMPORTANT IMPLEMENTATION RULES

1. **Never claim to predict prices** — all AI output must include disclaimer
2. **Never say "buy" or "sell"** — use "signal", "indicator", "technical level"
3. **Cache aggressively** — same price data is used by all users, cache in Redis TTL 5min
4. **Circuit breaker on all external calls** — Binance down? Use cached data. Claude down? Use fallback provider.
5. **Async everywhere** — FastAPI + SQLAlchemy async + httpx for all I/O
6. **Rate limiting** — max 3 alerts per coin per hour per user, max 5 AI requests/minute
7. **Testnet first** — all Binance order features must work on testnet before touching real API
8. **One backend, multiple frontends** — Telegram bot and Web Dashboard call same service layer
9. **Keep interfaces thin** — Telegram handlers only parse commands and call services. No business logic in handlers.
10. **Secrets never in code** — all keys via environment variables, never hardcoded

---

## 14. DOCKER COMPOSE (local development)

```yaml
version: '3.8'
services:
  app:
    build: .
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      - postgres
      - redis
    volumes:
      - ./src:/app/src

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: cryptoai
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  postgres_data:
```

---

## 15. BUILD ORDER (recommended sequence)

### Week 1: Foundation
- [ ] Project setup: Python 3.11, FastAPI, Docker Compose, PostgreSQL, Redis
- [ ] Database models + Alembic migrations
- [ ] Binance API connection — fetch price for 1 coin
- [ ] Telegram Bot setup — /start and /price commands working
- [ ] Redis cache-aside helper

### Week 2: Core features
- [ ] Watchlist CRUD (/watch, /unwatch, /watchlist)
- [ ] pandas-ta integration — compute RSI, MACD, Bollinger for any coin
- [ ] Alert system — /setalert, /alerts, /clear
- [ ] Cron job: check alerts every 5 minutes, push Telegram on trigger

### Week 3: AI integration
- [ ] AIProvider abstract class + ClaudeProvider implementation
- [ ] Context Builder — assemble market data into prompt
- [ ] /analyze command — TA data → Claude Sonnet → natural language output
- [ ] News fetching — CryptoPanic API → finBERT sentiment → store DB
- [ ] /signal command — confluence scoring engine (rule-based, no AI)
- [ ] /signal AI layer — pass scored results to Claude Sonnet for interpretation
- [ ] signals table migration + logging all generated signals

### Week 4: Risk tools + Morning brief
- [ ] /tpsl command — ATR + swing levels → TP/SL calculation
- [ ] /risk command — position sizing formula
- [ ] /fee command — fee calculation
- [ ] Morning brief job — assemble + Claude Haiku → send 7AM

### Week 5: Trade journal
- [ ] /log, /history, /report commands
- [ ] P&L calculation logic
- [ ] Weekly report — Claude Sonnet trade pattern analysis

### Week 6: Polish + real usage
- [ ] /settings, /capital, /timezone commands
- [ ] Error handling everywhere — Circuit Breaker on all external calls
- [ ] Rate limiting — anti-spam for alerts
- [ ] Use the bot daily — note what's useful and what's missing
- [ ] Write tests for core services

---

## 16. ESTIMATED MONTHLY COST (Phase 1 personal use)

| Item | Cost |
|---|---|
| Claude API (personal use ~100 AI calls/day) | $5–15 |
| Railway (FastAPI + Redis) | $0 free tier |
| Supabase (PostgreSQL) | $0 free tier |
| Vercel (frontend, Phase 2) | $0 free tier |
| Binance API | $0 free |
| CryptoPanic API | $0 free tier |
| Fear & Greed API | $0 free |
| Domain (.com/year ÷ 12) | ~$1 |
| **Total Phase 1** | **$6–16/month** |

---

*End of master prompt. Build Phase 1 (Telegram Bot) first. Validate with real daily usage for 4-6 weeks before investing in Phase 2 (Web Dashboard).*
