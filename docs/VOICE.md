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

## The Jarvis register

Call it **MO** or **Jarvis** ("Jarvis", "hey Jarvis", "okay Jarvis", "MO"). What it does:

- **Wake and brief.** On a fresh wake (or after half an hour of quiet) it greets you for your local time of day and gives one
  honest status line: `Good evening, boss. Systems are up. One build has failed and two approvals are waiting on you.` It only
  says "All systems are running normally" when the audit trail verifies and nothing needs you.
- **Your form of address.** boss, sir, ma'am, chief, your name, or none. Set it in *Voice settings*; MO never assumes one.
- **Situational awareness.** "Brief me", "what did I miss", "run diagnostics" (database, audit trail, tools, model, sandbox
  isolation, server speech), "what time is it" (in your timezone).
- **Small talk.** Thanks, "how are you", "who are you" (it says it is software), "good morning", and "that will be all" to stand
  down.
- **Offers.** After a build it asks *Shall I bring up the preview?* and "yes please" / "not now" work. An accepted offer runs
  through exactly the same scope, MFA and approval gates as if you had asked for it.
- **Bad news first.** "I'm afraid the build failed, boss." It never softens a failure into something that sounds like success.
- **Free-form requests.** With a model provider connected, a request that matches no phrase is mapped to one of the *existing*
  intents ("get me up to speed on where everything stands" becomes the briefing) and then goes through the normal gates. Anything
  else becomes conversation: at most three spoken sentences, which cannot take actions or claim to have taken any.
- **Voice.** The console picks the closest voice your browser has to a calm British male (for example Daniel or Google UK English
  Male), slightly slower and lower than default. You can choose a voice, speed and pitch. Which voices exist depends on your
  browser and operating system.
- **Talking naturally.** You can talk over MO to interrupt it, it ignores its own voice, and utterances that arrive while it is
  still answering are queued rather than dropped.

What it is not: the film character. It has no persistent physical-world reach, its commands are the intents listed by
*help* (plus what a connected model can map onto them), approving a high-impact action by voice is refused by design, and
wake-word detection is transcript-level rather than an always-on acoustic model.

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
