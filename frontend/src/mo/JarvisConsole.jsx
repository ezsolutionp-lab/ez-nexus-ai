/*
 * MO NEXUS OMEGA — JARVIS voice console.
 *
 * Say "MO" (or "hey MO", "jarvis"), and MO answers out loud. Keep talking — for
 * 30 seconds after each reply you don't need to say the name again. Talk over
 * MO and it stops to listen, the way a person would.
 *
 * How it actually works, so nothing here is overstated:
 *   - Speech recognition and speech synthesis run IN THIS BROWSER via the Web
 *     Speech API. Raw microphone audio is never sent to MO; only the finished
 *     transcript is.
 *   - Wake-word detection is transcript-level phrase matching (done server-side),
 *     not an always-on acoustic model like Alexa's. It works, but the browser is
 *     transcribing continuously while the console is open.
 *   - Recognition needs a Chromium or Safari engine. Firefox has none, so the
 *     console falls back to typing — the conversation still works.
 *
 * The two hard problems handled here:
 *   ECHO — MO's voice comes out of the speakers and back into the microphone.
 *          Without suppression MO would hear itself and answer itself forever.
 *   BARGE-IN — you can still interrupt MO mid-sentence. Speech that isn't an
 *          echo of what MO is saying cancels MO's speech immediately.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'

const API = import.meta.env.VITE_API_URL || ''

const Recognition =
  typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition)
const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window

async function call(path, { method = 'GET', body, token } = {}) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    ...(body ? { body: JSON.stringify(body) } : {}),
  })
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { raw: text } }
  if (!response.ok) {
    const detail = data?.detail
    throw new Error(detail?.detail || detail || `HTTP ${response.status}`)
  }
  return data
}

/* ── Echo detection ─────────────────────────────────────────────────────────
 * True when `heard` is mostly words MO itself just said. Word overlap rather
 * than exact match, because recognition of our own playback is never exact.
 */
const WORD = /[a-z0-9']+/g
function words(text) { return (String(text).toLowerCase().match(WORD) || []) }
export function isEcho(heard, spoken, threshold = 0.6) {
  const h = words(heard)
  if (!h.length || !spoken) return false
  const s = new Set(words(spoken))
  const overlap = h.filter(w => s.has(w)).length
  return overlap / h.length >= threshold
}

/* Voice preferences live in this browser only. */
const PREFS_KEY = 'jv_prefs'
const ADDRESS_PRESETS = ['boss', 'sir', "ma'am", 'chief', '']
function loadPrefs() {
  try { return { address: 'boss', voice: '', rate: 0.98, pitch: 0.88, ...(JSON.parse(localStorage.getItem(PREFS_KEY) || '{}')) } }
  catch { return { address: 'boss', voice: '', rate: 0.98, pitch: 0.88 } }
}
function savePrefs(p) { try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)) } catch { /* private mode */ } }
const timezone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' } catch { return 'UTC' } }

/*
 * Pick the voice: the user's choice if it still exists, else the closest thing the browser has to a calm, measured
 * British male voice (the register this assistant speaks in), else any local voice in the session language.
 * Which voices exist is decided by the browser and operating system, not by MO.
 */
const JARVIS_LIKE = ['Google UK English Male', 'Daniel', 'Arthur', 'Oliver', 'Microsoft George', 'Microsoft Ryan', 'Alex']
function chooseVoice(lang, wanted = '') {
  if (!canSpeak) return null
  const all = window.speechSynthesis.getVoices()
  const chosen = wanted && all.find(v => v.name === wanted)
  if (chosen) return chosen
  const voices = all.filter(v => v.lang?.startsWith(lang.slice(0, 2)))
  for (const name of JARVIS_LIKE) {
    const v = voices.find(x => x.name.includes(name))
    if (v) return v
  }
  return voices.find(v => v.lang === 'en-GB') || voices.find(v => v.localService) || voices[0] || null
}

const MODE_LABEL = {
  off: 'Microphone off',
  asleep: 'Listening for “MO” or “Jarvis”',
  awake: 'I’m listening',
  thinking: 'Working on it',
  speaking: 'Speaking',
}

export default function JarvisConsole({ token }) {
  const [session, setSession] = useState(null)
  const [mode, setMode] = useState('off')
  const [interim, setInterim] = useState('')
  const [log, setLog] = useState([])
  const [error, setError] = useState(null)
  const [typed, setTyped] = useState('')
  const [level, setLevel] = useState(0)
  const [muted, setMuted] = useState(false)
  const [examples, setExamples] = useState([])
  const [prefs, setPrefs] = useState(loadPrefs)
  const [voices, setVoices] = useState([])

  const recRef = useRef(null)
  const wantListening = useRef(false)
  const speakingText = useRef('')      // what MO is saying right now, for echo checks
  const lastSpoken = useRef('')        // what MO said last, echo can trail playback
  const busy = useRef(false)
  const queued = useRef([])            // utterances that arrived while MO was still handling the last one
  const sendRef = useRef(null)
  const audio = useRef({ ctx: null, stream: null, raf: 0 })
  const sessionRef = useRef(null)
  const logEnd = useRef(null)

  useEffect(() => { sessionRef.current = session }, [session])
  useEffect(() => { logEnd.current?.scrollIntoView({ behavior: 'smooth' }) }, [log, interim])

  /* ── Start a conversation ─────────────────────────────────────────────── */
  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const s = await call('/api/mo/voice/sessions', { method: 'POST', token,
          body: { address: prefs.address, timezone: timezone() } })
        if (!cancelled) setSession(s)
        const c = await call('/api/mo/voice/commands', { token })
        if (!cancelled) setExamples(c.examples.slice(0, 8))
      } catch (e) { if (!cancelled) setError(e.message) }
    })()
    if (canSpeak) {
      const refresh = () => setVoices(window.speechSynthesis.getVoices().filter(v => v.lang?.startsWith('en')))
      refresh()
      window.speechSynthesis.addEventListener?.('voiceschanged', refresh)
    }
    return () => { cancelled = true }
  }, [token, prefs.address])

  const updatePrefs = useCallback((patch) => {
    setPrefs(p => { const next = { ...p, ...patch }; savePrefs(next); return next })
  }, [])

  /* ── MO speaks ───────────────────────────────────────────────────────── */
  const speak = useCallback((text) => {
    if (!text || !canSpeak || muted) return
    window.speechSynthesis.cancel()
    const u = new SpeechSynthesisUtterance(text)
    const v = chooseVoice(session?.language || 'en-US', prefs.voice)
    if (v) u.voice = v
    if (v?.lang) u.lang = v.lang
    u.rate = prefs.rate
    u.pitch = prefs.pitch
    speakingText.current = text
    u.onstart = () => setMode('speaking')
    const done = () => {
      lastSpoken.current = speakingText.current
      speakingText.current = ''
      setMode(m => (m === 'speaking' ? 'awake' : m))
    }
    u.onend = done
    u.onerror = done
    window.speechSynthesis.speak(u)
  }, [muted, session, prefs])

  /* Stop MO mid-sentence — barge-in. */
  const interrupt = useCallback(() => {
    if (canSpeak && window.speechSynthesis.speaking) {
      window.speechSynthesis.cancel()
      lastSpoken.current = speakingText.current
      speakingText.current = ''
      setMode('awake')
    }
  }, [])

  /* ── Send one utterance to MO ─────────────────────────────────────────── */
  const send = useCallback(async (transcript) => {
    const s = sessionRef.current
    if (!s || !transcript.trim()) return
    if (busy.current) { queued.current.push(transcript); return }          // never drop what the user said
    busy.current = true
    setMode(m => (m === 'speaking' ? m : 'thinking'))
    try {
      const r = await call(`/api/mo/voice/sessions/${s.session_id}/turns`, {
        method: 'POST', token, body: { transcript },
      })
      if (r.reply) {
        setLog(l => [...l, { who: 'you', text: transcript },
                          { who: 'mo', text: r.reply, state: r.state, intent: r.intent?.intent }])
        speak(r.reply)
        if (!canSpeak || muted) setMode(r.awake ? 'awake' : 'asleep')
      } else {
        // MO was asleep and not addressed: stay quiet, show nothing.
        setMode(wantListening.current ? 'asleep' : 'off')
      }
      if (!r.reply) return
      if (!r.awake && !(canSpeak && !muted)) setMode('asleep')
    } catch (e) {
      setError(e.message)
      setMode(wantListening.current ? 'asleep' : 'off')
    } finally {
      busy.current = false
      const next = queued.current.shift()
      if (next) setTimeout(() => sendRef.current?.(next), 0)
    }
  }, [token, speak, muted])
  useEffect(() => { sendRef.current = send }, [send])

  /* ── Microphone level meter (visual proof MO can hear you) ────────────── */
  const startMeter = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      })
      const ctx = new (window.AudioContext || window.webkitAudioContext)()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 512
      ctx.createMediaStreamSource(stream).connect(analyser)
      const buf = new Uint8Array(analyser.fftSize)
      const tick = () => {
        analyser.getByteTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v }
        setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4))
        audio.current.raf = requestAnimationFrame(tick)
      }
      tick()
      audio.current = { ctx, stream, raf: audio.current.raf }
    } catch {
      /* Meter is decoration; recognition can still work without it. */
    }
  }, [])

  const stopMeter = useCallback(() => {
    const a = audio.current
    cancelAnimationFrame(a.raf)
    a.stream?.getTracks().forEach(t => t.stop())
    a.ctx?.close?.()
    audio.current = { ctx: null, stream: null, raf: 0 }
    setLevel(0)
  }, [])

  /* ── Continuous recognition ───────────────────────────────────────────── */
  const startListening = useCallback(() => {
    if (!Recognition) {
      setError('This browser has no speech recognition. Use Chrome, Edge or Safari — or type below.')
      return
    }
    const rec = new Recognition()
    rec.continuous = true
    rec.interimResults = true
    rec.lang = sessionRef.current?.language || 'en-US'

    rec.onresult = (event) => {
      let finalText = ''
      let interimText = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript
        if (event.results[i].isFinal) finalText += t
        else interimText += t
      }
      const current = speakingText.current

      // Barge-in: real speech over MO — not MO's own voice coming back — stops MO.
      if (interimText && current && !isEcho(interimText, current)) interrupt()
      setInterim(current && isEcho(interimText, current) ? '' : interimText)

      if (finalText.trim()) {
        setInterim('')
        // Drop MO hearing itself, during playback and just after it.
        if (isEcho(finalText, current) || isEcho(finalText, lastSpoken.current, 0.8)) return
        send(finalText.trim())
      }
    }
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        setError('Microphone permission was denied. Allow it in the browser to talk to MO.')
        wantListening.current = false
        setMode('off')
      }
      // 'no-speech' and 'aborted' are routine; onend restarts us.
    }
    // Browsers end recognition after silence. Restart while the user wants it on.
    rec.onend = () => {
      if (wantListening.current) { try { rec.start() } catch { /* already started */ } }
    }

    recRef.current = rec
    wantListening.current = true
    setError(null)
    try { rec.start() } catch { /* already started */ }
    setMode('asleep')
    startMeter()
  }, [send, interrupt, startMeter])

  const stopListening = useCallback(() => {
    wantListening.current = false
    try { recRef.current?.stop() } catch { /* not started */ }
    recRef.current = null
    interrupt()
    stopMeter()
    setInterim('')
    setMode('off')
  }, [interrupt, stopMeter])

  useEffect(() => () => {
    wantListening.current = false
    try { recRef.current?.stop() } catch { /* noop */ }
    stopMeter()
    if (canSpeak) window.speechSynthesis.cancel()
  }, [stopMeter])

  const submitTyped = (e) => {
    e.preventDefault()
    if (!typed.trim()) return
    interrupt()
    send(typed.trim())
    setTyped('')
  }

  if (!token) return <div className="jv-empty">Sign in to talk to MO.</div>

  const listening = mode !== 'off'

  return (
    <div className="jv">
      <div className="jv-stage">
        <button
          className={`jv-orb jv-orb--${mode}`}
          style={{ '--level': level }}
          onClick={listening ? stopListening : startListening}
          aria-label={listening ? 'Stop listening' : 'Start listening'}
          aria-pressed={listening}
        >
          <span className="jv-orb__core" />
          <span className="jv-orb__ring" />
        </button>
        <div className="jv-status" role="status" aria-live="polite">
          <div className="jv-status__mode">{MODE_LABEL[mode]}</div>
          <div className="jv-status__hint">
            {mode === 'off' && 'Tap the orb, then say “MO” or “Jarvis”.'}
            {mode === 'asleep' && 'Say “MO” or “Jarvis” to wake me.'}
            {mode === 'awake' && 'Go ahead — no need to say my name again for a bit.'}
            {mode === 'thinking' && 'One moment…'}
            {mode === 'speaking' && 'Talk over me any time to interrupt.'}
          </div>
        </div>
        <div className="jv-controls">
          <button className="jv-btn" onClick={() => setMuted(m => !m)} aria-pressed={muted}>
            {muted ? 'Voice off' : 'Voice on'}
          </button>
          {mode === 'speaking' && (
            <button className="jv-btn" onClick={interrupt}>Stop talking</button>
          )}
        </div>
      </div>

      {!Recognition && (
        <div className="jv-notice">
          This browser can't do speech recognition, so you'll need to type. Chrome, Edge and
          Safari support talking to MO directly.
        </div>
      )}
      {error && <div className="jv-error" role="alert">{error}</div>}

      <div className="jv-log" aria-live="polite">
        {log.length === 0 && (
          <div className="jv-intro">
            <p>Try saying:</p>
            <ul>
              <li>“Jarvis”</li>
              {examples.slice(0, 6).map(x => <li key={x.say}>“{x.say}”</li>)}
            </ul>
          </div>
        )}
        {log.map((m, i) => (
          <div key={i} className={`jv-msg jv-msg--${m.who}`}>
            <div className="jv-msg__who">{m.who === 'mo' ? 'MO' : 'You'}</div>
            <div className="jv-msg__text">{m.text}</div>
            {m.who === 'mo' && m.state && m.state !== 'SUCCESS' && (
              <div className={`jv-msg__state jv-state--${m.state.toLowerCase()}`}>
                {m.state.replace(/_/g, ' ').toLowerCase()}
              </div>
            )}
          </div>
        ))}
        {interim && <div className="jv-msg jv-msg--you jv-msg--interim">{interim}…</div>}
        <div ref={logEnd} />
      </div>


      <details className="jv-settings">
        <summary>Voice settings</summary>
        <label>
          Call me
          <select value={ADDRESS_PRESETS.includes(prefs.address) ? prefs.address : '__custom'}
                  onChange={e => updatePrefs({ address: e.target.value === '__custom' ? 'friend' : e.target.value })}>
            {ADDRESS_PRESETS.map(a => <option key={a} value={a}>{a === '' ? '(no form of address)' : a}</option>)}
            <option value="__custom">a name…</option>
          </select>
        </label>
        {!ADDRESS_PRESETS.includes(prefs.address) && (
          <input aria-label="Your name" maxLength={24} value={prefs.address}
                 onChange={e => updatePrefs({ address: e.target.value.replace(/[^A-Za-z .'-]/g, '') })} />
        )}
        <label>
          Voice
          <select value={prefs.voice} onChange={e => updatePrefs({ voice: e.target.value })}>
            <option value="">Automatic (closest to a calm British male)</option>
            {voices.map(v => <option key={v.name} value={v.name}>{v.name} ({v.lang})</option>)}
          </select>
        </label>
        <label>Speed
          <input type="range" min="0.7" max="1.3" step="0.02" value={prefs.rate}
                 onChange={e => updatePrefs({ rate: Number(e.target.value) })} />
        </label>
        <label>Pitch
          <input type="range" min="0.6" max="1.3" step="0.02" value={prefs.pitch}
                 onChange={e => updatePrefs({ pitch: Number(e.target.value) })} />
        </label>
        <button type="button" className="jv-btn" onClick={() => speak(`At your service${prefs.address ? ', ' + prefs.address : ''}.`)}>
          Test voice
        </button>
        <p className="jv-privacy">
          The available voices come from your browser and operating system. Changing the form of address starts a fresh
          conversation.
        </p>
      </details>

      <form className="jv-type" onSubmit={submitTyped}>
        <input
          value={typed}
          onChange={e => setTyped(e.target.value)}
          placeholder="Or type — e.g. “Jarvis, run diagnostics” or “brief me”"
          aria-label="Type a message to MO"
        />
        <button type="submit" disabled={!typed.trim() || !session}>Send</button>
      </form>

      <p className="jv-privacy">
        Speech is recognised in your browser. MO receives only the text, never the audio.
      </p>
    </div>
  )
}
