Build a production-grade Chat-Over-Data Teams bot using Semantic Kernel 
(Python) and Azure OpenAI. The agent reads tabular data and lets users 
interact with it directly inside Microsoft Teams — asking natural language 
questions and getting back exact counts, full record lists, summaries, 
and insights with no row caps or hidden truncation.

---

## Context

Proof-of-concept experiment. Local testing uses mock Excel data. 
Production target is an on-premises SQL Server accessed via pyodbc. 
The swap between Excel and SQL Server must require only Microsoft Teams Bot

- Use the **Bot Framework SDK (Python)** + **Semantic Kernel** for the agent
- Bot runs locally on localhost:3978
- Local testing via **Bot Framework Emulator** (no Teams required for dev loop)
- For Teams testing a single 
environment variable change — no code modifications.

---

## Target Interface:: provide ngrok setup instructions + Azure Bot Service 
  registration steps (free tier)
- Each user message triggers the SK agent; response returns to Teams/Emulator

---

## Azure Resources to Provision (provide az CLI commands for each)
- Azure OpenAI resource
- GPT-4o deployment (chat completion, function calling enabled)
- Azure Bot Service registration (for Teams channel, free tier)
- All secrets managed via .env — no hardcoded values

---

## Data Layer
- Load Excel file(s) from a configurable folder path (local test)
- Load each sheet as a named "table"
- Support: full SELECT, exact COUNT(* sets — no sampling, no top-N limits
- Paging logic), filter by column/value, 
  distinct values, multi-table queries
- Return full result: if results > 50 rows, return first page + prompt 
  "Reply 'more' to see next 50"
- Clean data module with a DATASOURCE flag:
  - DATASOURCE=excel → reads from EXCEL_FOLDER_PATH
  - DATASOURCE=sql   → connects via pyodbc using SQL_* variables
- Document the swap clearly in README

---

## Semantic Kernel Agent
- Use Semantic Kernel Python SDK (latest stable, not preview)
- Register data access functions as SK plugins with clear descriptions 
  so the LLM selects them correctly
- Azure OpenAI backend (function calling enabled)
- Agent must:
  - Return exact record counts
  - List all records (paged)
  - Filter and group by column
  - Summarize and provide insights
  - State what query it ran and how many rows it found

---

## Production-Grade Standards
- Full type hints and docstrings
- Structured error handling (data errors, API errors, empty results, 
  bot errors)
- Python logging (level configurable via LOG_LEVEL in .env)
- .env.example with every variable documented and grouped by owner
- requirements.txt with pinned versions
- README: setup, Structure

chat_agent/
├── .env.example
├── requirements.txt
├── README.md
├── main.py                  # Bot entry point (a local test with Emulator, Teams deployment, SQL swap

---

## Projectiohttp server)
├── bot/
│   ├── __init__.py
│   └── bot_handler.py       # Bot Framework activity handler
├── agent/
│   ├── __init__.py
│   ├── kernel.py            # Semantic Kernel + Azure OpenAI setup
│   └── plugins/
│       ├── __init__.py
│       └── data_plugin.py   # SK plugin wrapping data access
├── data/
│   ├── __init__.py
│   └── loader.py            # Excel loader (swap point for pyodbc)
└── config/
    ├── __init__.py
    └── settings.py          # Pydantic settings loaded from .env

---

## .env.example — split by owner

# ── JORGE (local test) ──────────────────────────────
DATASOURCE=excel
EXCEL_FOLDER_PATH=./data/mock

# ── MACIEJ (production) ─────────────────────────────
# DATASOURCE=sql
# SQL_SERVER=your-server-hostname-or-ip
# SQL_DATABASE=your-database-name
# SQL_TABLE=your-table-or-view-name
# SQL_TRUSTED_CONNECTION=yes          # Windows auth
# SQL_USERNAME=                       # SQL auth only
# SQL_PASSWORD=                       # SQL auth only

# ── AZURE OPENAI (both) ─────────────────────────────
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4o  # swap model here

# ── BOT FRAMEWORK ───────────────────────────────────
MICROSOFT_APP_ID=                    # empty for local Emulator test
MICROSOFT_APP_PASSWORD=              # empty for local Emulator test
BOT_PORT=3978

# ── GENERAL ─────────────────────────────────────────
LOG_LEVEL=INFO

---

## Notes
- Python 3.11+
- semantic-kernel latest stable (not preview)
- openai SDK v1.x
- botframework-connector + aiohttp for the bot server
- No LangChain
- Local Emulator test must work with MICROSOFT_APP_ID and 
  MICROSOFT_APP_PASSWORD left blank