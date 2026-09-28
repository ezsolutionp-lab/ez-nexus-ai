# Talking to MO — voice assistant

Say **"MO"** and MO answers out loud, in plain conversational language, and
does what you ask. It is built into the console: open the **🎙️ Talk to MO** tab.

## What works today

| Capability | Status | How |
|---|---|---|
| Wake by name ("MO", "hey MO", "okay MO") | Works | Transcript keyword match, see limits below |
| Spoken replies, human phrasing | Works | Browser speech synthesis; replies are written to be heard |
| Follow-up conversation, no need to repeat "MO" | Works | 30-second wake window, extended on each turn |
| Follow-up questions for missing details | Works | "Deploy it" -> "Which environment?" -> "staging" |
| Talk over MO (barge-in) | Works | Speech cancels playback |
| Ignores its own voice (echo suppression) | Works | Transcripts that match what MO just said are dropped |
| Builds, previews, status, audit, agents, approvals list | Works | Real MO operations, same code as the HTTP API |
| Typed fallback | Works | For browsers without speech recognition |

Example conversation (real output from the test-verified engine):

> **You:** Some background chatter about dinner  — *MO stays silent*
> **You:** MO — *"Yes? I'm listening."*
> **You:** Build me a website for a plumbing company with online booking
> **MO:** *builds it, then reports modules, models and pages, that tests passed, and which integrations still need credentials*
> **You:** Show me the preview
> **You:** Deploy it — *"Which environment, staging or production?"*
> **You:** Staging — *"that needs sign-off first"*
> **You:** Approve the deployment — *refused: approvals cannot be given by voice*
> **You:** Never mind — *MO goes back to sleep*

Say **"help"** for more examples, or `GET /api/mo/voice/commands`.

## Honest limitations

These are real gaps, not roadmap decoration. `GET /api/mo/voice/capabilities`
reports the same list.

- **Wake word is a transcript keyword, not an acoustic model.** The browser
  transcribes continuously and MO reacts when it hears its name. That means the
  microphone stays on while the console is listening (the UI says so), the tab
  must stay open, and it can mishear. A true always-on, on-device wake-word
  detector (Porcupine/openWakeWord) is not built.
- **No speaker verification.** MO cannot tell *who* is speaking from their voice.
  Identity is the signed-in user's bearer token; anyone at that keyboard acts as
  that user.
- **Approvals cannot be given by voice.** Approving a deployment needs a
  separate authenticated party and cannot be established from speech. MO
  refuses and says so.
- **Recognition runs in the browser.** Chrome, Edge and Safari support it;
  Firefox does not (use the typed box). Chrome's implementation may send audio
  to the browser vendor's speech service — that is the browser's behaviour, not
  MO's. MO's server receives **transcripts only**, never audio.
- **Server-side streaming STT/TTS (cloud providers) and Twilio phone calls** are
  declared in the provider fabric but report `CREDENTIAL_REQUIRED` /
  not-implemented until wired. Phone calls would be turn-based with no barge-in.
- **Not everything is voice-controllable yet.** Only the intents in `/commands`.
  Anything else gets "I didn't catch that", never a guess.

## How it stays governed

- Every voice turn runs under the caller's own `RequestContext` with the channel
  stamped `VOICE`. Voice never has more authority than the token behind it.
- Same scopes, MFA and approval rules as HTTP. Deployment is approval-gated;
  execution without a deploy adapter reports `CREDENTIAL_REQUIRED`.
- Sessions are bound to tenant and user. Another tenant's session reads as 404.
- Every turn is recorded (`mo_voice_turns`) and written to the hash-chained audit log.
- Turns use the `write` rate bucket (60/min); sandboxed builds are throttled
  separately at 12/min so ordinary conversation is never blocked by build limits.
- Transcripts are capped at 2000 characters.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/mo/voice/sessions` | Start a conversation |
| POST | `/api/mo/voice/sessions/{id}/turns` | `{"transcript": "..."}` -> reply, `speak` directive, `awake`, `expecting` |
| GET | `/api/mo/voice/sessions/{id}` | Transcript of the conversation |
| POST | `/api/mo/voice/sessions/{id}/end` | End it |
| GET | `/api/mo/voice/capabilities` | Truthful capability matrix |
| GET | `/api/mo/voice/commands` | Wake phrases and things to say |

The older stateless `POST /api/mo/voice/command` is unchanged.

## Running it locally

```bash
git clone <repo> && cd ez-nexus-ai
git checkout claude/mo-nexus-omega-platform-8ai5z1
export SECRET_KEY='<long random string>'
pip install -r backend/requirements.txt
(cd backend && alembic upgrade head && uvicorn app.main:app --reload)
(cd frontend && npm ci && npm run dev)
code .            # open in VS Code
```

Open the app in Chrome, Edge or Safari, sign in, choose **🎙️ Talk to MO**, allow
the microphone, and say "MO". Microphone access requires `localhost` or HTTPS.

## Tests

`pytest -m voice` — grammar and slot extraction, wake gating, follow-ups,
governance refusals, echo suppression, and the HTTP API (authentication, tenancy,
limits, throttling).
