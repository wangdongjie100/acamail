<p align="center">
  <h1 align="center">📧 AcaMail — AI Email Assistant for Academics</h1>
  <p align="center">
    <em>An intelligent Telegram bot that monitors your Gmail, classifies emails, and drafts professional replies — built for professors, researchers, and academics who receive 100+ emails daily.</em>
  </p>
  <p align="center">
    <a href="#-features">Features</a> •
    <a href="#-quick-start">Quick Start</a> •
    <a href="#-architecture">Architecture</a> •
    <a href="#-comparison">vs. OpenClaw</a> •
    <a href="#-license">License</a>
  </p>
</p>

---

## ✨ Features

### 🧠 Smart Email Classification
- **AI-powered triage** — Automatically categorizes emails as actionable vs. informational
- **Batch classification** — Groups up to 5 emails per API call, saving ~60-70% token costs
- **Pre-filtering** — Pattern-based rules skip AI entirely for newsletters, notifications, and system emails
- **Priority scoring** — High / Medium / Low priority with category labels

### ✍️ Professional Reply Generation
- **3-tone drafts** — Generates positive, negative, and neutral replies in one click
- **Academic tone** — Formal language with proper greetings and sign-offs for faculty
- **Bilingual** — Chinese summaries + English replies (perfect for international academics)
- **Custom instructions** — Tell the AI (in Chinese) what to change, and it rewrites in English

### 📱 Telegram-Powered Workflow
- **Interactive inbox** — Browse, preview, and reply to emails from your phone
- **Reply / Reply All** — Choose to reply to sender only or CC all recipients
- **Persistent queue** — Unprocessed emails carry over between sessions
- **Scheduled push** — Automatic email summaries at configurable times

### ⚡ Cost & Efficiency
- **Near-free** — Uses Google Gemini Flash Lite (free tier sufficient for most users)
- **Token-optimized** — HTML stripping, body truncation, batch classification, pre-filtering
- **Forwarded email detection** — Auto-detects forwarded emails and replies to the original sender
- **Local storage** — All data in SQLite, no cloud dependency

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- A Gmail account with [API access enabled](https://console.cloud.google.com/)
- A [Telegram Bot](https://core.telegram.org/bots#creating-a-new-bot) token
- A [Google Gemini API key](https://aistudio.google.com/apikey)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/acamail.git
cd acamail

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your credentials
```

### Configuration (.env)

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.1-flash-lite-preview
USER_EMAIL=your_email@gmail.com
TIMEZONE=America/Chicago
PUSH_HOURS=[9,18]
CREDENTIALS_PATH=credentials.json
TOKEN_PATH=token.json
DB_PATH=gmail_bot.db
```

### Gmail OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable Gmail API
3. Create OAuth 2.0 credentials (Desktop App)
4. Download `credentials.json` to the project root
5. On first run, a browser window opens for authorization

### Run

```bash
python main.py
```

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/check` | 📬 Check for new emails and classify them |
| `/status` | 📊 View system status |
| `/help` | 📖 Usage guide |
| `/start` | 👋 Initialize the bot |

---

## 🏗 Architecture

```
acamail/
├── main.py                 # Entry point
├── config.py               # Configuration management
├── ai/
│   ├── classifier.py       # Email classification (batch + single)
│   └── reply_generator.py  # Reply draft generation
├── bot/
│   ├── handlers.py         # Telegram command & callback handlers
│   ├── keyboards.py        # Inline keyboard definitions
│   └── formatter.py        # Message formatting
├── gmail/
│   ├── auth.py             # OAuth2 authentication
│   ├── client.py           # Gmail API client
│   └── models.py           # Data models (Email, ClassificationResult, etc.)
├── scheduler/
│   └── jobs.py             # Scheduled email push
└── storage/
    └── database.py         # SQLite persistence
```

### Data Flow

```
Gmail API → Fetch emails → Pre-filter (pattern matching)
                              ↓ (skip AI)         ↓ (needs AI)
                        Direct classify    → Batch classify (5/call)
                              ↓                    ↓
                        Telegram push summary ← Merge results
                              ↓
                    User clicks email → Detail view
                              ↓
                    Generate replies (3 tones) → User picks one
                              ↓
                    Reply / Reply All → Gmail API sends
```

---

## 🆚 Comparison

| Feature | AcaMail | OpenClaw |
|---------|---------|----------|
| **Focus** | 📧 Email specialist | 🤖 General AI agent |
| **AI Model** | Google Gemini (free/low-cost) | OpenAI GPT ($20-100+/mo) |
| **Setup Time** | 5 minutes | 30+ minutes |
| **Codebase** | ~15 files, minimal deps | Large, complex |
| **Academic Tone** | Built-in, professor-grade | Manual prompting |
| **Bilingual** | ✅ Chinese summary + English reply | ❌ English-only |
| **Multi-Account** | ✅ Email forwarding support | ❌ Single account |
| **Batch Processing** | ✅ 5 emails/API call | ❌ 1 email/call |
| **Privacy** | 100% local SQLite | Requires local deploy |

**AcaMail is not a competitor to OpenClaw** — it's a **vertical solution** for the #1 pain point of academics: **email overload**. While OpenClaw is a general-purpose AI agent, AcaMail does one thing exceptionally well.

---

## 🔧 Token Optimization

AcaMail is designed to minimize AI costs:

| Optimization | Savings |
|-------------|---------|
| Pre-filtering (noreply, GitHub, etc.) | ~30-50% calls skipped |
| Batch classification (5/call) | ~60-70% fewer API calls |
| HTML → plaintext stripping | ~40% fewer input tokens |
| Body truncation (1200 chars classify, 800 batch) | Bounded input |
| Result caching (SQLite + in-memory) | No repeated classification |
| Gemini Flash Lite model | ~10x cheaper than GPT-4 |

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🙏 Acknowledgments

- [Google Gemini API](https://ai.google.dev/) for AI capabilities
- [python-telegram-bot](https://python-telegram-bot.org/) for Telegram integration
- Built with ❤️ for the academic community
