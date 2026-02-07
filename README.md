# ⚡ SalesShortcut

**AI-Powered Sales Development Representative System**

A multi-agent system that automates the entire SDR workflow — from discovering local businesses without websites, to researching them, calling with an AI voice, sending tailored proposals, and auto-scheduling meetings when they reply. Built with [Dedalus ADK](https://docs.dedaluslabs.ai) at Columbia ADI DevFest 2026.

---

## 🎯 What It Does

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Lead Finder │────▶│  SDR Agent   │────▶│ Gmail Listener│────▶│ Lead Manager │
│   (8081)     │     │   (8084)     │     │   (8083)      │     │   (8082)     │
└──────┬───────┘     └──────┬───────┘     └───────┬───────┘     └──────┬───────┘
       │                    │                     │                    │
       │         ┌──────────┴──────────┐          │          ┌────────┴────────┐
       │         │ • Research business │          │          │ • Analyze email  │
       │         │ • Draft proposal    │          │          │ • Detect meeting │
       │         │ • Fact-check draft  │          │          │   request        │
       │         │ • AI phone call     │          │          │ • Check calendar │
       │         │ • Classify outcome  │          │          │ • Schedule meet  │
       │         │ • Send email        │          │          │ • Google Meet    │
       │         └─────────────────────┘          │          └─────────────────┘
       │                                          │
       ▼                    ▼                     ▼                    ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                    UI Client Dashboard (8000)                          │
  │         Real-time WebSocket updates • Lead table • Activity log        │
  └─────────────────────────────────────────────────────────────────────────┘
```

| Step | What Happens |
|------|-------------|
| **1. Discover** | Lead Finder searches Google Maps for local businesses without websites |
| **2. Research** | SDR Agent deep-researches each business via web search |
| **3. Propose** | Generates a tailored website proposal (draft + fact-check) |
| **4. Call** | Places an AI phone call via ElevenLabs conversational AI |
| **5. Classify** | LLM classifies call outcome: interested / agreed to email / not interested |
| **6. Email** | Sends personalized HTML proposal email via Gmail |
| **7. Listen** | Gmail Pub/Sub Listener watches for replies in real-time |
| **8. Schedule** | Lead Manager detects meeting requests and auto-books Google Calendar + Meet |

---

## 🏗️ Architecture

### Services

| Service | Port | Description |
|---------|------|-------------|
| **UI Client** | `8000` | FastAPI dashboard with WebSocket real-time updates |
| **Lead Finder** | `8081` | Google Maps search → BigQuery storage |
| **Lead Manager** | `8082` | Email analysis → calendar scheduling |
| **Gmail Listener** | `8083` | Pub/Sub subscriber → forwards to Lead Manager |
| **SDR Agent** | `8084` | Research → proposal → call → email pipeline |

### Tech Stack

- **AI Orchestration**: [Dedalus ADK](https://docs.dedaluslabs.ai) — `DedalusRunner` with agent-as-tool pattern
- **LLM Providers**: OpenAI GPT-4.1, Anthropic Claude Sonnet 4 (via Dedalus unified API)
- **MCP Servers**: Brave Search MCP for web research
- **Voice AI**: ElevenLabs Conversational AI for phone calls
- **Backend**: FastAPI + WebSockets
- **Data**: Google BigQuery
- **APIs**: Google Maps Places, Gmail, Google Calendar
- **Frontend**: Vanilla HTML/CSS/JS with dark theme dashboard

### Design Patterns

| Pattern | Usage |
|---------|-------|
| **Agent-as-Tool** | Each specialist (research, proposal, classifier) is a nested `runner.run()` call wrapped as a tool function |
| **Coordinator + Specialists** | Cheap model coordinates, expensive models handle specific tasks |
| **Structured Outputs** | Pydantic `response_format` for classification and email analysis |
| **Callback Broadcasting** | Services POST to `/agent_callback` → WebSocket broadcast to all dashboard clients |
| **Shared Models** | `common/models.py` defines `Lead`, `Meeting`, `SDRResult`, etc. used everywhere |

---

## 📁 Project Structure

```
salesshortcut/
├── .env                          # API keys (fill in yours)
├── pyproject.toml                # Python packaging & dependencies
├── requirements.txt              # pip dependencies
│
├── common/                       # Shared across all services
│   ├── config.py                 # Ports, URLs, BigQuery, model names
│   └── models.py                 # Pydantic models: Lead, Meeting, SDRResult, etc.
│
├── lead_finder/                  # Service 1: Discover leads
│   ├── __main__.py               # Entrypoint
│   ├── agent.py                  # FastAPI + DedalusRunner orchestration
│   └── tools/
│       ├── maps_search.py        # Google Maps Places API wrapper
│       └── bigquery_utils.py     # BigQuery lead persistence
│
├── sdr/                          # Service 2: SDR outreach pipeline
│   ├── __main__.py               # Entrypoint
│   ├── agent.py                  # Full pipeline: research → call → email
│   └── tools/
│       ├── phone_call.py         # ElevenLabs AI phone calls
│       ├── email_tool.py         # Gmail send via service account
│       └── bigquery_utils.py     # SDR session persistence
│
├── lead_manager/                 # Service 3: Email processing + meetings
│   ├── __main__.py               # Entrypoint
│   ├── agent.py                  # Email analysis + calendar booking
│   └── tools/
│       ├── check_email.py        # Gmail API: fetch/mark unread emails
│       ├── calendar_utils.py     # Google Calendar: availability + create meeting
│       └── bigquery_utils.py     # Lead lookup + meeting persistence
│
├── gmail_pubsub_listener/        # Service 4: Real-time email notifications
│   └── gmail_listener_service.py # Pub/Sub subscriber + polling fallback
│
└── ui_client/                    # Service 5: Dashboard
    ├── __main__.py               # Entrypoint
    ├── main.py                   # FastAPI: WebSocket, callbacks, workflow triggers
    ├── templates/
    │   └── dashboard.html        # Interactive dashboard
    └── static/
        ├── css/style.css         # Dark theme styles
        └── js/app.js             # WebSocket client + UI logic
```

---

## 🚀 Quick Start

### 1. Clone & Install

```bash
git clone <repo-url>
cd adi-devfest-hackathon
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment

Fill in your API keys in `.env`:

```env
# Required for core functionality
DEDALUS_API_KEY=your-dedalus-key           # https://dedaluslabs.ai/dashboard/api-keys
GOOGLE_MAPS_API_KEY=your-maps-key          # Google Cloud Console → APIs → Places API

# Required for phone calls
ELEVENLABS_API_KEY=your-elevenlabs-key     # https://elevenlabs.io
ELEVENLABS_AGENT_ID=your-agent-id

# Required for email sending/receiving
SALES_EMAIL=sales@yourdomain.com
SERVICE_ACCOUNT_FILE=path/to/service-account.json

# Required for data persistence
GOOGLE_CLOUD_PROJECT=your-gcp-project

# Optional: customize LLM models
DEFAULT_MODEL=openai/gpt-4.1
DRAFT_MODEL=anthropic/claude-sonnet-4-20250514
```

### 3. Run Services

Open 5 terminal tabs:

```bash
# Terminal 1 — Dashboard (start this first)
PYTHONPATH=. python -m ui_client

# Terminal 2 — Lead Finder
PYTHONPATH=. python -m lead_finder

# Terminal 3 — SDR Agent
PYTHONPATH=. python -m sdr

# Terminal 4 — Lead Manager
PYTHONPATH=. python -m lead_manager

# Terminal 5 — Gmail Listener
PYTHONPATH=. python gmail_pubsub_listener/gmail_listener_service.py
```

### 4. Use It

1. Open **http://localhost:8000** in your browser
2. Enter a city (e.g., "San Francisco, CA") and click **Find Leads**
3. Watch leads populate in real-time via WebSocket
4. Click **Run SDR** on any lead to start the full outreach pipeline
5. Click **Process Inbox** to scan for replies and auto-schedule meetings

---

## 🔑 API Keys & Setup Guide

| Key | Where to Get It | What It Enables |
|-----|----------------|-----------------|
| `DEDALUS_API_KEY` | [Dedalus Dashboard](https://dedaluslabs.ai/dashboard/api-keys) | All LLM calls (OpenAI, Anthropic, etc.) via unified API |
| `GOOGLE_MAPS_API_KEY` | [GCP Console](https://console.cloud.google.com/apis/credentials) → Enable Places API | Lead discovery |
| `GOOGLE_CLOUD_PROJECT` | GCP Console → Project ID | BigQuery data storage |
| `SERVICE_ACCOUNT_FILE` | GCP → IAM → Service Accounts → Create Key (JSON) | Gmail + Calendar access |
| `SALES_EMAIL` | Your Gmail/Workspace email | Sending/receiving sales emails |
| `ELEVENLABS_API_KEY` | [ElevenLabs](https://elevenlabs.io) | AI phone calls |
| `ELEVENLABS_AGENT_ID` | ElevenLabs → Conversational AI → Create Agent | Phone call agent persona |

### GCP Service Account Permissions

The service account needs these scopes/roles:
- **Gmail API**: `gmail.modify` (send + read + mark as read)
- **Calendar API**: `calendar` (create events)
- **BigQuery**: `bigquery.dataEditor`, `bigquery.user`
- **Pub/Sub** (optional): `pubsub.subscriber`

Enable domain-wide delegation if using Google Workspace.

---

## 🧠 How the AI Works

### Dedalus ADK Integration

Every agent uses the **agent-as-tool** pattern from the Dedalus SDK:

```python
# Coordinator uses cheap model, delegates to specialist tools
result = await runner.run(
    input="Research this business, draft a proposal, then call them",
    model="openai/gpt-4.1",          # Cheap coordinator
    tools=[
        research_business,            # Calls runner.run() with Brave Search MCP
        draft_proposal,               # Calls runner.run() with Claude
        make_phone_call,              # Calls ElevenLabs API
        classify_call_outcome,        # Calls runner.run() with structured output
        send_outreach_email,          # Calls Gmail API
    ],
    max_steps=15,
)
```

Each specialist tool is itself a `runner.run()` call with a different model/MCP:

```python
async def research_business(business_name: str, city: str) -> str:
    """Deep research via web search."""
    result = await runner.run(
        input=f"Research {business_name} in {city}...",
        model="openai/gpt-4.1",
        mcp_servers=["windsor/brave-search-mcp"],  # Web search
    )
    return result.final_output
```

### Structured Outputs

Classification and analysis use Pydantic `response_format` for reliable parsing:

```python
result = await runner.run(
    input="Classify this call transcript...",
    model="openai/gpt-4.1",
    response_format=ConversationClassification,  # Pydantic model
)
```

---

## 📡 API Reference

### UI Client (`:8000`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard HTML |
| `GET` | `/health` | Service health check |
| `WS` | `/ws` | WebSocket for real-time events |
| `POST` | `/agent_callback` | Receive agent status updates |
| `POST` | `/start_lead_finding` | Trigger lead discovery |
| `POST` | `/start_sdr` | Trigger SDR pipeline for a lead |
| `POST` | `/start_email_processing` | Trigger inbox processing |
| `GET` | `/api/businesses` | Get all discovered leads |
| `GET` | `/api/events` | Get event log |
| `POST` | `/api/human-input/request` | Agent requests human feedback |
| `POST` | `/api/human-input/respond` | Human provides feedback |

### Lead Finder (`:8081`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/find_leads` | Start lead discovery for a city |
| `GET` | `/api/leads` | Get discovered leads |

### SDR Agent (`:8084`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/run_sdr` | Execute full SDR pipeline for a lead |
| `GET` | `/api/sessions` | Get SDR session history |

### Lead Manager (`:8082`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/process_emails` | Scan inbox and process all unread |
| `POST` | `/process_single_email` | Process one email (used by Gmail Listener) |
| `GET` | `/api/meetings` | Get scheduled meetings |

### Gmail Listener (`:8083`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check + processed count |

---

## 🛡️ MVP Limitations

- **In-memory state**: Lead/event data is lost on restart (BigQuery persists if configured)
- **No auth**: Dashboard and APIs are open (add JWT middleware for production)
- **Single-process**: Each service runs as one process (no horizontal scaling)
- **ElevenLabs API**: Depends on your plan's outbound calling capabilities
- **Gmail delegation**: Requires domain-wide delegation for service account email access

---

## 📜 License

Built at Columbia ADI DevFest Hackathon 2026.
