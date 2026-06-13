# Crypto Trading Assistant — Walkthrough kỹ thuật đầy đủ

> **Phiên bản:** v4.0 (Milestone 3 & 4 hoàn chỉnh)  
> **Cập nhật lần cuối:** 06/2026  
> **Trạng thái:** Production-ready

Hệ thống đã được nâng cấp toàn diện từ một trading bot bán tự động cơ bản thành **Trợ lý giao dịch thông minh (Decision Support Engine)** tích hợp AI, nhận diện cấu trúc thị trường (Market Regime), quản lý vốn tự động (Position Sizing) và ghi nhận kết quả (Backtesting DB).

---

## Mục lục

1. [Kiến trúc tổng quan](#1-kiến-trúc-tổng-quan)
2. [Hybrid AI Factory](#2-hybrid-ai-factory-milestone-3)
3. [RSI Danger Guard & 2-Tier Scoring](#3-rsi-danger-guard--2-tier-scoring)
4. [ADX Market Regime Filter](#4-adx-market-regime-filter)
5. [Position Sizing tự động](#5-position-sizing-tự-động)
6. [Backtesting DB](#6-backtesting-db)
7. [Danh sách lệnh Telegram](#7-danh-sách-lệnh-telegram)
8. [Hướng dẫn cài đặt & chạy thử](#8-hướng-dẫn-cài-đặt--chạy-thử)
9. [Giới hạn đã biết & roadmap](#9-giới-hạn-đã-biết--roadmap)

---

## 1. Kiến trúc tổng quan

```
Binance API (live data)
        │
        ▼
  TAService (Python)
  ├── 200 nến 4H
  ├── RSI · MACD · BB · MA · ATR · ADX · Volume
  ├── RSI Danger Guard
  ├── ADX Market Regime Filter
  ├── 3-Layer MTF Trend Filter (1W → 1D → 4H)
  └── 2-Tier Confluence Scoring (thang 10 điểm)
        │
        ▼
  Signal Engine
  ├── Entry Zone (Fib 0.618 limit / Market)
  ├── SL theo tier (1.0x ATR / 1.5x ATR)
  ├── TP1 · TP2 · TP3
  └── Position Sizing (Risk-based)
        │
        ▼
  AI Risk Manager (Claude / DeepSeek / Fallback)
        │
        ▼
  Telegram Output + SQLite DB Log
```

**Quy tắc thiết kế cốt lõi:**
- Dữ liệu giá: Binance API (chính xác 100%, không dự đoán)
- Tính toán: Python thuần — không cảm xúc, không ảo giác
- Nhận định ngôn ngữ: AI biên soạn từ dữ liệu kỹ thuật có sẵn
- Lỗi DB không bao giờ làm crash signal handler

---

## 2. Hybrid AI Factory (Milestone 3)

Hệ thống phân luồng tự động giữa 2 AI provider:

| Provider | Vai trò | Khi nào dùng |
|---|---|---|
| **Claude** (Primary) | Phân tích kỹ thuật nặng | Signal, setup phức tạp, đọc cấu trúc thị trường |
| **DeepSeek** (Fast) | Báo cáo nhanh, tóm tắt | Tin tức, thông báo cảnh báo, summary |
| **OpenAI / Gemini** | Fallback tự động | Khi Primary AI gặp lỗi / timeout |

**Cơ chế fallback:** Nếu AI chính trả về lỗi hoặc timeout, hệ thống tự động chuyển sang provider tiếp theo trong chuỗi mà không cần restart bot. Người dùng nhận được thông báo nhẹ thay vì lỗi thô.

---

## 3. RSI Danger Guard & 2-Tier Scoring

### 3.1 RSI Danger Guard

Chặn điểm RSI ở vùng cực đoan để tránh "bắt dao rơi" hoặc "cản tàu trực tiếp":

| Lệnh | Ngưỡng cực đoan | Hành động |
|---|---|---|
| LONG | RSI < 15 | Cộng 0 điểm + cảnh báo `⚠️ RSI extremely low — danger zone` |
| SHORT | RSI > 85 | Cộng 0 điểm + cảnh báo `⚠️ RSI extremely high — danger zone` |

> **Lý do chọn 15 / 85 (không phải 20 / 80):** Ngưỡng 20/80 sẽ loại bỏ nhiều setup oversold hợp lệ. Ngưỡng 15/85 chỉ block các trường hợp panic sell / short squeeze bất thường thực sự — những lúc momentum có thể tiếp tục mà không đảo chiều ngay.

### 3.2 Confluence Scoring — thang 10 điểm

**Bộ chỉ báo gốc (7 điểm):**

| Điều kiện | Điểm |
|---|---|
| Giá trên MA50 (LONG) / dưới MA50 (SHORT) | +1 |
| Giá trên MA200 (LONG) / dưới MA200 (SHORT) | +1 |
| RSI ở vùng phù hợp (chuẩn hóa, không cực đoan) | +1 |
| MACD cắt lên Signal (LONG) / cắt xuống (SHORT) | +1 |
| MACD Histogram dương (LONG) / âm (SHORT) | +1 |
| Giá chạm dải BB phù hợp | +1 |
| Giá tại vùng support / resistance cứng | +1 |

**Điểm bổ sung (3 điểm — phụ thuộc điều kiện):**

| Điều kiện | Điểm |
|---|---|
| Nến đóng cửa xác nhận chiều (bullish/bearish candle) | +2 |
| Volume > 1.5x MA20 — cùng chiều tín hiệu | +2 |
| Volume > 1.2x MA20 — cùng chiều tín hiệu | +1 |

> **Quan trọng — Volume direction check:** Volume spike chỉ tính điểm khi nến có volume cao là nến cùng chiều tín hiệu. Volume tăng trong nến ngược chiều không được tính.

**Ngưỡng kích hoạt:**

| Điểm | Kết quả |
|---|---|
| < 6 / 10 | Không bắn signal — thị trường chưa đủ điều kiện |
| 6–7 / 10 | Signal Tier B — thận trọng |
| 8–10 / 10 | Signal Tier A — chất lượng cao |

### 3.3 2-Tier Signal Management

| | Tier B (6–7 điểm) | Tier A (8–10 điểm) |
|---|---|---|
| Nhãn | ⭐⭐ KHÁ | ⭐⭐⭐ MẠNH |
| Stop Loss | 1.0x ATR | 1.5x ATR |
| Mục tiêu | TP1 only — thoát 100% | TP1 + TP2 + TP3 |
| Position size | Half (0.5–1% vốn) | Full (1–2% vốn) |
| Tự động expire | 5 ngày | 7 ngày |

---

## 4. ADX Market Regime Filter

ADX(14) xác định trạng thái thị trường để tự động điều chỉnh bộ chỉ báo ưu tiên:

| ADX | Regime | Chiến lược | Bonus điểm |
|---|---|---|---|
| > 25 | 📈 TRENDING | Trend-following | +1 nếu MACD crossover; +1 nếu MA20 > MA50 |
| 20–25 | ⚡ TRANSITIONAL | Trung lập | Không cộng thêm |
| < 20 | ↔️ RANGING | Mean-reversion | +1 nếu BB touch extreme; +1 nếu RSI extreme |

**Điều kiện MA trong TRENDING mode** (đã nới lỏng so với v1):
- Trước đây yêu cầu `MA20 > MA50 > MA200` (cả 3 cùng lúc).
- Hiện tại chỉ cần `MA20 > MA50`: **+1 điểm** (short/medium term momentum).
- MA200 đã bị loại bỏ khỏi điều kiện vì trên khung 4H, MA200 tương đương ~800 ngày — quá chậm, sẽ bỏ lỡ các setup đầu bull run khi MA200 chưa bắt kịp.

> **Giới hạn đã biết:** ADX(14) có độ trễ tự nhiên ~5–7 nến. Signal trend-following có thể trễ vài nến ở đầu xu hướng mới, và bonus TRENDING có thể vẫn được tính khi trend sắp hết hơi. Đây là trade-off cố hữu của ADX — không có cách fix hoàn toàn.

---

## 4b. 3-Layer MTF Trend Filter (Weekly → Daily → 4H)

Hệ thống hiện tại dùng **3 lớp MTF** để xác định xu hướng trước khi bắn signal:

```
L1: 4H indicators  →  Score cơ sở (chỉ báo kỹ thuật)
L2: 1D trend       →  Bộ lọc trung hạn (~50-200 ngày)
L3: 1W trend       →  Bộ lọc macro (~50-200 tuần) — mạnh nhất
```

**Logic bộ lọc có điều kiện (Conditional Block):**

| Weekly (1W) | Daily (1D) | LONG | SHORT |
|---|---|---|---|
| UPTREND | UPTREND | ✅ Bình thường (+1 bonus) | ❌ Blocked (L2) |
| UPTREND | DOWNTREND | ✅ Bình thường | ⚠️ Warning (counter-weekly) |
| UPTREND | SIDEWAYS | ✅ Bình thường | ✅ Bình thường |
| DOWNTREND | UPTREND | ⚠️ Warning + giữ bonus | ✅ Bình thường |
| DOWNTREND | DOWNTREND | ❌ Blocked (L2) | ✅ Bình thường (+1 bonus) |
| SIDEWAYS | bất kỳ | ✅ Không ảnh hưởng | ✅ Không ảnh hưởng |

**Tác động lên điểm số:**
- **Full alignment (weekly = daily):** Daily trend bonus được cộng đầy đủ `+1 điểm`.
- **Counter-weekly:** Daily trend bonus bị giữ lại (`0 điểm`) + hiển thị cảnh báo rõ trong danh sách tín hiệu.
- **Sideways weekly:** Không ảnh hưởng gì — đây là vùng trung lập.

**Ví dụ thực tế:**
```
Bear Market 2022: Weekly DOWNTREND
  → Daily UPTREND (sóng hồi tháng 3/2022) → LONG được bắn nhưng có cảnh báo
  → Daily DOWNTREND (giai đoạn chính) → LONG bị blocked hoàn toàn
```

> **Lưu ý kỹ thuật:** Weekly MA50/MA200 trên Binance `1w` kline tương đương ~1-4 năm dữ liệu. Bot yêu cầu tối thiểu 50 nến tuần (~1 năm); nếu chưa đủ, mặc định `sideways` (không ảnh hưởng signal).

---

## 5. Position Sizing tự động

### 5.1 Công thức

```
Position Value (USDT) = (Equity × Risk%) / SL%
Số lượng coin        = Position Value / Entry Price
```

### 5.2 Tier-aware Risk

Tier B tự động giảm 50% mức rủi ro so với cài đặt:

```
Ví dụ: Equity = $10,000 | Risk = 1% | SL = 2%

Tier A: Position = (10,000 × 1%) / 2% = $5,000
Tier B: Position = (10,000 × 0.5%) / 2% = $2,500
```

### 5.3 Safety Cap & Cảnh báo đòn bẩy

| Điều kiện | Hành động |
|---|---|
| Position > 80% Equity | Chặn — cap tại 80% |
| Đòn bẩy hiệu quả > 10x | Cảnh báo `🚨` |
| Đòn bẩy hiệu quả > 5x | Cảnh báo `⚠️` |

---

## 6. Backtesting DB

### 6.1 Kiến trúc

```
src/
├── database/
│   └── signal_repository.py   ← SQLite CRUD (tầng dữ liệu)
├── core/
│   └── signal_tracker.py      ← Business logic
└── interfaces/telegram/
    ├── handlers.py             ← 3 handlers mới + auto-log
    └── bot.py                  ← Đăng ký commands + job 4H
```

File DB: `data/signals.db` (tự tạo khi bot start, không commit lên Git)

### 6.2 Schema chính

```sql
CREATE TABLE signal_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT,     -- 'BTCUSDT'
    side          TEXT,     -- 'long' | 'short'
    score         INTEGER,  -- 0–10
    tier          TEXT,     -- 'A' | 'B'
    market_regime TEXT,     -- 'trending' | 'ranging' | 'transitional'
    adx           REAL,
    entry_price   REAL,
    limit_entry   REAL,     -- Fib 0.618
    sl            REAL,
    tp1           REAL,
    tp2           REAL,
    tp3           REAL,
    sl_pct        REAL,
    rr1           REAL,
    rr2           REAL,
    fired_at      TEXT,     -- ISO-8601 UTC
    status        TEXT,     -- 'open' | 'tp1_hit' | 'tp2_hit' | 'sl_hit' | 'expired'
    outcome_price REAL,
    outcome_at    TEXT,
    pnl_pct       REAL,
    notes         TEXT
);

CREATE INDEX IF NOT EXISTS idx_status ON signal_logs(status);
CREATE INDEX IF NOT EXISTS idx_symbol ON signal_logs(symbol);
```

### 6.3 Auto-checker 4H

Mỗi 4H, bot tự động:
1. Lấy tất cả signal `status='open'`
2. Batch fetch giá theo symbol (tối ưu API call)
3. So sánh theo thứ tự ưu tiên: **SL trước → TP2 → TP1** (cẩn thận hơn)
4. Cập nhật DB nếu có kết quả
5. Expire signal quá hạn (Tier A: 7 ngày, Tier B: 5 ngày)

> **Lưu ý về `outcome_at`:** Thời điểm ghi là lúc bot chạy job, không phải lúc giá thực tế chạm SL/TP. Độ lệch tối đa ~4H — chấp nhận được cho thống kê tổng quát.

### 6.4 Thống kê `/stats`

```
📊 Thống kê tín hiệu — toàn hệ thống
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 Tổng signal: 15
✅ Thắng: 9  |  ❌ Thua: 4  |  ⌛ Hết hạn: 2
🟢 Win rate: 69.2%

💰 Avg lãi/lệnh thắng: +3.45%
💸 Avg lỗ/lệnh thua:  -1.87%

📋 Phân tích theo Tier:
⭐⭐⭐ Tier A: 7/9 thắng (77.8%)
⭐⭐   Tier B: 2/6 thắng (33.3%)
```

---

## 7. Danh sách lệnh Telegram

### Phân tích & Tín hiệu

| Lệnh | Mô tả |
|---|---|
| `/signal <coin>` | Tín hiệu giao dịch đầy đủ: Entry Zone, SL, TP, Position Size, AI nhận định |
| `/analyze <coin>` | Phân tích kỹ thuật chi tiết không kèm tín hiệu vào lệnh |

### Quản lý vốn

| Lệnh | Mô tả |
|---|---|
| `/setequity <USDT>` | Thiết lập tổng vốn giao dịch |
| `/setrisk <phần trăm>` | Thiết lập % rủi ro tối đa/lệnh (khuyến nghị: 0.5–2%) |
| `/possize <entry> <sl_price> [tier]` | Tính nhanh Position Size thủ công |

### Thống kê & Lịch sử

| Lệnh | Mô tả |
|---|---|
| `/stats [coin]` | Win rate, PnL, phân tích Tier A vs B |
| `/history` | 8 signal gần nhất với kết quả thực tế |
| `/checkoutcomes` | Trigger thủ công kiểm tra signal đang mở |

---

## 8. Hướng dẫn cài đặt & chạy thử

**Bước 1 — Cấu hình `.env`:**

```env
TELEGRAM_BOT_TOKEN=...
ANTHROPIC_API_KEY=...
DEEPSEEK_API_KEY=...
```

**Bước 2 — Chạy bot:**

```bash
uv run python main.py
```

**Bước 3 — Thiết lập vốn ban đầu trên Telegram:**

```
/setequity 10000    ← Vốn giả lập $10,000
/setrisk 1          ← Rủi ro 1% / lệnh Tier A (Tier B tự động = 0.5%)
```

**Bước 4 — Kiểm tra tín hiệu:**

```
/signal BTC
/signal ETH
```

---

## 9. Giới hạn đã biết & Roadmap

### Giới hạn hiện tại

| Hạng mục | Mô tả |
|---|---|
| ADX lagging | Độ trễ ~5–7 nến — entry đẹp nhất đầu trend có thể bị phân loại sai regime |
| `outcome_at` | Ghi theo lúc job chạy, không phải thời điểm giá chạm SL/TP thực tế (±4H) |
| Partial close | Schema chưa có field `partial_close` — lệnh hit TP1 rồi về SL vẫn tính là Win |
| Weekly MTF | Chỉ lọc theo 1D, chưa kiểm tra Weekly để tránh counter-trend trong bear market dài hạn |

### Roadmap đề xuất (ưu tiên theo tác động)

1. **Thu thập dữ liệu thực** — cần 30–50 signal có kết quả trước khi tinh chỉnh thêm tham số
2. **Partial close tracking** — thêm field `partial_close_pct` vào schema DB để phân biệt TP1 partial vs. full exit

> **Lưu ý:** Volume direction check đã được triển khai đầy đủ trong `ta_service.py` — volume spike chỉ tính điểm khi nến cùng chiều tín hiệu. Roadmap không cần bao gồm điểm này.
> **Lưu ý:** Weekly MTF Filter đã được triển khai hoàn chỉnh (Section 4b) — đã xóa khỏi Roadmap.
