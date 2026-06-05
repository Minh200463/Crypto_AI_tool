# CryptoAI Trading Assistant

A personal crypto trading assistant system with Telegram bot, AI-powered insights, technical analysis, and risk management tools.

## Setup Instructions

### Prerequisites
- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (Package manager)

### Installation

1. Install dependencies using uv:
   ```bash
   uv sync
   ```

2. Create `.env` file from template:
   ```bash
   cp .env.example .env
   ```
   Fill in your Telegram bot token and AI provider API keys.

3. Run database migrations:
   ```bash
   uv run alembic upgrade head
   ```

4. Start the bot:
   ```bash
   uv run python main.py
   ```

## Development

Run tests:
```bash
uv run pytest tests/
```
