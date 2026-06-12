# EZ-NEXUS AI Platform
### Your AI Workforce for Business Growth™

A full-stack AI-powered business operations platform with real-time notifications, call analysis, and appointment management.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python · FastAPI 0.111 · SQLAlchemy 2.0 · SQLite / PostgreSQL |
| AI | Heuristic engine (built-in) · OpenAI GPT-3.5 (optional) |
| Real-time | WebSocket NotificationHub |
| Frontend | React 18 · Vite 5 |

---

## Project Structure

```
ez-nexus-ai/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── database.py        # SQLAlchemy engine + session
│   │   ├── models.py          # Business + Appointment ORM models
│   │   ├── schemas.py         # Pydantic v2 request/response schemas
│   │   ├── ai_agent.py        # AI transcript analysis engine
│   │   ├── notifications.py   # WebSocket NotificationHub
│   │   └── main.py            # FastAPI app + all routes
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── main.jsx            # React app (all tabs + WebSocket client)
        └── style.css           # Brand styles + component CSS
```

---

## Quick Start

### 1 — Backend Setup

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY to enable GPT enhancement (optional)

# Start the API server
uvicorn app.main:app --reload --port 8000
```

The API will be available at **http://localhost:8000**  
Interactive API docs: **http://localhost:8000/docs**

### 2 — Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The dashboard will be available at **http://localhost:5173**

---

## API Reference

### Businesses

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/businesses` | Create business |
| `GET` | `/businesses` | List all active businesses |
| `GET` | `/businesses/{id}` | Get single business |
| `PUT` | `/businesses/{id}` | Update business |
| `DELETE` | `/businesses/{id}` | Soft-delete (sets is_active=false) |

### Appointments

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/appointments` | Book appointment |
| `GET` | `/appointments` | List appointments (filter: `?business_id=&status=`) |
| `GET` | `/appointments/{id}` | Get single appointment |
| `PUT` | `/appointments/{id}` | Update appointment |
| `DELETE` | `/appointments/{id}` | Cancel appointment |

### AI Analysis

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/ai/summarize` | Analyze call transcript → summary, triage, actions, sentiment |

```json
// POST /ai/summarize
{
  "transcript": "Caller: Hi, my account is locked and I can't login...",
  "appointment_id": 42   // optional — saves result to appointment
}

// Response
{
  "summary": "Client reported account lockout. Agent confirmed identity and initiated reset.",
  "triage": "urgent",
  "action_items": ["Reset client account password", "Send confirmation email"],
  "sentiment": "negative"
}
```

### Stats & WebSocket

| Endpoint | Description |
|----------|-------------|
| `GET /stats` | Platform metrics (businesses, appointments, urgent, ws connections) |
| `GET /` | Health check |
| `WS /ws/{client_id}` | Real-time notification stream |

---

## WebSocket Events

Connect to `ws://localhost:8000/ws/<any-client-id>` to receive live events:

```json
{ "type": "new_appointment", "message": "New appointment: Jane Doe — Consultation",
  "data": { "appointment_id": 1, "business_id": 2, ... } }

{ "type": "ai_summary", "message": "AI summary ready for appointment #5",
  "data": { "appointment_id": 5, "triage": "urgent", "summary": "..." } }

{ "type": "status_change", "message": "Appointment #3 status: scheduled → completed",
  "data": { "appointment_id": 3, "old_status": "scheduled", "new_status": "completed" } }
```

Send `ping` to keep the connection alive; the server responds with `{"type":"pong"}`.

---

## AI Engine

The platform ships with a fully offline heuristic AI engine — **no API key required**:

| Feature | How it works |
|---------|-------------|
| **Triage** | Keyword density scoring → `urgent` / `normal` / `low` |
| **Sentiment** | Positive/negative keyword sets → `positive` / `neutral` / `negative` |
| **Action items** | Regex extraction of imperative patterns, capped at 10 |
| **Summary** | First 2 + action-heavy + last 2 sentences |

**Optional GPT Enhancement**: set `OPENAI_API_KEY` in `.env` to enable GPT-3.5-turbo analysis. The engine tries OpenAI first and silently falls back to heuristics on failure.

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and configure:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./ez_nexus.db` | Database connection string |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Server port |
| `OPENAI_API_KEY` | _(empty)_ | Enables GPT analysis when set |
| `SECRET_KEY` | `change-me` | JWT signing key |
| `ALLOWED_ORIGINS` | `*` | CORS origins (comma-separated) |

**PostgreSQL example:**
```
DATABASE_URL=postgresql://user:password@localhost:5432/eznexus
```

---

## Production Build

```bash
# Frontend — build static assets
cd frontend
npm run build          # outputs to frontend/dist/

# Backend — run without --reload
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Serve the `frontend/dist/` folder from any static host (Nginx, Vercel, S3+CloudFront).  
Point `/api` and `/ws` proxies to the FastAPI server.

---

## Brand Colors

| Token | Hex | Use |
|-------|-----|-----|
| Navy | `#0D1F3C` | Navbar, headings |
| Blue | `#1B4FD8` | Primary actions |
| Teal | `#0F766E` | AI features, success states |

---

*EZ-NEXUS AI — Your AI Workforce for Business Growth™*
