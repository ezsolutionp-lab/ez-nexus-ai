/**
 * EZ-NEXUS AI Platform — React Frontend
 * Your AI Workforce for Business Growth™
 */

import React, { useState, useEffect, useCallback, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import { LangProvider, useLang, LANG_LIST } from './i18n.jsx'

// ── Config ──────────────────────────────────────────────────────────────────
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS  = API.replace(/^http/, 'ws')

// ── HTTP helpers ─────────────────────────────────────────────────────────────
async function apiFetch(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    // FastAPI validation errors return detail as an array of objects
    const detail = err.detail
    const message = Array.isArray(detail)
      ? detail.map(d => d.msg || String(d)).join(', ')
      : (typeof detail === 'string' ? detail : 'Request failed')
    throw new Error(message)
  }
  return res.json()
}

// ── Hooks ────────────────────────────────────────────────────────────────────
function useWebSocket(onMessage) {
  const [connected, setConnected] = useState(false)
  const wsRef = useRef(null)
  const clientId = useRef(`dashboard-${Math.random().toString(36).slice(2)}`)

  const connect = useCallback(() => {
    const ws = new WebSocket(`${WS}/ws/${clientId.current}`)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      wsRef.current._pingInterval = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send('ping')
      }, 25000)
    }

    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type !== 'pong' && data.type !== 'connected') onMessage(data)
      } catch { /* ignore */ }
    }

    ws.onclose = () => {
      setConnected(false)
      clearInterval(ws._pingInterval)
      setTimeout(connect, 3000)
    }

    ws.onerror = () => ws.close()
  }, [onMessage])

  useEffect(() => {
    connect()
    return () => {
      clearInterval(wsRef.current?._pingInterval)
      wsRef.current?.close()
    }
  }, [connect])

  return connected
}

// ── Shared Components ─────────────────────────────────────────────────────────
function Badge({ value }) {
  return <span className={`badge badge-${value}`}>{value}</span>
}

function Spinner() {
  return <div className="loading"><div className="spinner" /><span>Loading…</span></div>
}

function Alert({ msg, type = 'error' }) {
  if (!msg) return null
  return <div className={`alert alert-${type}`}>{msg}</div>
}

// ── Home Tab ──────────────────────────────────────────────────────────────────
const FEATURES = [
  { icon: '🎧', name: 'AI CALL CENTER',   desc: 'Smart Conversations. Better Customer Experiences.', tabId: 'call-center' },
  { icon: '📅', name: 'APPOINTMENTS',     desc: 'Schedule. Manage. Never Miss.',                     tabId: 'appointments' },
  { icon: '🖥️', name: 'WEBSITE BUILDER', desc: 'Build. Launch. Grow Online.',                       tabId: 'website-builder' },
  { icon: '📣', name: 'MARKETING & SEO',  desc: 'Get Found. Get Leads. Grow Faster.',                tabId: 'marketing' },
  { icon: '🎬', name: 'CONTENT STUDIO',   desc: 'Videos. Reels. Graphics. AI Powered.',              tabId: 'content-studio' },
  { icon: '👥', name: 'CRM & SALES',      desc: 'Leads to Loyal Customers.',                         tabId: 'businesses' },
  { icon: '📈', name: 'ANALYTICS',        desc: 'Insights. Reports. Smarter Decisions.',             tabId: 'dashboard' },
  { icon: '⚡', name: 'AUTOMATION',       desc: 'Workflows That Work. Save Time. Scale More.',       tabId: 'automation' },
]

const TRUST = [
  { icon: '📚', label: 'ALL-IN-ONE PLATFORM' },
  { icon: '🧠', label: 'AI POWERED' },
  { icon: '👤', label: 'HUMAN APPROVED' },
  { icon: '🎯', label: 'RESULTS DRIVEN' },
  { icon: '🔒', label: 'SECURE & RELIABLE' },
]

function HomeTab({ onNavigate }) {
  const { t } = useLang()
  const TRUST_ICONS = ['📚','🧠','👤','🎯','🔒']
  const FEAT_ICONS  = ['🎧','📅','🖥️','📣','🎬','👥','📈','⚡']
  const FEAT_TABS   = ['call-center','appointments','website-builder','marketing','content-studio','businesses','dashboard','automation']

  return (
    <div className="home-page">

      {/* ── Hero ── */}
      <div className="hero-section">
        <div className="hero-inner">
          <div className="en-logo-wrap">
            <div className="en-logo">
              <div className="en-orbit">
                <div className="en-orbit-ring" />
                <div className="en-orbit-ring en-orbit-ring--2" />
                <div className="en-node en-node--top">📞</div>
                <div className="en-node en-node--right">📊</div>
                <div className="en-node en-node--bottom">👥</div>
                <div className="en-node en-node--left">🌐</div>
              </div>
              <div className="en-letters">
                <span className="en-e">E</span><span className="en-n">N</span>
              </div>
            </div>
          </div>
          <div className="hero-divider" />
          <div className="hero-brand">
            <div className="hero-title">EZ-NEXUS <span className="hero-ai-badge">AI</span></div>
            <div className="hero-tagline">{t.home.heroTag}</div>
            <div className="hero-actions">
              <button className="btn btn-primary" onClick={() => onNavigate('appointments')}>{t.home.book}</button>
              <button className="btn btn-outline" onClick={() => onNavigate('dashboard')}>{t.home.viewDash}</button>
            </div>
          </div>
        </div>
      </div>

      {/* ── Feature Cards ── */}
      <div className="features-section">
        {t.features.map((f, i) => (
          <div className="feature-card" key={i} onClick={() => onNavigate(FEAT_TABS[i])} title={`Open ${f.name}`}>
            <div className="feature-icon">{FEAT_ICONS[i]}</div>
            <div className="feature-name">{f.name}</div>
            <div className="feature-desc">{f.desc}</div>
            <div className="feature-arrow">→</div>
          </div>
        ))}
      </div>

      {/* ── Trust Bar ── */}
      <div className="trust-bar">
        {t.trust.map((label, i) => (
          <React.Fragment key={i}>
            <div className="trust-item">
              <span className="trust-icon">{TRUST_ICONS[i]}</span>
              <span className="trust-label">{label}</span>
            </div>
            {i < t.trust.length - 1 && <div className="trust-sep" />}
          </React.Fragment>
        ))}
      </div>

    </div>
  )
}

// ── Coming Soon Tab ───────────────────────────────────────────────────────────
function ComingSoonTab({ tabId, onBack }) {
  const { t } = useLang()
  const FEAT_ICONS = ['🎧','📅','🖥️','📣','🎬','👥','📈','⚡']
  const FEAT_TABS  = ['call-center','appointments','website-builder','marketing','content-studio','businesses','dashboard','automation']
  const idx = FEAT_TABS.indexOf(tabId)
  const icon = idx >= 0 ? FEAT_ICONS[idx] : '🚀'
  const feat = idx >= 0 ? t.features[idx] : { name: tabId, desc: '' }
  return (
    <div className="card coming-soon-card">
      <div className="coming-soon-body">
        <div className="coming-soon-icon">{icon}</div>
        <h2 className="coming-soon-title">{feat.name}</h2>
        <p className="coming-soon-desc">{feat.desc}</p>
        <div className="coming-soon-badge">{t.home.comingSoon}</div>
        <p className="coming-soon-sub">{t.home.comingSoonSub}</p>
        <button className="btn btn-outline" onClick={onBack}>{t.home.back}</button>
      </div>
    </div>
  )
}

// ── Web Audio ring tone helper ────────────────────────────────────────────────
function buildRingtone() {
  const AudioCtx = window.AudioContext || window.webkitAudioContext
  if (!AudioCtx) return null
  const ctx = new AudioCtx()
  let alive = true
  let cycleTimer = null

  const burst = (startAt) => {
    // Classic dual-tone ring: 480 Hz + 440 Hz, two short pulses
    [[0, 0.35], [0.5, 0.35]].forEach(([offset, dur]) => {
      ;[480, 440].forEach(freq => {
        const osc  = ctx.createOscillator()
        const gain = ctx.createGain()
        osc.connect(gain); gain.connect(ctx.destination)
        osc.frequency.value = freq
        gain.gain.setValueAtTime(0.07, startAt + offset)
        gain.gain.exponentialRampToValueAtTime(0.0001, startAt + offset + dur)
        osc.start(startAt + offset)
        osc.stop(startAt + offset + dur + 0.05)
      })
    })
  }

  const ring = () => {
    if (!alive) return
    burst(ctx.currentTime)
    cycleTimer = setTimeout(ring, 2400)
  }

  ring()
  return { stop: () => { alive = false; clearTimeout(cycleTimer); ctx.close().catch(() => {}) } }
}

// ── AI Call Center Tab ────────────────────────────────────────────────────────
function CallCenterTab() {
  const { t } = useLang()
  const [calls, setCalls]   = useState(() => {
    try { return JSON.parse(localStorage.getItem('ez_nexus_calls') || '[]') } catch (e) { return [] }
  })
  // callPhase: null | 'preview' | 'dialing' | 'active'
  const [callPhase, setCallPhase]   = useState(null)
  const [activeCall, setActiveCall] = useState(null)
  const [ringCount, setRingCount]   = useState(0)
  const [transcript, setTranscript] = useState('')
  const [analysis, setAnalysis]     = useState(null)
  const [analyzing, setAnalyzing]   = useState(false)
  const [showForm, setShowForm]     = useState(false)
  const [form, setForm]             = useState({ caller_name: '', caller_phone: '', reason: '' })
  const [callTimer, setCallTimer]   = useState(0)
  const [micActive, setMicActive]   = useState(false)
  const [copied, setCopied]         = useState(false)
  const [error, setError]           = useState('')

  const timerRef    = useRef(null)
  const analyzeRef  = useRef(null)
  const ringtoneRef = useRef(null)
  const micRef      = useRef(null)
  const ringCountRef = useRef(0)

  const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2,'0')}:${String(s % 60).padStart(2,'0')}`
  const saveCalls = (list) => { setCalls(list); localStorage.setItem('ez_nexus_calls', JSON.stringify(list)) }

  const todayCalls  = calls.filter(c => new Date(c.started_at).toDateString() === new Date().toDateString())
  const urgentCalls = calls.filter(c => c.analysis?.triage === 'urgent')

  // ── Mic helpers
  const startMic = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      micRef.current = stream
      setMicActive(true)
    } catch {
      setError('Microphone access denied. Click the padlock in the address bar to allow it.')
    }
  }, [])

  const stopMic = useCallback(() => {
    micRef.current?.getTracks().forEach(t => t.stop())
    micRef.current = null
    setMicActive(false)
  }, [])

  // ── Connect (dialing → active)
  const connectCall = useCallback(() => {
    ringtoneRef.current?.stop()
    ringtoneRef.current = null
    setCallPhase('active')
    setCallTimer(0)
    timerRef.current = setInterval(() => setCallTimer(t => t + 1), 1000)
    startMic()
  }, [startMic])

  // Auto-connect after 4 rings
  useEffect(() => {
    if (callPhase === 'dialing' && ringCount >= 4) connectCall()
  }, [ringCount, callPhase, connectCall])

  // ── Step 1: show preview modal with number + "I'm on the call" button
  const startCall = (e) => {
    e.preventDefault()
    const call = {
      id: Date.now(),
      caller_name: form.caller_name,
      caller_phone: form.caller_phone,
      reason: form.reason,
      started_at: new Date().toISOString(),
    }
    setActiveCall(call)
    setCallPhase('preview')
    setCopied(false)
    setShowForm(false)
    setTranscript(''); setAnalysis(null); setCallTimer(0)
  }

  // ── Copy number to clipboard
  const copyNumber = () => {
    if (!activeCall?.caller_phone) return
    navigator.clipboard.writeText(activeCall.caller_phone).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    })
  }

  // ── Step 2: user confirms they are on the call → start timer + mic + ring UI
  const confirmOnCall = () => {
    setForm({ caller_name: '', caller_phone: '', reason: '' })
    setCallPhase('dialing')
    setRingCount(0)
    ringCountRef.current = 0
    ringtoneRef.current = buildRingtone()
    const ringTick = setInterval(() => {
      ringCountRef.current += 1
      setRingCount(ringCountRef.current)
      if (ringCountRef.current >= 4) clearInterval(ringTick)
    }, 2400)
  }

  // ── End / Decline
  const endCall = useCallback((declined = false) => {
    ringtoneRef.current?.stop(); ringtoneRef.current = null
    clearInterval(timerRef.current)
    clearTimeout(analyzeRef.current)
    stopMic()

    if (!declined && activeCall && callPhase === 'active') {
      saveCalls([{ ...activeCall, transcript, analysis, ended_at: new Date().toISOString(), duration: callTimer }, ...calls])
    }
    setCallPhase(null); setActiveCall(null)
    setTranscript(''); setAnalysis(null); setCallTimer(0); setRingCount(0)
  }, [activeCall, callPhase, transcript, analysis, callTimer, calls, stopMic])

  // ── AI transcript
  const analyzeNow = useCallback(async (text) => {
    if (!text.trim() || text.length < 25) return
    setAnalyzing(true)
    try {
      setAnalysis(await apiFetch('/ai/summarize', { method: 'POST', body: JSON.stringify({ transcript: text }) }))
    } catch (e) { setError(e.message) }
    finally { setAnalyzing(false) }
  }, [])

  const handleTranscript = (val) => {
    setTranscript(val)
    clearTimeout(analyzeRef.current)
    if (val.length > 30) analyzeRef.current = setTimeout(() => analyzeNow(val), 1800)
  }

  // cleanup on unmount
  useEffect(() => () => {
    ringtoneRef.current?.stop()
    clearInterval(timerRef.current)
    clearTimeout(analyzeRef.current)
    stopMic()
  }, [stopMic])

  return (
    <div>
      <Alert msg={error} type="error" />

      {/* Stats */}
      <div className="stats-grid" style={{ marginBottom: 20 }}>
        <div className={`stat-card ${callPhase === 'active' ? 'teal' : ''}`}>
          <div className="stat-label">Status</div>
          <div className="stat-value" style={{ fontSize:'1.2rem' }}>
            {callPhase === 'active' ? '🔴 Live' : callPhase === 'dialing' ? `📳 ${t.call.ringing}` : t.call.ready}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t.call.today}</div>
          <div className="stat-value">{todayCalls.length}</div>
        </div>
        <div className="stat-card teal">
          <div className="stat-label">{t.call.total}</div>
          <div className="stat-value">{calls.length}</div>
        </div>
        <div className="stat-card urgent">
          <div className="stat-label">{t.call.urgent}</div>
          <div className="stat-value">{urgentCalls.length}</div>
        </div>
      </div>

      {/* ── Preview / Google Voice Call Modal */}
      {callPhase === 'preview' && activeCall && (
        <div className="card call-preview-card">

          {/* Header */}
          <div className="call-preview-header">
            <span className="gv-logo">G</span>
            <div>
              <div className="call-preview-name">{activeCall.caller_name}</div>
              {activeCall.reason && <div className="call-preview-reason">{activeCall.reason}</div>}
            </div>
            <div className="gv-badge">Google Voice</div>
          </div>

          {/* Big number + action buttons */}
          {activeCall.caller_phone ? (
            <div className="call-preview-number-row">
              <div className="call-preview-number">{activeCall.caller_phone}</div>
              <button className="btn btn-outline btn-sm" onClick={copyNumber}>
                {copied ? '✅ Copied!' : '📋 Copy'}
              </button>
            </div>
          ) : (
            <div className="call-preview-nonumber">No number — you can still log the call manually</div>
          )}

          {/* Google Voice launch button */}
          <button
            className="gv-launch-btn"
            onClick={() => {
              copyNumber()
              window.open('https://voice.google.com/calls', '_blank', 'width=420,height=680')
            }}
          >
            <span className="gv-launch-icon">G</span>
            <span>
              <strong>Open Google Voice</strong>
              <span className="gv-launch-sub">Number auto-copied — just paste &amp; call</span>
            </span>
            <span className="gv-launch-arrow">↗</span>
          </button>

          {/* Steps */}
          <div className="call-preview-steps">
            <div className="call-preview-step">
              <span className="step-num">1</span>
              <span>Click <strong>Open Google Voice</strong> above — the number is copied automatically</span>
            </div>
            <div className="call-preview-step">
              <span className="step-num">2</span>
              <span>In Google Voice: click the <strong>keypad icon</strong> → paste the number (Ctrl+V) → press Call</span>
            </div>
            <div className="call-preview-step">
              <span className="step-num">3</span>
              <span>When the other person picks up, click <strong>"I'm Connected"</strong> below to start AI logging</span>
            </div>
          </div>

          {/* Don't have Google Voice yet */}
          <div className="gv-setup-hint">
            <span>🆕 Don't have Google Voice yet?</span>
            <a href="https://voice.google.com" target="_blank" rel="noreferrer" className="gv-setup-link">
              Set it up free at voice.google.com →
            </a>
            <span className="gv-setup-note">Free US &amp; Canada calls • Needs a Google account</span>
          </div>

          {/* Action buttons */}
          <div className="call-preview-btns">
            <button
              className="btn btn-teal"
              style={{ fontSize:'1rem', padding:'10px 28px' }}
              onClick={confirmOnCall}
            >
              ✅ I'm Connected — Start AI Logging
            </button>
            <button className="btn btn-outline" onClick={() => { setCallPhase(null); setActiveCall(null) }}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Dialing screen */}
      {callPhase === 'dialing' && activeCall && (
        <div className="card dialing-card">
          <div className="dialing-phone-icon">📞</div>
          <div className="dialing-name">{activeCall.caller_name}</div>
          {activeCall.caller_phone && <div className="dialing-num">{activeCall.caller_phone}</div>}
          {activeCall.reason && <div className="dialing-reason">{activeCall.reason}</div>}
          <div className="dialing-rings">
            {[1,2,3,4].map(i => <div key={i} className={`ring-pip ${i <= ringCount ? 'ring-pip--lit' : ''}`} />)}
          </div>
          <div className="dialing-status">{ringCount === 0 ? t.call.connecting : `${t.call.ringing} (${ringCount})`}</div>
          <div className="dialing-btns">
            <button className="btn btn-teal" onClick={connectCall}>{t.call.answer}</button>
            <button className="btn btn-danger" onClick={() => endCall(true)}>{t.call.decline}</button>
          </div>
        </div>
      )}

      {/* ── Live call screen */}
      {callPhase === 'active' && activeCall && (
        <div className="card active-call-card">
          <div className="card-header">
            <div>
              <span className="live-dot" />
              <span className="card-title" style={{ color:'var(--teal)', marginLeft:8 }}>{t.call.live}</span>
              <span className="active-caller">
                {activeCall.caller_name}{activeCall.caller_phone ? ` — ${activeCall.caller_phone}` : ''}
              </span>
              {activeCall.reason && <span className="active-reason">{activeCall.reason}</span>}
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <button
                className={`btn btn-sm ${micActive ? 'btn-teal' : 'btn-outline'}`}
                onClick={micActive ? stopMic : startMic}
              >
                {micActive ? t.call.micOn : t.call.micOff}
              </button>
              <span className="call-timer">{fmt(callTimer)}</span>
              <button className="btn btn-danger" onClick={() => endCall(false)}>{t.call.end}</button>
            </div>
          </div>

          {micActive && (
            <div className="mic-bar">
              {[...Array(7)].map((_, i) => <span key={i} className="mic-wave" style={{ animationDelay: `${i * 0.1}s` }}>▌</span>)}
              <span style={{ marginLeft:10, fontSize:'.78rem', color:'var(--teal)', fontWeight:600 }}>
                Microphone active — speak clearly
              </span>
            </div>
          )}

          <div className="call-layout">
            <div className="call-transcript-col">
              <label className="form-label">{t.call.transcript}</label>
              <textarea
                className="form-textarea call-transcript"
                placeholder={"Type or paste what the caller says…\n\nAI will analyze automatically."}
                value={transcript}
                onChange={e => handleTranscript(e.target.value)}
              />
              <div className="transcript-hint">
                {analyzing ? '⏳ AI analyzing…' : analysis ? '✅ Analysis ready' : 'Type 30+ characters to trigger AI'}
              </div>
            </div>

            <div className="call-ai-col">
              <label className="form-label">{t.call.aiAssist}</label>
              {analysis ? (
                <div className="call-ai-panel">
                  <div className="call-ai-row"><span className="call-ai-lbl">Triage</span><Badge value={analysis.triage} /></div>
                  <div className="call-ai-row">
                    <span className="call-ai-lbl">Sentiment</span>
                    <span className={`badge badge-${analysis.sentiment}`}>{analysis.sentiment}</span>
                  </div>
                  <div className="call-ai-divider" />
                  <div>
                    <div className="call-ai-lbl" style={{ marginBottom:6 }}>Summary</div>
                    <p className="call-ai-text">{analysis.summary}</p>
                  </div>
                  {analysis.action_items?.length > 0 && (
                    <div>
                      <div className="call-ai-lbl" style={{ marginBottom:6 }}>Action Items</div>
                      <ul className="action-items">
                        {analysis.action_items.slice(0,5).map((item,i) => <li key={i} style={{ fontSize:'.8rem' }}>{item}</li>)}
                      </ul>
                    </div>
                  )}
                </div>
              ) : (
                <div className="call-ai-panel call-ai-empty">
                  <div style={{ fontSize:'2.5rem', marginBottom:10 }}>🤖</div>
                  <p style={{ fontSize:'.85rem', color:'var(--gray-400)', textAlign:'center' }}>
                    Type 30+ characters to get real-time AI analysis
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Twilio-ready banner */}
      <div className="twilio-banner">
        <span className="twilio-mode-pill twilio-mode-test">📱 TEST MODE</span>
        <span className="twilio-banner-text">
          Calls via <strong>Google Voice</strong> (free). Number auto-copies to clipboard — paste in Google Voice &amp; call.
          &nbsp;AI transcript analysis is fully live.
        </span>
        <span className="twilio-upgrade-pill">
          🔌 Twilio full-call upgrade available — activate when ready
        </span>
      </div>

      {/* ── New call form + history */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">🎧 Call Center</span>
          {!callPhase && (
            <button className="btn btn-teal btn-sm" onClick={() => setShowForm(v => !v)}>
              {showForm ? `✕ ${t.c.cancel}` : t.call.newCall}
            </button>
          )}
        </div>

        {showForm && !callPhase && (
          <form className="form" onSubmit={startCall} style={{ marginBottom: 20 }}>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">{t.call.callerName} *</label>
                <input className="form-input" required placeholder="e.g. Jane Smith"
                  value={form.caller_name} onChange={e => setForm({ ...form, caller_name: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">📱 {t.call.callerName === 'Caller Name' ? 'Phone Number — opens your dialer' : t.c.phone}</label>
                <input className="form-input" placeholder="+1 555 000 0000"
                  value={form.caller_phone} onChange={e => setForm({ ...form, caller_phone: e.target.value })} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">{t.call.reason}</label>
              <input className="form-input" placeholder="e.g. Booking inquiry, support request…"
                value={form.reason} onChange={e => setForm({ ...form, reason: e.target.value })} />
            </div>
            <div className="twilio-dial-hint">
              📱 Entering a phone number will open your device dialer — you can then speak &amp; log the transcript here.
            </div>
            <button className="btn btn-teal" type="submit">{t.call.dial}</button>
          </form>
        )}

        {calls.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">📞</div>
            <p>{t.call.noHistory}</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>{t.call.callerName}</th><th>{t.call.reason}</th><th>{t.c.date}</th><th>{t.call.duration}</th><th>{t.call.triage}</th><th>{t.call.sentiment}</th>
              </tr></thead>
              <tbody>
                {calls.map(c => (
                  <tr key={c.id}>
                    <td>
                      <strong>{c.caller_name}</strong>
                      {c.caller_phone && <div style={{ fontSize:'.75rem', color:'var(--gray-600)' }}>{c.caller_phone}</div>}
                    </td>
                    <td style={{ color:'var(--gray-600)', fontSize:'.85rem' }}>{c.reason || '—'}</td>
                    <td>{new Date(c.started_at).toLocaleString()}</td>
                    <td>{c.duration != null ? fmt(c.duration) : '—'}</td>
                    <td>{c.analysis?.triage ? <Badge value={c.analysis.triage} /> : '—'}</td>
                    <td>{c.analysis?.sentiment ? <span className={`badge badge-${c.analysis.sentiment}`}>{c.analysis.sentiment}</span> : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Dashboard Tab ─────────────────────────────────────────────────────────────
function DashboardTab({ wsConnected }) {
  const { t } = useLang()
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchStats = useCallback(async () => {
    try {
      const data = await apiFetch('/stats')
      setStats(data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchStats() }, [fetchStats])
  useEffect(() => {
    const id = setInterval(fetchStats, 30000)
    return () => clearInterval(id)
  }, [fetchStats])

  if (loading) return <Spinner />

  return (
    <div>
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">{t.dash.businesses}</div>
          <div className="stat-value">{stats?.total_businesses ?? '—'}</div>
        </div>
        <div className="stat-card teal">
          <div className="stat-label">{t.dash.appointments}</div>
          <div className="stat-value">{stats?.total_appointments ?? '—'}</div>
        </div>
        <div className="stat-card urgent">
          <div className="stat-label">Urgent Open</div>
          <div className="stat-value">{stats?.urgent_open ?? '—'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">{t.dash.calls}</div>
          <div className="stat-value">{stats?.completed_today ?? '—'}</div>
        </div>
        <div className={`stat-card ${wsConnected ? 'teal' : ''}`}>
          <div className="stat-label">Live WS Clients</div>
          <div className="stat-value">{stats?.ws_connections ?? '—'}</div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">{t.dash.title}</span>
          <button className="btn btn-outline btn-sm" onClick={fetchStats}>↺ {t.c.back}</button>
        </div>
        <p style={{ color: 'var(--gray-600)', fontSize: '.9rem' }}>
          Backend API: <strong style={{ color: 'var(--teal)' }}>Online</strong>
          &nbsp;·&nbsp;
          WebSocket: <strong style={{ color: wsConnected ? 'var(--teal)' : 'var(--urgent-fg)' }}>
            {wsConnected ? t.live : t.reconnecting}
          </strong>
          &nbsp;·&nbsp;
          AI Engine: <strong style={{ color: 'var(--blue)' }}>Ready</strong>
        </p>
      </div>
    </div>
  )
}

// ── Businesses Tab ─────────────────────────────────────────────────────────────
const EMPTY_BIZ = { name: '', industry: '', email: '', phone: '', address: '', website: '', description: '', revenue: '', employees: '' }

function BusinessesTab() {
  const { t } = useLang()
  const [list, setList]         = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [success, setSuccess]   = useState('')
  const [showForm, setShowForm] = useState(false)
  const [form, setForm]         = useState(EMPTY_BIZ)
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm]   = useState(EMPTY_BIZ)

  const load = useCallback(async () => {
    setLoading(true)
    try { setList(await apiFetch('/businesses')) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(''); setSuccess('')
    try {
      await apiFetch('/businesses', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          revenue: parseFloat(form.revenue) || 0,
          employees: parseInt(form.employees) || 1,
        }),
      })
      setSuccess('Business created successfully!')
      setShowForm(false)
      setForm(EMPTY_BIZ)
      load()
    } catch (e) { setError(e.message) }
  }

  const handleEdit = (b) => {
    setEditingId(b.id)
    setShowForm(false)
    setEditForm({
      name: b.name, industry: b.industry, email: b.email,
      phone: b.phone || '', address: b.address || '', website: b.website || '',
      description: b.description || '',
      revenue: String(b.revenue || ''), employees: String(b.employees || ''),
    })
  }

  const handleEditSubmit = async (e) => {
    e.preventDefault()
    setError(''); setSuccess('')
    try {
      await apiFetch(`/businesses/${editingId}`, {
        method: 'PUT',
        body: JSON.stringify({
          name: editForm.name, industry: editForm.industry, phone: editForm.phone,
          address: editForm.address, website: editForm.website, description: editForm.description,
          revenue: parseFloat(editForm.revenue) || 0,
          employees: parseInt(editForm.employees) || 1,
        }),
      })
      setSuccess('Business updated!')
      setEditingId(null)
      load()
    } catch (e) { setError(e.message) }
  }

  const deactivate = async (id) => {
    if (!confirm('Deactivate this business?')) return
    try {
      await apiFetch(`/businesses/${id}`, { method: 'DELETE' })
      load()
    } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <Alert msg={error} type="error" />
      <Alert msg={success} type="success" />

      <div className="card">
        <div className="card-header">
          <span className="card-title">{t.biz.title} ({list.length})</span>
          <button className="btn btn-primary btn-sm" onClick={() => { setShowForm(!showForm); setEditingId(null) }}>
            {showForm ? `✕ ${t.c.cancel}` : t.biz.addNew}
          </button>
        </div>

        {showForm && (
          <form className="form" onSubmit={handleSubmit} style={{ marginBottom: 20 }}>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">{t.biz.bizName} *</label>
                <input className="form-input" required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">{t.biz.industry} *</label>
                <input className="form-input" required value={form.industry} onChange={e => setForm({ ...form, industry: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">{t.c.email} *</label>
                <input className="form-input" type="email" required value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">{t.c.phone}</label>
                <input className="form-input" value={form.phone} onChange={e => setForm({ ...form, phone: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">{t.biz.revenue}</label>
                <input className="form-input" type="number" value={form.revenue} onChange={e => setForm({ ...form, revenue: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">{t.biz.employees}</label>
                <input className="form-input" type="number" value={form.employees} onChange={e => setForm({ ...form, employees: e.target.value })} />
              </div>
            </div>
            <button className="btn btn-primary" type="submit">{t.biz.addNew}</button>
          </form>
        )}

        {loading ? <Spinner /> : list.length === 0 ? (
          <div className="empty"><div className="empty-icon">🏢</div><p>{t.biz.noData}</p></div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>{t.c.name}</th><th>{t.biz.industry}</th><th>{t.c.email}</th>
                <th>{t.biz.employees}</th><th>{t.biz.revenue}</th><th>{t.c.actions}</th>
              </tr></thead>
              <tbody>
                {list.map(b => (
                  <React.Fragment key={b.id}>
                    <tr>
                      <td><strong>{b.name}</strong></td>
                      <td>{b.industry}</td>
                      <td>{b.email}</td>
                      <td>{b.employees}</td>
                      <td>${(b.revenue || 0).toLocaleString()}</td>
                      <td>
                        <div style={{ display: 'flex', gap: 6 }}>
                          <button
                            className="btn btn-outline btn-sm"
                            onClick={() => editingId === b.id ? setEditingId(null) : handleEdit(b)}
                          >
                            {editingId === b.id ? t.c.cancel : t.c.edit}
                          </button>
                          <button className="btn btn-danger btn-sm" onClick={() => deactivate(b.id)}>
                            {t.c.delete}
                          </button>
                        </div>
                      </td>
                    </tr>
                    {editingId === b.id && (
                      <tr>
                        <td colSpan={6} style={{ background: 'var(--blue-light)', padding: 16 }}>
                          <form className="form" onSubmit={handleEditSubmit}>
                            <div className="form-row">
                              <div className="form-group">
                                <label className="form-label">{t.biz.bizName} *</label>
                                <input className="form-input" required value={editForm.name} onChange={e => setEditForm({ ...editForm, name: e.target.value })} />
                              </div>
                              <div className="form-group">
                                <label className="form-label">{t.biz.industry} *</label>
                                <input className="form-input" required value={editForm.industry} onChange={e => setEditForm({ ...editForm, industry: e.target.value })} />
                              </div>
                            </div>
                            <div className="form-row">
                              <div className="form-group">
                                <label className="form-label">{t.c.phone}</label>
                                <input className="form-input" value={editForm.phone} onChange={e => setEditForm({ ...editForm, phone: e.target.value })} />
                              </div>
                              <div className="form-group">
                                <label className="form-label">Website</label>
                                <input className="form-input" value={editForm.website} onChange={e => setEditForm({ ...editForm, website: e.target.value })} />
                              </div>
                            </div>
                            <div className="form-row">
                              <div className="form-group">
                                <label className="form-label">{t.biz.revenue}</label>
                                <input className="form-input" type="number" value={editForm.revenue} onChange={e => setEditForm({ ...editForm, revenue: e.target.value })} />
                              </div>
                              <div className="form-group">
                                <label className="form-label">{t.biz.employees}</label>
                                <input className="form-input" type="number" value={editForm.employees} onChange={e => setEditForm({ ...editForm, employees: e.target.value })} />
                              </div>
                            </div>
                            <div style={{ display: 'flex', gap: 8 }}>
                              <button className="btn btn-primary" type="submit">{t.c.save}</button>
                              <button className="btn btn-outline" type="button" onClick={() => setEditingId(null)}>{t.c.cancel}</button>
                            </div>
                          </form>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Appointments Tab ──────────────────────────────────────────────────────────
const EMPTY_APPT = { business_id: '', client_name: '', client_email: '', client_phone: '', service: '', notes: '', scheduled_at: '', duration_mins: '60' }

function AppointmentsTab() {
  const { t } = useLang()
  const [list, setList]           = useState([])
  const [businesses, setBusinesses] = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')
  const [success, setSuccess]     = useState('')
  const [showForm, setShowForm]   = useState(false)
  const [form, setForm]           = useState(EMPTY_APPT)
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm]   = useState({})
  const [filterStatus, setFilterStatus] = useState('')
  const [filterSearch, setFilterSearch] = useState('')
  const [showQuickBiz, setShowQuickBiz] = useState(false)
  const [quickBizForm, setQuickBizForm] = useState({ name: '', email: '', industry: '' })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [appts, bizs] = await Promise.all([apiFetch('/appointments'), apiFetch('/businesses')])
      setList(appts); setBusinesses(bizs)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const filtered = list.filter(a => {
    if (filterStatus && a.status !== filterStatus) return false
    if (filterSearch) {
      const q = filterSearch.toLowerCase()
      if (!a.client_name.toLowerCase().includes(q) && !a.service.toLowerCase().includes(q)) return false
    }
    return true
  })

  const handleSubmit = async (e) => {
    e.preventDefault(); setError(''); setSuccess('')

    // If Quick Add panel is open with data, auto-create the business first
    let resolvedBizId = parseInt(form.business_id)
    if (showQuickBiz) {
      if (!quickBizForm.name.trim()) {
        setError('Please enter a Business Name.')
        return
      }
      if (!quickBizForm.industry.trim()) {
        setError('Please enter an Industry.')
        return
      }
      if (!quickBizForm.email.trim()) {
        setError('Please enter a Business Email.')
        return
      }
      try {
        const newBiz = await apiFetch('/businesses', {
          method: 'POST',
          body: JSON.stringify({ ...quickBizForm, revenue: 0, employees: 1 }),
        })
        setBusinesses(prev => [...prev, newBiz])
        setShowQuickBiz(false)
        setQuickBizForm({ name: '', email: '', industry: '' })
        resolvedBizId = newBiz.id
      } catch (e) { setError(e.message); return }
    }

    if (!resolvedBizId || isNaN(resolvedBizId)) {
      setError('Please select or add a business before booking.')
      return
    }
    try {
      await apiFetch('/appointments', {
        method: 'POST',
        body: JSON.stringify({
          ...form,
          business_id: resolvedBizId,
          duration_mins: parseInt(form.duration_mins) || 60,
        }),
      })
      setSuccess('Appointment booked!')
      setShowForm(false)
      setForm(EMPTY_APPT)
      load()
    } catch (e) { setError(e.message) }
  }

  const handleQuickBiz = async () => {
    if (!quickBizForm.name.trim() || !quickBizForm.industry.trim() || !quickBizForm.email.trim()) {
      setError('Please fill in business name, industry, and email.')
      return
    }
    setError('')
    try {
      const newBiz = await apiFetch('/businesses', {
        method: 'POST',
        body: JSON.stringify({ ...quickBizForm, revenue: 0, employees: 1 }),
      })
      setBusinesses(prev => [...prev, newBiz])
      setForm(f => ({ ...f, business_id: String(newBiz.id) }))
      setShowQuickBiz(false)
      setQuickBizForm({ name: '', email: '', industry: '' })
      setSuccess(`✅ "${newBiz.name}" created — now fill the appointment details and click Book.`)
    } catch (e) { setError(e.message) }
  }

  const handleEdit = (a) => {
    setEditingId(a.id)
    setShowForm(false)
    const dt = new Date(a.scheduled_at)
    const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
    setEditForm({
      client_name: a.client_name, client_email: a.client_email || '',
      client_phone: a.client_phone || '', service: a.service,
      notes: a.notes || '', scheduled_at: local,
      duration_mins: String(a.duration_mins || 60),
    })
  }

  const handleEditSubmit = async (e) => {
    e.preventDefault(); setError(''); setSuccess('')
    try {
      await apiFetch(`/appointments/${editingId}`, {
        method: 'PUT',
        body: JSON.stringify({
          ...editForm,
          duration_mins: parseInt(editForm.duration_mins) || 60,
        }),
      })
      setSuccess('Appointment updated!')
      setEditingId(null)
      load()
    } catch (e) { setError(e.message) }
  }

  const updateStatus = async (id, status) => {
    try {
      await apiFetch(`/appointments/${id}`, { method: 'PUT', body: JSON.stringify({ status }) })
      load()
    } catch (e) { setError(e.message) }
  }

  const cancel = async (id) => {
    if (!confirm('Cancel this appointment?')) return
    try { await apiFetch(`/appointments/${id}`, { method: 'DELETE' }); load() }
    catch (e) { setError(e.message) }
  }

  const STATUS_CLASSES = {
    scheduled: 'badge-scheduled', confirmed: 'badge-confirmed',
    completed: 'badge-completed', cancelled: 'badge-cancelled',
    pending_approval: 'badge-pending',
  }

  return (
    <div>
      <Alert msg={error} type="error" />
      <Alert msg={success} type="success" />

      <div className="card">
        <div className="card-header">
          <span className="card-title">
            {t.appt.title} ({filtered.length}{filtered.length !== list.length ? `/${list.length}` : ''})
          </span>
          <button className="btn btn-primary btn-sm" onClick={() => { setShowForm(v => { if (v) { setShowQuickBiz(false) } return !v }); setEditingId(null) }}>
            {showForm ? `✕ ${t.c.cancel}` : t.appt.addNew}
          </button>
        </div>

        {/* Filter bar */}
        <div className="filter-bar">
          <input
            className="form-input"
            style={{ flex: 1, minWidth: 180 }}
            placeholder={t.c.search}
            value={filterSearch}
            onChange={e => setFilterSearch(e.target.value)}
          />
          <select
            className="form-select"
            style={{ width: 160 }}
            value={filterStatus}
            onChange={e => setFilterStatus(e.target.value)}
          >
            <option value="">{t.c.all}</option>
            <option value="pending_approval">⏳ Pending Approval</option>
            <option value="scheduled">{t.appt.scheduled}</option>
            <option value="confirmed">{t.appt.confirmed}</option>
            <option value="completed">{t.appt.completed}</option>
            <option value="cancelled">{t.c.cancel}</option>
          </select>
          {(filterStatus || filterSearch) && (
            <button className="btn btn-outline btn-sm" onClick={() => { setFilterStatus(''); setFilterSearch('') }}>
              ✕ {t.c.cancel}
            </button>
          )}
        </div>

        {showForm && (
          <form className="form" onSubmit={handleSubmit} style={{ marginBottom: 20 }}>
            <div className="form-group">
              <div className="qbiz-label-row">
                <label className="form-label">{t.appt.business} *</label>
                <button type="button" className="btn btn-outline btn-sm qbiz-toggle"
                  onClick={() => { setShowQuickBiz(v => !v); setError('') }}>
                  {showQuickBiz ? `✕ ${t.c.cancel}` : t.appt.quickAdd}
                </button>
              </div>

              {!showQuickBiz ? (
                <select className="form-select" required value={form.business_id}
                  onChange={e => setForm({ ...form, business_id: e.target.value })}>
                  <option value="">{t.c.selectBiz}</option>
                  {businesses.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              ) : (
                <div className="quick-biz-panel">
                  <p className="quick-biz-title">{t.appt.quickAdd}</p>
                  <div className="form-row">
                    <div className="form-group">
                      <label className="form-label">{t.biz.bizName} *</label>
                      <input className="form-input" placeholder="e.g. Doctor Shaikh Clinic"
                        value={quickBizForm.name} onChange={e => setQuickBizForm({ ...quickBizForm, name: e.target.value })} />
                    </div>
                    <div className="form-group">
                      <label className="form-label">{t.biz.industry} *</label>
                      <input className="form-input" placeholder="e.g. Healthcare"
                        value={quickBizForm.industry} onChange={e => setQuickBizForm({ ...quickBizForm, industry: e.target.value })} />
                    </div>
                  </div>
                  <div className="form-group">
                    <label className="form-label">{t.c.email} *</label>
                    <input className="form-input" type="email" placeholder="clinic@example.com"
                      value={quickBizForm.email} onChange={e => setQuickBizForm({ ...quickBizForm, email: e.target.value })} />
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button type="button" className="btn btn-primary btn-sm" onClick={handleQuickBiz}>
                      ✔ {t.c.confirm}
                    </button>
                    <button type="button" className="btn btn-outline btn-sm" onClick={() => setShowQuickBiz(false)}>
                      {t.c.cancel}
                    </button>
                  </div>
                </div>
              )}
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">{t.appt.custName} *</label>
                <input className="form-input" required value={form.client_name} onChange={e => setForm({ ...form, client_name: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">{t.appt.service} *</label>
                <input className="form-input" required value={form.service} onChange={e => setForm({ ...form, service: e.target.value })} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label">{t.c.date} &amp; {t.c.time} *</label>
                <input className="form-input" type="datetime-local" required value={form.scheduled_at} onChange={e => setForm({ ...form, scheduled_at: e.target.value })} />
              </div>
              <div className="form-group">
                <label className="form-label">Duration (mins)</label>
                <input className="form-input" type="number" value={form.duration_mins} onChange={e => setForm({ ...form, duration_mins: e.target.value })} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">{t.c.notes}</label>
              <textarea className="form-textarea" value={form.notes} onChange={e => setForm({ ...form, notes: e.target.value })} />
            </div>
            <button className="btn btn-primary" type="submit">
              {showQuickBiz ? '📋 Create Business & Book' : t.appt.addNew}
            </button>
          </form>
        )}

        {loading ? <Spinner /> : filtered.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">📅</div>
            <p>{t.appt.noData}</p>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr>
                <th>{t.appt.custName}</th><th>{t.appt.service}</th><th>{t.c.date}</th>
                <th>{t.c.status}</th><th>Triage</th><th>{t.c.actions}</th>
              </tr></thead>
              <tbody>
                {filtered.map(a => (
                  <React.Fragment key={a.id}>
                    <tr>
                      <td><strong>{a.client_name}</strong></td>
                      <td>{a.service}</td>
                      <td>{new Date(a.scheduled_at).toLocaleString()}</td>
                      <td><span className={`badge ${STATUS_CLASSES[a.status] || ''}`}>{a.status}</span></td>
                      <td>{a.triage_result ? <Badge value={a.triage_result} /> : '—'}</td>
                      <td>
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                          {a.status === 'pending_approval' && (
                            <>
                              <button
                                className="btn btn-sm"
                                style={{ background: '#DCFCE7', color: '#166534', border: 'none', fontWeight: 700 }}
                                onClick={() => updateStatus(a.id, 'confirmed').then(() => apiFetch(`/appointments/${a.id}/send-confirmation`, { method: 'POST' }).catch(() => {}))}
                              >
                                ✅ Approve
                              </button>
                              <button
                                className="btn btn-sm"
                                style={{ background: '#FEF3C7', color: '#92400E', border: 'none' }}
                                onClick={() => apiFetch(`/appointments/${a.id}/notify-staff`, { method: 'POST' }).then(() => setSuccess('Staff notified!')).catch(e => setError(e.message))}
                              >
                                📧 Notify Staff
                              </button>
                            </>
                          )}
                          {a.status === 'scheduled' && (
                            <button
                              className="btn btn-sm"
                              style={{ background: '#EDE9FE', color: '#7C3AED', border: 'none' }}
                              onClick={() => updateStatus(a.id, 'confirmed')}
                            >
                              Confirm
                            </button>
                          )}
                          {(a.status === 'scheduled' || a.status === 'confirmed') && (
                            <button className="btn btn-teal btn-sm" onClick={() => updateStatus(a.id, 'completed')}>
                              Complete
                            </button>
                          )}
                          {a.status !== 'cancelled' && a.status !== 'completed' && (
                            <button
                              className="btn btn-outline btn-sm"
                              onClick={() => editingId === a.id ? setEditingId(null) : handleEdit(a)}
                            >
                              {editingId === a.id ? 'Close' : 'Edit'}
                            </button>
                          )}
                          {a.status !== 'cancelled' && (
                            <button className="btn btn-danger btn-sm" onClick={() => cancel(a.id)}>Cancel</button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {editingId === a.id && (
                      <tr>
                        <td colSpan={6} style={{ background: 'var(--blue-light)', padding: 16 }}>
                          <form className="form" onSubmit={handleEditSubmit}>
                            <div className="form-row">
                              <div className="form-group">
                                <label className="form-label">Client Name *</label>
                                <input className="form-input" required value={editForm.client_name} onChange={e => setEditForm({ ...editForm, client_name: e.target.value })} />
                              </div>
                              <div className="form-group">
                                <label className="form-label">Service *</label>
                                <input className="form-input" required value={editForm.service} onChange={e => setEditForm({ ...editForm, service: e.target.value })} />
                              </div>
                            </div>
                            <div className="form-row">
                              <div className="form-group">
                                <label className="form-label">Scheduled At *</label>
                                <input className="form-input" type="datetime-local" required value={editForm.scheduled_at} onChange={e => setEditForm({ ...editForm, scheduled_at: e.target.value })} />
                              </div>
                              <div className="form-group">
                                <label className="form-label">Duration (mins)</label>
                                <input className="form-input" type="number" value={editForm.duration_mins} onChange={e => setEditForm({ ...editForm, duration_mins: e.target.value })} />
                              </div>
                            </div>
                            <div className="form-group">
                              <label className="form-label">Notes</label>
                              <textarea className="form-textarea" value={editForm.notes} onChange={e => setEditForm({ ...editForm, notes: e.target.value })} />
                            </div>
                            <div style={{ display: 'flex', gap: 8 }}>
                              <button className="btn btn-primary" type="submit">Save Changes</button>
                              <button className="btn btn-outline" type="button" onClick={() => setEditingId(null)}>Cancel</button>
                            </div>
                          </form>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Approval Queue Tab ────────────────────────────────────────────────────────
function ApprovalQueueTab() {
  const [list, setList]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]   = useState('')
  const [success, setSuccess] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const appts = await apiFetch('/appointments?status=pending_approval&limit=100')
      setList(appts)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const approve = async (id) => {
    setError(''); setSuccess('')
    try {
      await apiFetch(`/appointments/${id}`, { method: 'PUT', body: JSON.stringify({ status: 'confirmed' }) })
      await apiFetch(`/appointments/${id}/send-confirmation`, { method: 'POST' }).catch(() => {})
      setSuccess('Appointment approved and client notified!')
      load()
    } catch (e) { setError(e.message) }
  }

  const reject = async (id) => {
    if (!confirm('Decline this appointment?')) return
    setError(''); setSuccess('')
    try {
      await apiFetch(`/appointments/${id}`, { method: 'DELETE' })
      setSuccess('Appointment declined.')
      load()
    } catch (e) { setError(e.message) }
  }

  const notifyStaff = async (id) => {
    setError(''); setSuccess('')
    try {
      const r = await apiFetch(`/appointments/${id}/notify-staff`, { method: 'POST' })
      setSuccess(r.sent ? `Staff notified at ${r.staff_email}` : 'Staff email not configured yet.')
    } catch (e) { setError(e.message) }
  }

  return (
    <div>
      <Alert msg={error} type="error" />
      <Alert msg={success} type="success" />
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            📋 Approval Queue
            {list.length > 0 && <span className="approval-badge">{list.length}</span>}
          </span>
          <button className="btn btn-outline btn-sm" onClick={load}>↻ Refresh</button>
        </div>

        {loading ? <Spinner /> : list.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">✅</div>
            <p>No appointments waiting for approval.</p>
          </div>
        ) : (
          <div className="approval-list">
            {list.map(a => (
              <div key={a.id} className="approval-card">
                <div className="approval-card-header">
                  <div>
                    <strong className="approval-client">{a.client_name}</strong>
                    <span className="approval-service">{a.service}</span>
                  </div>
                  <span className="badge badge-pending">Pending Approval</span>
                </div>
                <div className="approval-meta">
                  <span>📅 {new Date(a.scheduled_at).toLocaleString()}</span>
                  {a.client_phone && <span>📞 {a.client_phone}</span>}
                  {a.client_email && <span>✉️ {a.client_email}</span>}
                </div>
                {a.notes && (
                  <div className="approval-notes">
                    <em>{a.notes.length > 150 ? a.notes.slice(0, 150) + '…' : a.notes}</em>
                  </div>
                )}
                <div className="approval-actions">
                  <button className="btn btn-sm approval-approve" onClick={() => approve(a.id)}>
                    ✅ Approve &amp; Notify Client
                  </button>
                  <button className="btn btn-sm approval-staff" onClick={() => notifyStaff(a.id)}>
                    📧 Email Staff
                  </button>
                  <button className="btn btn-danger btn-sm" onClick={() => reject(a.id)}>
                    ✕ Decline
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ── AI Analyzer Tab ───────────────────────────────────────────────────────────
function AIAnalyzerTab() {
  const { t } = useLang()
  const [transcript, setTranscript] = useState('')
  const [appointmentId, setAppointmentId] = useState('')
  const [result, setResult]   = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  const analyze = async (e) => {
    e.preventDefault(); setError(''); setResult(null); setLoading(true)
    try {
      const data = await apiFetch('/ai/summarize', {
        method: 'POST',
        body: JSON.stringify({
          transcript,
          appointment_id: appointmentId ? parseInt(appointmentId) : undefined,
        }),
      })
      setResult(data)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <div>
      <Alert msg={error} type="error" />
      <div className="card">
        <div className="card-header">
          <span className="card-title">🤖 {t.ai.title}</span>
        </div>
        <form className="form" onSubmit={analyze}>
          <div className="form-group">
            <label className="form-label">{t.call.transcript} *</label>
            <textarea
              className="form-textarea"
              style={{ minHeight: 160 }}
              required
              placeholder={t.ai.placeholder}
              value={transcript}
              onChange={e => setTranscript(e.target.value)}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Appointment ID (optional)</label>
            <input
              className="form-input"
              type="number"
              placeholder="e.g. 42"
              value={appointmentId}
              onChange={e => setAppointmentId(e.target.value)}
            />
          </div>
          <button className="btn btn-teal" type="submit" disabled={loading}>
            {loading ? t.ai.analyzing : t.ai.analyze}
          </button>
        </form>

        {result && (
          <div className="ai-result">
            <h4>{t.ai.summary}</h4>
            <p style={{ fontSize: '.8rem', marginBottom: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
              <span>{t.call.triage}:</span><Badge value={result.triage} />
              <span style={{ marginLeft: 12 }}>{t.call.sentiment}:</span>
              <span className={`badge badge-${result.sentiment}`}>{result.sentiment}</span>
            </p>
            <p className="ai-summary-text">{result.summary}</p>
            {result.action_items?.length > 0 && (
              <>
                <p style={{ fontWeight: 600, fontSize: '.85rem', marginBottom: 6, color: 'var(--teal)' }}>
                  {t.ai.actionItems}
                </p>
                <ul className="action-items">
                  {result.action_items.map((item, i) => <li key={i}>{item}</li>)}
                </ul>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── Notification Toast ────────────────────────────────────────────────────────
function NotificationsPanel({ notifications }) {
  if (notifications.length === 0) return null
  return (
    <div className="notifications">
      {notifications.slice(-5).map((n, i) => (
        <div key={i} className={`notification ${n.type}`}>
          <div className="notification-type">{n.type.replace(/_/g, ' ')}</div>
          <div className="notification-msg">{n.message}</div>
        </div>
      ))}
    </div>
  )
}

// ── Auth Context ──────────────────────────────────────────────────────────────
const AuthCtx = React.createContext(null)

function AuthProvider({ children }) {
  const [user, setUser]   = useState(() => {
    try { return JSON.parse(localStorage.getItem('ez_user') || 'null') } catch { return null }
  })
  const [token, setToken] = useState(() => localStorage.getItem('ez_token') || '')

  const login  = (userData, accessToken) => {
    setUser(userData); setToken(accessToken)
    localStorage.setItem('ez_user',  JSON.stringify(userData))
    localStorage.setItem('ez_token', accessToken)
  }
  const logout = () => {
    setUser(null); setToken('')
    localStorage.removeItem('ez_user'); localStorage.removeItem('ez_token')
  }
  return <AuthCtx.Provider value={{ user, token, login, logout }}>{children}</AuthCtx.Provider>
}

function useAuth() { return React.useContext(AuthCtx) }

function authFetch(path, token, options = {}) {
  return fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers },
    ...options,
  }).then(async res => {
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      const detail = err.detail
      throw new Error(Array.isArray(detail) ? detail.map(d => d.msg || String(d)).join(', ') : (typeof detail === 'string' ? detail : 'Request failed'))
    }
    return res.json()
  })
}

// ── Data Entry AI Tab ─────────────────────────────────────────────────────────
function DataEntryTab() {
  const [panel, setPanel]         = useState('upload')   // upload | jobs | patients | equipment | bookkeeping | audit
  const [businesses, setBusinesses] = useState([])
  const [stats, setStats]         = useState(null)
  const [jobs, setJobs]           = useState([])
  const [documents, setDocuments] = useState([])
  const [patients, setPatients]   = useState([])
  const [equipment, setEquipment] = useState([])
  const [bookkeeping, setBookkeeping] = useState([])
  const [auditLogs, setAuditLogs] = useState([])
  const [loading, setLoading]     = useState(false)
  const [error, setError]         = useState('')
  const [success, setSuccess]     = useState('')

  // Upload state
  const [uploadFile, setUploadFile]     = useState(null)
  const [uploadBizId, setUploadBizId]   = useState('')
  const [workflowType, setWorkflowType] = useState('medical')
  const [uploading, setUploading]       = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [dragOver, setDragOver]         = useState(false)

  // Patient form
  const [showPatForm, setShowPatForm] = useState(false)
  const [patForm, setPatForm] = useState({ business_id:'', first_name:'', last_name:'', date_of_birth:'', phone:'', email:'', address:'', city:'', state:'', zip_code:'', preferred_language:'en' })

  // Equipment form
  const [showEqForm, setShowEqForm] = useState(false)
  const [eqForm, setEqForm] = useState({ business_id:'', patient_id:'', equipment_type:'', diagnosis_or_reason:'', prescribing_provider:'', hcpcs_codes:'', insurance_required:true })

  // Bookkeeping form
  const [showBkForm, setShowBkForm] = useState(false)
  const [bkForm, setBkForm] = useState({ business_id:'', entry_type:'invoice', vendor_or_customer:'', transaction_date:'', amount:'', category:'', memo:'', tax_flag:false })

  const { user } = useAuth()

  const loadAll = async () => {
    setLoading(true)
    try {
      const [b, s, j, p] = await Promise.all([
        apiFetch('/businesses'),
        apiFetch('/data-entry/stats'),
        apiFetch('/data-entry/jobs?limit=50'),
        apiFetch('/patients?limit=50'),
      ])
      setBusinesses(b); setStats(s); setJobs(j); setPatients(p)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const loadPanel = async (p) => {
    setPanel(p); setError('')
    if (p === 'bookkeeping') {
      try { setBookkeeping(await apiFetch('/bookkeeping?limit=50')) } catch (e) { setError(e.message) }
    } else if (p === 'equipment') {
      try { setEquipment(await apiFetch('/equipment-requests?limit=50')) } catch (e) { setError(e.message) }
    } else if (p === 'audit') {
      try { setAuditLogs(await apiFetch('/audit-logs?limit=50')) } catch (e) { setError(e.message) }
    }
  }

  useEffect(() => { loadAll() }, [])

  // ── Upload with progress
  const handleUpload = async (e) => {
    e.preventDefault()
    if (!uploadFile) return setError('Please select a document first')
    if (!uploadBizId) return setError('Please select a business')
    setUploading(true); setError(''); setUploadResult(null); setSuccess('')
    try {
      const token = localStorage.getItem('ez_token')
      const form = new FormData()
      form.append('business_id', uploadBizId)
      form.append('workflow_type', workflowType)
      form.append('file', uploadFile)
      const res = await fetch(`${API}/data-entry/upload`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Upload failed')
      setUploadResult(data)
      setSuccess('Document processed! Review the extraction below and check the Jobs Queue.')
      loadAll()
    } catch (e) { setError(e.message) }
    finally { setUploading(false) }
  }

  const handleDrop = (e) => {
    e.preventDefault(); setDragOver(false)
    const f = e.dataTransfer.files[0]
    if (f) setUploadFile(f)
  }

  // ── Job actions
  const approveJob = async (id) => {
    try {
      await apiFetch(`/data-entry/jobs/${id}/approve`, { method:'POST', body: JSON.stringify({ admin_notes: 'Approved by admin' }) })
      setSuccess(`Job #${id} approved!`); loadAll()
    } catch (e) { setError(e.message) }
  }
  const declineJob = async (id) => {
    const reason = prompt('Reason for decline?') || 'Needs revision'
    try {
      await apiFetch(`/data-entry/jobs/${id}/decline`, { method:'POST', body: JSON.stringify({ reason }) })
      setSuccess(`Job #${id} declined.`); loadAll()
    } catch (e) { setError(e.message) }
  }

  // ── Patient
  const savePatient = async (e) => {
    e.preventDefault(); setError('')
    try {
      await apiFetch('/patients', { method:'POST', body: JSON.stringify({ ...patForm, business_id: Number(patForm.business_id) }) })
      setSuccess('Patient created!'); setShowPatForm(false)
      setPatients(await apiFetch('/patients?limit=50'))
    } catch (e) { setError(e.message) }
  }

  // ── Equipment
  const saveEquipment = async (e) => {
    e.preventDefault(); setError('')
    try {
      await apiFetch('/equipment-requests', { method:'POST', body: JSON.stringify({ ...eqForm, business_id: Number(eqForm.business_id), patient_id: eqForm.patient_id ? Number(eqForm.patient_id) : null }) })
      setSuccess('Equipment request created!'); setShowEqForm(false)
      setEquipment(await apiFetch('/equipment-requests?limit=50'))
    } catch (e) { setError(e.message) }
  }

  // ── Bookkeeping
  const saveBookkeeping = async (e) => {
    e.preventDefault(); setError('')
    try {
      await apiFetch('/bookkeeping', { method:'POST', body: JSON.stringify({ ...bkForm, business_id: Number(bkForm.business_id), amount: Number(bkForm.amount) }) })
      setSuccess('Bookkeeping entry created (draft — pending approval)!'); setShowBkForm(false)
      setBookkeeping(await apiFetch('/bookkeeping?limit=50'))
    } catch (e) { setError(e.message) }
  }
  const approveBk = async (id) => {
    try { await apiFetch(`/bookkeeping/${id}/approve`, { method:'POST' }); setSuccess('Entry approved!'); setBookkeeping(await apiFetch('/bookkeeping?limit=50')) } catch (e) { setError(e.message) }
  }

  // ── Export
  const exportExcel = async (type) => {
    if (!uploadBizId) return setError('Select a business first')
    try {
      const token = localStorage.getItem('ez_token')
      const res = await fetch(`${API}/data-entry/export/${type}-excel?business_id=${uploadBizId}`, {
        method:'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail || 'Export failed') }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url
      a.download = `${type}_export.xlsx`; document.body.appendChild(a); a.click()
      URL.revokeObjectURL(url); a.remove()
    } catch (e) { setError(e.message) }
  }

  const STATUS_BADGE = {
    'pending_admin_approval': '#f59e0b',
    'approved_ready_to_post': '#22c55e',
    'declined_needs_revision': '#ef4444',
    'draft': '#64748b',
    'posted': '#3b82f6',
  }

  const PANEL_TABS = [
    { id:'upload',      label:'📤 Upload & Extract' },
    { id:'jobs',        label:'📋 Approval Queue' },
    { id:'patients',    label:'👤 Patients' },
    { id:'equipment',   label:'🦽 Equipment' },
    { id:'bookkeeping', label:'📒 Bookkeeping' },
    { id:'audit',       label:'🔐 Audit Log' },
  ]

  return (
    <div>
      {/* Module header */}
      <div style={{ background:'linear-gradient(135deg,#0f172a,#1e293b)', borderRadius:12, padding:'20px 24px', marginBottom:20 }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', flexWrap:'wrap', gap:12 }}>
          <div>
            <div style={{ fontSize:'1.3rem', fontWeight:700, color:'#f1f5f9' }}>🤖 Data Entry AI Module</div>
            <div style={{ color:'#94a3b8', fontSize:'.85rem', marginTop:4 }}>
              Document OCR • Medical Data Extraction • Insurance Verification • Excel Export • Bookkeeping
            </div>
          </div>
          <div style={{ display:'flex', gap:8, flexWrap:'wrap' }}>
            <select className="input" style={{ width:'auto', fontSize:'.8rem', padding:'5px 10px' }} value={uploadBizId} onChange={e => setUploadBizId(e.target.value)}>
              <option value="">Select Business</option>
              {businesses.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
            <button className="btn btn-outline" style={{ fontSize:'.75rem', padding:'5px 10px' }} onClick={() => exportExcel('patient')}>⬇ Patient Excel</button>
            <button className="btn btn-outline" style={{ fontSize:'.75rem', padding:'5px 10px' }} onClick={() => exportExcel('bookkeeping')}>⬇ Bookkeeping Excel</button>
          </div>
        </div>

        {/* Stats row */}
        {stats && (
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(130px, 1fr))', gap:10, marginTop:16 }}>
            {[
              ['📄 Documents',   stats.total_documents,         '#3b82f6'],
              ['⏳ Pending',      stats.pending_jobs,            '#f59e0b'],
              ['✅ Approved',     stats.approved_jobs,           '#22c55e'],
              ['❌ Declined',     stats.declined_jobs,           '#ef4444'],
              ['👤 Patients',     stats.total_patients,          '#8b5cf6'],
              ['🦽 Equipment',    stats.total_equipment_requests,'#14b8a6'],
              ['📒 Bookkeeping',  stats.approved_bookkeeping,    '#f97316'],
            ].map(([label, val, color]) => (
              <div key={label} style={{ background:'rgba(255,255,255,.05)', borderRadius:8, padding:'10px 12px', borderLeft:`3px solid ${color}` }}>
                <div style={{ fontSize:'.7rem', color:'#94a3b8' }}>{label}</div>
                <div style={{ fontSize:'1.4rem', fontWeight:700, color:'#f1f5f9' }}>{val ?? 0}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <Alert msg={error} type="error" />
      {success && <div className="alert alert-success" style={{ background:'#14532d', border:'1px solid #16a34a', color:'#86efac' }}>{success}</div>}

      {/* Sub-tabs */}
      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
        {PANEL_TABS.map(t => (
          <button key={t.id} className={`tab-btn ${panel===t.id?'active':''}`}
            style={{ fontSize:'.8rem', padding:'6px 12px' }}
            onClick={() => loadPanel(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Upload & Extract ── */}
      {panel === 'upload' && (
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
          <div className="card">
            <h3 style={{ marginBottom:12 }}>📤 Upload Document</h3>
            <p style={{ color:'#94a3b8', fontSize:'.82rem', marginBottom:12 }}>
              Supports: PDF, Scanned PDF, Images (JPG/PNG), Word (.docx), Excel (.xlsx), CSV • Max {import.meta.env.VITE_MAX_UPLOAD_MB || 25}MB
            </p>

            {/* Drag & Drop zone */}
            <div
              onDragOver={e => { e.preventDefault(); setDragOver(true) }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => document.getElementById('de-file-input').click()}
              style={{
                border: `2px dashed ${dragOver ? '#3b82f6' : '#334155'}`,
                borderRadius:10, padding:'30px 20px', textAlign:'center',
                cursor:'pointer', marginBottom:12, transition:'all .2s',
                background: dragOver ? 'rgba(59,130,246,.05)' : 'transparent',
              }}
            >
              <input id="de-file-input" type="file" hidden
                accept=".pdf,.docx,.doc,.xlsx,.xls,.csv,.png,.jpg,.jpeg,.heic,.tif,.tiff"
                onChange={e => setUploadFile(e.target.files[0])} />
              <div style={{ fontSize:'2rem', marginBottom:6 }}>📁</div>
              <div style={{ color:'#94a3b8', fontSize:'.82rem' }}>
                {uploadFile ? (
                  <><strong style={{ color:'#60a5fa' }}>{uploadFile.name}</strong><br />{(uploadFile.size/1024).toFixed(0)} KB</>
                ) : 'Drag & drop or click to browse'}
              </div>
            </div>

            <form onSubmit={handleUpload} style={{ display:'grid', gap:10 }}>
              <select className="input" value={workflowType} onChange={e => setWorkflowType(e.target.value)} required>
                <option value="medical">🏥 Medical Patient / Insurance</option>
                <option value="bookkeeping">📒 Bookkeeping / Invoice / Receipt</option>
                <option value="insurance">🔒 Insurance Card Only</option>
                <option value="equipment">🦽 Equipment Request Form</option>
              </select>
              <button type="submit" className="btn btn-primary" disabled={uploading || !uploadFile || !uploadBizId}>
                {uploading ? '🔄 Processing with Commander AI…' : '🚀 Process Document'}
              </button>
            </form>

            <div style={{ marginTop:14, padding:10, background:'rgba(251,191,36,.08)', border:'1px solid rgba(251,191,36,.3)', borderRadius:8, fontSize:'.75rem', color:'#fbbf24' }}>
              ⚠️ <strong>HIPAA Notice:</strong> No medical, insurance, or bookkeeping data is posted to production without admin approval.
            </div>
          </div>

          {/* Upload Result */}
          <div className="card" style={{ overflow:'auto' }}>
            <h3 style={{ marginBottom:12 }}>🧠 Commander AI Extraction</h3>
            {!uploadResult && <p style={{ color:'#64748b', fontSize:'.85rem' }}>Upload a document to see AI extraction results here.</p>}
            {uploadResult && (() => {
              const r = uploadResult.commander_result || {}
              const ext = r.extraction || {}
              const fields = ext.fields || ext.entry || {}
              const verify = r.verification || {}
              const recs = r.commander_recommendations || []
              return (
                <div style={{ fontSize:'.8rem' }}>
                  {/* Document info */}
                  <div style={{ display:'flex', gap:8, marginBottom:10, flexWrap:'wrap' }}>
                    <span style={{ background:'#1e293b', padding:'3px 10px', borderRadius:12, color:'#94a3b8' }}>
                      📄 {uploadResult.document_type?.replace(/_/g,' ')}
                    </span>
                    <span style={{ background: uploadResult.confidence_score >= .7 ? '#14532d' : '#78350f', color:'#fff', padding:'3px 10px', borderRadius:12 }}>
                      Confidence: {((uploadResult.confidence_score || 0)*100).toFixed(0)}%
                    </span>
                    <span style={{ background:'#1e40af', color:'#fff', padding:'3px 10px', borderRadius:12 }}>
                      Job #{uploadResult.job_id}
                    </span>
                  </div>

                  {/* Extracted fields */}
                  {Object.keys(fields).length > 0 && (
                    <div style={{ marginBottom:10 }}>
                      <div style={{ fontWeight:600, color:'#60a5fa', marginBottom:6 }}>Extracted Fields</div>
                      {Object.entries(fields).map(([k, v]) => v ? (
                        <div key={k} style={{ display:'flex', gap:8, padding:'3px 0', borderBottom:'1px solid #1e293b' }}>
                          <span style={{ color:'#64748b', minWidth:160 }}>{k.replace(/_/g,' ')}</span>
                          <span style={{ color:'#e2e8f0', flex:1, wordBreak:'break-all' }}>{String(v)}</span>
                        </div>
                      ) : null)}
                    </div>
                  )}

                  {/* Missing fields */}
                  {verify.missing_required?.length > 0 && (
                    <div style={{ background:'rgba(239,68,68,.1)', border:'1px solid rgba(239,68,68,.3)', borderRadius:8, padding:10, marginBottom:10 }}>
                      <div style={{ color:'#f87171', fontWeight:600, marginBottom:4 }}>⚠ Missing Required Fields</div>
                      {verify.missing_required.map((f, i) => <div key={i} style={{ color:'#fca5a5', fontSize:'.75rem' }}>• {f.replace(/_/g,' ')}</div>)}
                    </div>
                  )}

                  {/* Recommendations */}
                  {recs.length > 0 && (
                    <div style={{ background:'rgba(16,185,129,.08)', border:'1px solid rgba(16,185,129,.2)', borderRadius:8, padding:10 }}>
                      <div style={{ color:'#34d399', fontWeight:600, marginBottom:4 }}>🧠 Commander Recommendations</div>
                      {recs.map((r, i) => <div key={i} style={{ color:'#6ee7b7', fontSize:'.75rem', marginBottom:2 }}>• {r}</div>)}
                    </div>
                  )}
                </div>
              )
            })()}
          </div>
        </div>
      )}

      {/* ── Approval Queue ── */}
      {panel === 'jobs' && (
        <div className="card">
          <div className="card-header">
            <h3>📋 Admin Approval Queue</h3>
            <button className="btn btn-outline btn-sm" onClick={loadAll}>↻ Refresh</button>
          </div>
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Type</th><th>Status</th><th>Missing Fields</th><th>Errors</th><th>Complete %</th><th>Actions</th></tr></thead>
                <tbody>
                  {jobs.length === 0 && <tr><td colSpan={7} style={{ textAlign:'center', color:'#64748b' }}>No jobs yet. Upload a document to get started.</td></tr>}
                  {jobs.map(j => {
                    let missing = [], errors = []
                    try { missing = JSON.parse(j.missing_fields || '[]') } catch {}
                    try { errors = JSON.parse(j.validation_errors || '[]') } catch {}
                    return (
                      <tr key={j.id}>
                        <td>#{j.id}</td>
                        <td style={{ fontSize:'.8rem' }}>{j.job_type}</td>
                        <td>
                          <span style={{ background: STATUS_BADGE[j.status] || '#64748b', color:'#fff', padding:'2px 8px', borderRadius:4, fontSize:'.72rem', whiteSpace:'nowrap' }}>
                            {j.status.replace(/_/g,' ')}
                          </span>
                        </td>
                        <td style={{ fontSize:'.75rem', color:'#fca5a5', maxWidth:160 }}>{missing.length > 0 ? missing.join(', ') : <span style={{ color:'#64748b' }}>—</span>}</td>
                        <td style={{ fontSize:'.75rem', color:'#f87171', maxWidth:160 }}>{errors.length > 0 ? errors.join(', ') : <span style={{ color:'#64748b' }}>—</span>}</td>
                        <td style={{ fontSize:'.8rem' }}>
                          <span style={{ color: missing.length === 0 && errors.length === 0 ? '#22c55e' : '#f59e0b' }}>
                            {missing.length === 0 && errors.length === 0 ? '✅ 100%' : `⚠ ${Math.max(0, 100 - missing.length*15)}%`}
                          </span>
                        </td>
                        <td>
                          {j.status === 'pending_admin_approval' && (
                            <div style={{ display:'flex', gap:6 }}>
                              <button className="btn btn-primary btn-sm" onClick={() => approveJob(j.id)} style={{ fontSize:'.72rem', padding:'3px 10px' }}>✅ Approve</button>
                              <button className="btn btn-outline btn-sm" onClick={() => declineJob(j.id)} style={{ fontSize:'.72rem', padding:'3px 10px', color:'#ef4444', borderColor:'#ef4444' }}>✕ Decline</button>
                            </div>
                          )}
                          {j.status === 'approved_ready_to_post' && <span style={{ color:'#22c55e', fontSize:'.75rem' }}>✅ Approved</span>}
                          {j.status === 'declined_needs_revision' && <span style={{ color:'#ef4444', fontSize:'.75rem' }}>❌ Declined</span>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Patients ── */}
      {panel === 'patients' && (
        <div className="card">
          <div className="card-header">
            <h3>👤 Patient Records</h3>
            <button className="btn btn-primary btn-sm" onClick={() => setShowPatForm(v => !v)}>+ Add Patient</button>
          </div>
          {showPatForm && (
            <form onSubmit={savePatient} style={{ display:'grid', gap:10, gridTemplateColumns:'1fr 1fr', marginBottom:20 }}>
              <select className="input" value={patForm.business_id} onChange={e => setPatForm(f=>({...f,business_id:e.target.value}))} required>
                <option value="">Business *</option>{businesses.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
              <div />
              <input className="input" placeholder="First Name *" value={patForm.first_name} onChange={e=>setPatForm(f=>({...f,first_name:e.target.value}))} required />
              <input className="input" placeholder="Last Name *" value={patForm.last_name} onChange={e=>setPatForm(f=>({...f,last_name:e.target.value}))} required />
              <input className="input" placeholder="Date of Birth (MM/DD/YYYY)" value={patForm.date_of_birth} onChange={e=>setPatForm(f=>({...f,date_of_birth:e.target.value}))} />
              <input className="input" placeholder="Phone" value={patForm.phone} onChange={e=>setPatForm(f=>({...f,phone:e.target.value}))} />
              <input className="input" placeholder="Email" value={patForm.email} onChange={e=>setPatForm(f=>({...f,email:e.target.value}))} />
              <select className="input" value={patForm.preferred_language} onChange={e=>setPatForm(f=>({...f,preferred_language:e.target.value}))}>
                {[['en','English'],['es','Spanish'],['ur','Urdu'],['vi','Vietnamese'],['zh','Chinese'],['ar','Arabic'],['fr','French']].map(([v,l])=><option key={v} value={v}>{l}</option>)}
              </select>
              <input className="input" placeholder="Address" value={patForm.address} onChange={e=>setPatForm(f=>({...f,address:e.target.value}))} style={{gridColumn:'1/-1'}} />
              <input className="input" placeholder="City" value={patForm.city} onChange={e=>setPatForm(f=>({...f,city:e.target.value}))} />
              <input className="input" placeholder="State" value={patForm.state} onChange={e=>setPatForm(f=>({...f,state:e.target.value}))} />
              <input className="input" placeholder="ZIP Code" value={patForm.zip_code} onChange={e=>setPatForm(f=>({...f,zip_code:e.target.value}))} />
              <div style={{gridColumn:'1/-1',display:'flex',gap:8}}>
                <button type="submit" className="btn btn-primary">Save Patient</button>
                <button type="button" className="btn btn-outline" onClick={()=>setShowPatForm(false)}>Cancel</button>
              </div>
            </form>
          )}
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>DOB</th><th>Phone</th><th>Email</th><th>Language</th><th>Business</th></tr></thead>
                <tbody>
                  {patients.length === 0 && <tr><td colSpan={6} style={{textAlign:'center',color:'#64748b'}}>No patients yet</td></tr>}
                  {patients.map(p => (
                    <tr key={p.id}>
                      <td>{p.first_name} {p.last_name}</td>
                      <td style={{fontSize:'.8rem'}}>{p.date_of_birth || '—'}</td>
                      <td>{p.phone || '—'}</td>
                      <td style={{fontSize:'.8rem'}}>{p.email || '—'}</td>
                      <td>{p.preferred_language}</td>
                      <td style={{fontSize:'.8rem'}}>{businesses.find(b=>b.id===p.business_id)?.name||`#${p.business_id}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Equipment Requests ── */}
      {panel === 'equipment' && (
        <div className="card">
          <div className="card-header">
            <h3>🦽 Equipment Requests</h3>
            <button className="btn btn-primary btn-sm" onClick={()=>setShowEqForm(v=>!v)}>+ New Request</button>
          </div>
          {showEqForm && (
            <form onSubmit={saveEquipment} style={{ display:'grid', gap:10, gridTemplateColumns:'1fr 1fr', marginBottom:20 }}>
              <select className="input" value={eqForm.business_id} onChange={e=>setEqForm(f=>({...f,business_id:e.target.value}))} required>
                <option value="">Business *</option>{businesses.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
              <select className="input" value={eqForm.patient_id} onChange={e=>setEqForm(f=>({...f,patient_id:e.target.value}))}>
                <option value="">Patient (optional)</option>{patients.map(p=><option key={p.id} value={p.id}>{p.first_name} {p.last_name}</option>)}
              </select>
              <input className="input" placeholder="Equipment Type *" value={eqForm.equipment_type} onChange={e=>setEqForm(f=>({...f,equipment_type:e.target.value}))} required style={{gridColumn:'1/-1'}} />
              <textarea className="input" placeholder="Diagnosis/Reason" value={eqForm.diagnosis_or_reason} onChange={e=>setEqForm(f=>({...f,diagnosis_or_reason:e.target.value}))} style={{gridColumn:'1/-1',minHeight:60}} />
              <input className="input" placeholder="Prescribing Provider" value={eqForm.prescribing_provider} onChange={e=>setEqForm(f=>({...f,prescribing_provider:e.target.value}))} />
              <input className="input" placeholder="HCPCS Codes (comma-separated)" value={eqForm.hcpcs_codes} onChange={e=>setEqForm(f=>({...f,hcpcs_codes:e.target.value}))} />
              <div style={{gridColumn:'1/-1',display:'flex',gap:8}}>
                <button type="submit" className="btn btn-primary">Submit Request</button>
                <button type="button" className="btn btn-outline" onClick={()=>setShowEqForm(false)}>Cancel</button>
              </div>
            </form>
          )}
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Equipment</th><th>Patient</th><th>Provider</th><th>HCPCS</th><th>Insurance</th><th>Status</th></tr></thead>
                <tbody>
                  {equipment.length === 0 && <tr><td colSpan={6} style={{textAlign:'center',color:'#64748b'}}>No equipment requests yet</td></tr>}
                  {equipment.map(r => (
                    <tr key={r.id}>
                      <td>{r.equipment_type}</td>
                      <td style={{fontSize:'.8rem'}}>{r.patient_id ? `#${r.patient_id}` : '—'}</td>
                      <td style={{fontSize:'.8rem'}}>{r.prescribing_provider || '—'}</td>
                      <td style={{fontFamily:'monospace',fontSize:'.75rem'}}>{r.hcpcs_codes || '—'}</td>
                      <td>{r.insurance_required ? '✅' : '—'}</td>
                      <td><span style={{background:STATUS_BADGE[r.status]||'#334155',color:'#fff',padding:'2px 8px',borderRadius:4,fontSize:'.72rem'}}>{r.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Bookkeeping ── */}
      {panel === 'bookkeeping' && (
        <div className="card">
          <div className="card-header">
            <h3>📒 Bookkeeping Entries</h3>
            <button className="btn btn-primary btn-sm" onClick={()=>setShowBkForm(v=>!v)}>+ Add Entry</button>
          </div>
          {showBkForm && (
            <form onSubmit={saveBookkeeping} style={{ display:'grid', gap:10, gridTemplateColumns:'1fr 1fr', marginBottom:20 }}>
              <select className="input" value={bkForm.business_id} onChange={e=>setBkForm(f=>({...f,business_id:e.target.value}))} required>
                <option value="">Business *</option>{businesses.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
              <select className="input" value={bkForm.entry_type} onChange={e=>setBkForm(f=>({...f,entry_type:e.target.value}))}>
                <option value="invoice">Invoice</option><option value="receipt">Receipt</option>
                <option value="expense">Expense</option><option value="revenue">Revenue</option>
              </select>
              <input className="input" placeholder="Vendor / Customer *" value={bkForm.vendor_or_customer} onChange={e=>setBkForm(f=>({...f,vendor_or_customer:e.target.value}))} required />
              <input className="input" placeholder="Transaction Date (MM/DD/YYYY)" value={bkForm.transaction_date} onChange={e=>setBkForm(f=>({...f,transaction_date:e.target.value}))} />
              <input className="input" type="number" placeholder="Amount ($) *" value={bkForm.amount} onChange={e=>setBkForm(f=>({...f,amount:e.target.value}))} required />
              <input className="input" placeholder="Category" value={bkForm.category} onChange={e=>setBkForm(f=>({...f,category:e.target.value}))} />
              <textarea className="input" placeholder="Memo / Notes" value={bkForm.memo} onChange={e=>setBkForm(f=>({...f,memo:e.target.value}))} style={{gridColumn:'1/-1',minHeight:60}} />
              <label style={{display:'flex',alignItems:'center',gap:8,color:'#cbd5e1',fontSize:'.85rem'}}>
                <input type="checkbox" checked={bkForm.tax_flag} onChange={e=>setBkForm(f=>({...f,tax_flag:e.target.checked}))} />Tax-related entry
              </label>
              <div style={{gridColumn:'1/-1',display:'flex',gap:8}}>
                <button type="submit" className="btn btn-primary">Save Draft</button>
                <button type="button" className="btn btn-outline" onClick={()=>setShowBkForm(false)}>Cancel</button>
              </div>
            </form>
          )}
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Vendor/Customer</th><th>Type</th><th>Date</th><th>Amount</th><th>Category</th><th>Tax</th><th>Status</th><th>Action</th></tr></thead>
                <tbody>
                  {bookkeeping.length === 0 && <tr><td colSpan={8} style={{textAlign:'center',color:'#64748b'}}>No bookkeeping entries yet</td></tr>}
                  {bookkeeping.map(e => (
                    <tr key={e.id}>
                      <td>{e.vendor_or_customer || '—'}</td>
                      <td style={{fontSize:'.78rem'}}>{e.entry_type || '—'}</td>
                      <td style={{fontSize:'.78rem'}}>{e.transaction_date || '—'}</td>
                      <td style={{color:e.entry_type==='expense'?'#f87171':'#34d399',fontWeight:600}}>${e.amount?.toFixed(2)||'0.00'}</td>
                      <td style={{fontSize:'.75rem'}}>{e.category || '—'}</td>
                      <td>{e.tax_flag ? '✅' : '—'}</td>
                      <td><span style={{background:STATUS_BADGE[e.status]||'#334155',color:'#fff',padding:'2px 8px',borderRadius:4,fontSize:'.72rem'}}>{e.status}</span></td>
                      <td>
                        {!e.admin_approved && (
                          <button className="btn btn-primary btn-sm" onClick={()=>approveBk(e.id)} style={{fontSize:'.72rem',padding:'3px 8px'}}>✅ Approve</button>
                        )}
                        {e.admin_approved && <span style={{color:'#22c55e',fontSize:'.75rem'}}>Approved</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Audit Log ── */}
      {panel === 'audit' && (
        <div className="card">
          <h3 style={{marginBottom:12}}>🔐 Audit Log</h3>
          <p style={{color:'#94a3b8',fontSize:'.82rem',marginBottom:12}}>Immutable record of all admin actions on medical, insurance, and bookkeeping data.</p>
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Entity ID</th></tr></thead>
                <tbody>
                  {auditLogs.length === 0 && <tr><td colSpan={5} style={{textAlign:'center',color:'#64748b'}}>No audit logs yet</td></tr>}
                  {auditLogs.map(l => (
                    <tr key={l.id}>
                      <td style={{fontSize:'.75rem',color:'#64748b',whiteSpace:'nowrap'}}>{new Date(l.created_at).toLocaleString()}</td>
                      <td style={{fontSize:'.8rem',color:'#60a5fa'}}>{l.actor}</td>
                      <td style={{fontSize:'.8rem'}}>{l.action.replace(/_/g,' ')}</td>
                      <td style={{fontSize:'.75rem'}}>{l.entity_type || '—'}</td>
                      <td style={{fontSize:'.75rem',fontFamily:'monospace'}}>{l.entity_id || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Healthcare Hub Tab ────────────────────────────────────────────────────────
function HealthcareTab() {
  const [contacts, setContacts]   = useState([])
  const [intakes, setIntakes]     = useState([])
  const [businesses, setBusinesses] = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')
  const [panel, setPanel]         = useState('contacts') // contacts | intake | verify
  const [showForm, setShowForm]   = useState(false)

  // Contact form
  const [cForm, setCForm] = useState({ business_id: '', first_name: '', last_name: '', email: '', phone: '', preferred_language: 'en', consent_given: false })
  // Intake form
  const [iForm, setIForm] = useState({ contact_id: '', date_of_birth: '', gender: '', insurance_name: '', insurance_member_id: '', insurance_group_no: '', diagnosis_codes: '', equipment_needed: '', prescribing_doctor: '' })
  // Insurance AI
  const [verifyForm, setVerifyForm] = useState({ insurance_name: '', member_id: '', service: 'DME' })
  const [verifyResult, setVerifyResult] = useState('')
  const [verifying, setVerifying] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [c, i, b] = await Promise.all([
        apiFetch('/contacts'),
        apiFetch('/patient-intake'),
        apiFetch('/businesses'),
      ])
      setContacts(c); setIntakes(i); setBusinesses(b)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const saveContact = async (e) => {
    e.preventDefault(); setError('')
    try {
      await apiFetch('/contacts', { method: 'POST', body: JSON.stringify({ ...cForm, business_id: Number(cForm.business_id) }) })
      setCForm({ business_id: '', first_name: '', last_name: '', email: '', phone: '', preferred_language: 'en', consent_given: false })
      setShowForm(false); load()
    } catch (e) { setError(e.message) }
  }

  const saveIntake = async (e) => {
    e.preventDefault(); setError('')
    try {
      await apiFetch('/patient-intake', { method: 'POST', body: JSON.stringify({ ...iForm, contact_id: Number(iForm.contact_id) }) })
      setIForm({ contact_id: '', date_of_birth: '', gender: '', insurance_name: '', insurance_member_id: '', insurance_group_no: '', diagnosis_codes: '', equipment_needed: '', prescribing_doctor: '' })
      setShowForm(false); load()
    } catch (e) { setError(e.message) }
  }

  const runVerify = async (e) => {
    e.preventDefault(); setVerifyResult(''); setVerifying(true)
    try {
      const res = await apiFetch('/agents/run', {
        method: 'POST',
        body: JSON.stringify({ agent_key: 'insurance_verification', task_type: 'check_eligibility', payload: verifyForm }),
      })
      setVerifyResult(res.result?.verification_steps || JSON.stringify(res.result))
    } catch (e) { setError(e.message) }
    finally { setVerifying(false) }
  }

  const STATUS_COLOR = { pending: '#f59e0b', verified: '#3b82f6', approved: '#22c55e', denied: '#ef4444' }

  return (
    <div>
      <Alert msg={error} type="error" />
      <div style={{ display:'flex', gap:10, marginBottom:16, flexWrap:'wrap' }}>
        {['contacts','intake','verify'].map(p => (
          <button key={p} className={`tab-btn ${panel===p?'active':''}`} style={{ fontSize:'.8rem', padding:'6px 14px' }} onClick={() => { setPanel(p); setShowForm(false) }}>
            {p === 'contacts' ? '👥 Contacts' : p === 'intake' ? '📋 Patient Intake' : '🔒 Insurance Verify'}
          </button>
        ))}
      </div>

      {/* Contacts */}
      {panel === 'contacts' && (
        <div className="card">
          <div className="card-header">
            <h3>Patient / Lead Contacts</h3>
            <button className="btn btn-primary btn-sm" onClick={() => setShowForm(v => !v)}>+ Add Contact</button>
          </div>
          {showForm && (
            <form onSubmit={saveContact} style={{ display:'grid', gap:10, gridTemplateColumns:'1fr 1fr', marginBottom:20 }}>
              <select value={cForm.business_id} onChange={e => setCForm(f => ({...f, business_id: e.target.value}))} required className="input">
                <option value="">Select Business *</option>
                {businesses.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
              </select>
              <input className="input" placeholder="First Name *" value={cForm.first_name} onChange={e => setCForm(f => ({...f, first_name: e.target.value}))} required />
              <input className="input" placeholder="Last Name *" value={cForm.last_name} onChange={e => setCForm(f => ({...f, last_name: e.target.value}))} required />
              <input className="input" placeholder="Email" value={cForm.email} onChange={e => setCForm(f => ({...f, email: e.target.value}))} />
              <input className="input" placeholder="Phone" value={cForm.phone} onChange={e => setCForm(f => ({...f, phone: e.target.value}))} />
              <select className="input" value={cForm.preferred_language} onChange={e => setCForm(f => ({...f, preferred_language: e.target.value}))}>
                {[['en','English'],['es','Spanish'],['ur','Urdu'],['vi','Vietnamese'],['zh','Chinese'],['fr','French'],['ar','Arabic']].map(([v,l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <label style={{ display:'flex', alignItems:'center', gap:8, color:'#cbd5e1', fontSize:'.85rem', gridColumn:'1/-1' }}>
                <input type="checkbox" checked={cForm.consent_given} onChange={e => setCForm(f => ({...f, consent_given: e.target.checked}))} />
                HIPAA Consent Obtained
              </label>
              <div style={{ gridColumn:'1/-1', display:'flex', gap:8 }}>
                <button type="submit" className="btn btn-primary">Save Contact</button>
                <button type="button" className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
              </div>
            </form>
          )}
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Name</th><th>Business</th><th>Phone</th><th>Email</th><th>Language</th><th>Consent</th></tr></thead>
                <tbody>
                  {contacts.length === 0 && <tr><td colSpan={6} style={{ textAlign:'center', color:'#64748b' }}>No contacts yet</td></tr>}
                  {contacts.map(c => (
                    <tr key={c.id}>
                      <td>{c.first_name} {c.last_name}</td>
                      <td>{businesses.find(b => b.id === c.business_id)?.name || c.business_id}</td>
                      <td>{c.phone || '—'}</td>
                      <td>{c.email || '—'}</td>
                      <td>{c.preferred_language}</td>
                      <td>{c.consent_given ? '✅' : '❌'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Patient Intake */}
      {panel === 'intake' && (
        <div className="card">
          <div className="card-header">
            <h3>Patient Intake Forms (DME / Healthcare)</h3>
            <button className="btn btn-primary btn-sm" onClick={() => setShowForm(v => !v)}>+ New Intake</button>
          </div>
          {showForm && (
            <form onSubmit={saveIntake} style={{ display:'grid', gap:10, gridTemplateColumns:'1fr 1fr', marginBottom:20 }}>
              <select className="input" value={iForm.contact_id} onChange={e => setIForm(f => ({...f, contact_id: e.target.value}))} required style={{ gridColumn:'1/-1' }}>
                <option value="">Select Contact *</option>
                {contacts.map(c => <option key={c.id} value={c.id}>{c.first_name} {c.last_name} — {c.phone || c.email || `#${c.id}`}</option>)}
              </select>
              <input className="input" placeholder="Date of Birth (YYYY-MM-DD)" value={iForm.date_of_birth} onChange={e => setIForm(f => ({...f, date_of_birth: e.target.value}))} />
              <select className="input" value={iForm.gender} onChange={e => setIForm(f => ({...f, gender: e.target.value}))}>
                <option value="">Gender</option>
                <option>Male</option><option>Female</option><option>Non-binary</option><option>Prefer not to say</option>
              </select>
              <input className="input" placeholder="Insurance Name" value={iForm.insurance_name} onChange={e => setIForm(f => ({...f, insurance_name: e.target.value}))} />
              <input className="input" placeholder="Member ID" value={iForm.insurance_member_id} onChange={e => setIForm(f => ({...f, insurance_member_id: e.target.value}))} />
              <input className="input" placeholder="Group No." value={iForm.insurance_group_no} onChange={e => setIForm(f => ({...f, insurance_group_no: e.target.value}))} />
              <input className="input" placeholder="Diagnosis Codes (ICD-10, comma-separated)" value={iForm.diagnosis_codes} onChange={e => setIForm(f => ({...f, diagnosis_codes: e.target.value}))} style={{ gridColumn:'1/-1' }} />
              <input className="input" placeholder="Equipment Needed (e.g. CPAP, wheelchair)" value={iForm.equipment_needed} onChange={e => setIForm(f => ({...f, equipment_needed: e.target.value}))} style={{ gridColumn:'1/-1' }} />
              <input className="input" placeholder="Prescribing Doctor" value={iForm.prescribing_doctor} onChange={e => setIForm(f => ({...f, prescribing_doctor: e.target.value}))} />
              <div style={{ display:'flex', gap:8, gridColumn:'1/-1' }}>
                <button type="submit" className="btn btn-primary">Submit Intake</button>
                <button type="button" className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
              </div>
            </form>
          )}
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Contact #</th><th>Insurance</th><th>Member ID</th><th>Equipment</th><th>Diagnosis</th><th>Status</th></tr></thead>
                <tbody>
                  {intakes.length === 0 && <tr><td colSpan={6} style={{ textAlign:'center', color:'#64748b' }}>No intakes yet</td></tr>}
                  {intakes.map(i => (
                    <tr key={i.id}>
                      <td>#{i.contact_id}</td>
                      <td>{i.insurance_name || '—'}</td>
                      <td>{i.insurance_member_id || '—'}</td>
                      <td>{i.equipment_needed || '—'}</td>
                      <td style={{ fontSize:'.75rem' }}>{i.diagnosis_codes || '—'}</td>
                      <td><span style={{ background: STATUS_COLOR[i.status] || '#64748b', color:'#fff', padding:'2px 8px', borderRadius:4, fontSize:'.73rem' }}>{i.status}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Insurance Verification */}
      {panel === 'verify' && (
        <div className="card">
          <h3 style={{ marginBottom:16 }}>🔒 AI Insurance Verification</h3>
          <p style={{ color:'#94a3b8', marginBottom:16, fontSize:'.85rem' }}>Enter patient insurance details and our AI agent will provide verification steps and eligibility guidance.</p>
          <form onSubmit={runVerify} style={{ display:'grid', gap:10, gridTemplateColumns:'1fr 1fr', maxWidth:600 }}>
            <input className="input" placeholder="Insurance Name (e.g. Aetna, Medicare)" value={verifyForm.insurance_name} onChange={e => setVerifyForm(f => ({...f, insurance_name: e.target.value}))} required />
            <input className="input" placeholder="Member ID" value={verifyForm.member_id} onChange={e => setVerifyForm(f => ({...f, member_id: e.target.value}))} required />
            <input className="input" placeholder="Service (e.g. CPAP, wheelchair)" value={verifyForm.service} onChange={e => setVerifyForm(f => ({...f, service: e.target.value}))} style={{ gridColumn:'1/-1' }} />
            <button type="submit" className="btn btn-primary" disabled={verifying} style={{ gridColumn:'1/-1' }}>
              {verifying ? '🔄 Checking…' : '🔒 Verify Eligibility'}
            </button>
          </form>
          {verifyResult && (
            <div style={{ marginTop:20, background:'#0f172a', border:'1px solid #1e40af', borderRadius:8, padding:16 }}>
              <h4 style={{ color:'#60a5fa', marginBottom:8 }}>Verification Steps</h4>
              <pre style={{ color:'#e2e8f0', whiteSpace:'pre-wrap', fontSize:'.82rem', fontFamily:'inherit', margin:0 }}>{verifyResult}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── DME Marketplace Tab ───────────────────────────────────────────────────────
function DMEMarketplaceTab() {
  const [products, setProducts]   = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')
  const [showForm, setShowForm]   = useState(false)
  const [filterCat, setFilterCat] = useState('')
  const [matchForm, setMatchForm] = useState({ diagnosis: '', equipment_needed: '' })
  const [matchResult, setMatchResult] = useState('')
  const [matching, setMatching]   = useState(false)
  const [panel, setPanel]         = useState('products') // products | match

  const [form, setForm] = useState({
    supplier_name: '', supplier_email: '', name: '', category: '',
    hcpcs_code: '', description: '', unit_price: '', lead_time_days: 1
  })

  const CATEGORIES = ['mobility', 'respiratory', 'wound_care', 'orthotics', 'bathroom_safety', 'hospital_beds', 'diabetic', 'other']

  const load = async () => {
    setLoading(true)
    try {
      const url = filterCat ? `/supplier/products?category=${filterCat}` : '/supplier/products'
      setProducts(await apiFetch(url))
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [filterCat])

  const saveProduct = async (e) => {
    e.preventDefault(); setError('')
    try {
      await apiFetch('/supplier/products', {
        method: 'POST',
        body: JSON.stringify({ ...form, unit_price: form.unit_price ? Number(form.unit_price) : null, lead_time_days: Number(form.lead_time_days) })
      })
      setForm({ supplier_name: '', supplier_email: '', name: '', category: '', hcpcs_code: '', description: '', unit_price: '', lead_time_days: 1 })
      setShowForm(false); load()
    } catch (e) { setError(e.message) }
  }

  const runMatch = async (e) => {
    e.preventDefault(); setMatchResult(''); setMatching(true)
    try {
      const res = await apiFetch('/agents/run', {
        method: 'POST',
        body: JSON.stringify({ agent_key: 'dme_product_matching', task_type: 'match_products', payload: matchForm }),
      })
      setMatchResult(res.result?.recommendations || JSON.stringify(res.result))
    } catch (e) { setError(e.message) }
    finally { setMatching(false) }
  }

  return (
    <div>
      <Alert msg={error} type="error" />
      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        {['products','match'].map(p => (
          <button key={p} className={`tab-btn ${panel===p?'active':''}`} style={{ fontSize:'.8rem', padding:'6px 14px' }} onClick={() => setPanel(p)}>
            {p === 'products' ? '🏪 Supplier Products' : '🦽 AI Product Matching'}
          </button>
        ))}
      </div>

      {/* Products */}
      {panel === 'products' && (
        <div className="card">
          <div className="card-header">
            <h3>DME Supplier Marketplace</h3>
            <div style={{ display:'flex', gap:8 }}>
              <select className="input" style={{ width:'auto', fontSize:'.8rem', padding:'4px 8px' }} value={filterCat} onChange={e => setFilterCat(e.target.value)}>
                <option value="">All Categories</option>
                {CATEGORIES.map(c => <option key={c} value={c}>{c.replace(/_/g,' ')}</option>)}
              </select>
              <button className="btn btn-primary btn-sm" onClick={() => setShowForm(v => !v)}>+ Add Product</button>
            </div>
          </div>

          {showForm && (
            <form onSubmit={saveProduct} style={{ display:'grid', gap:10, gridTemplateColumns:'1fr 1fr', marginBottom:20 }}>
              <input className="input" placeholder="Supplier Name *" value={form.supplier_name} onChange={e => setForm(f => ({...f, supplier_name: e.target.value}))} required />
              <input className="input" placeholder="Supplier Email" value={form.supplier_email} onChange={e => setForm(f => ({...f, supplier_email: e.target.value}))} />
              <input className="input" placeholder="Product Name *" value={form.name} onChange={e => setForm(f => ({...f, name: e.target.value}))} required style={{ gridColumn:'1/-1' }} />
              <select className="input" value={form.category} onChange={e => setForm(f => ({...f, category: e.target.value}))} required>
                <option value="">Category *</option>
                {CATEGORIES.map(c => <option key={c} value={c}>{c.replace(/_/g,' ')}</option>)}
              </select>
              <input className="input" placeholder="HCPCS Code (e.g. E0601)" value={form.hcpcs_code} onChange={e => setForm(f => ({...f, hcpcs_code: e.target.value}))} />
              <input className="input" placeholder="Unit Price ($)" type="number" step="0.01" value={form.unit_price} onChange={e => setForm(f => ({...f, unit_price: e.target.value}))} />
              <input className="input" placeholder="Lead Time (days)" type="number" value={form.lead_time_days} onChange={e => setForm(f => ({...f, lead_time_days: e.target.value}))} />
              <textarea className="input" placeholder="Description" value={form.description} onChange={e => setForm(f => ({...f, description: e.target.value}))} style={{ gridColumn:'1/-1', minHeight:60 }} />
              <div style={{ gridColumn:'1/-1', display:'flex', gap:8 }}>
                <button type="submit" className="btn btn-primary">Save Product</button>
                <button type="button" className="btn btn-outline" onClick={() => setShowForm(false)}>Cancel</button>
              </div>
            </form>
          )}

          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Product</th><th>Category</th><th>HCPCS</th><th>Supplier</th><th>Price</th><th>Lead Time</th><th>Available</th></tr></thead>
                <tbody>
                  {products.length === 0 && <tr><td colSpan={7} style={{ textAlign:'center', color:'#64748b' }}>No products yet. Add your first supplier product above.</td></tr>}
                  {products.map(p => (
                    <tr key={p.id}>
                      <td>{p.name}</td>
                      <td style={{ fontSize:'.75rem' }}>{p.category.replace(/_/g,' ')}</td>
                      <td style={{ fontFamily:'monospace', fontSize:'.8rem' }}>{p.hcpcs_code || '—'}</td>
                      <td>{p.supplier_name}</td>
                      <td>{p.unit_price ? `$${p.unit_price.toFixed(2)}` : '—'}</td>
                      <td>{p.lead_time_days}d</td>
                      <td>{p.is_available ? '✅' : '❌'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* AI Product Matching */}
      {panel === 'match' && (
        <div className="card">
          <h3 style={{ marginBottom:8 }}>🦽 AI DME Product Matching</h3>
          <p style={{ color:'#94a3b8', marginBottom:16, fontSize:'.85rem' }}>Enter patient diagnosis and equipment need — the AI will recommend matching DME products and HCPCS codes.</p>
          <form onSubmit={runMatch} style={{ display:'grid', gap:10, maxWidth:600 }}>
            <input className="input" placeholder="Diagnosis (e.g. COPD, paraplegia)" value={matchForm.diagnosis} onChange={e => setMatchForm(f => ({...f, diagnosis: e.target.value}))} required />
            <input className="input" placeholder="Equipment needed (e.g. CPAP machine, power wheelchair)" value={matchForm.equipment_needed} onChange={e => setMatchForm(f => ({...f, equipment_needed: e.target.value}))} required />
            <button type="submit" className="btn btn-primary" disabled={matching}>{matching ? '🔄 Matching…' : '🦽 Find Products'}</button>
          </form>
          {matchResult && (
            <div style={{ marginTop:20, background:'#0f172a', border:'1px solid #0f766e', borderRadius:8, padding:16 }}>
              <h4 style={{ color:'#2dd4bf', marginBottom:8 }}>Product Recommendations</h4>
              <pre style={{ color:'#e2e8f0', whiteSpace:'pre-wrap', fontSize:'.82rem', fontFamily:'inherit', margin:0 }}>{matchResult}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Agents Roster Tab ─────────────────────────────────────────────────────────
function AgentsTab() {
  const [roster, setRoster]       = useState([])
  const [tasks, setTasks]         = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')
  const [panel, setPanel]         = useState('roster')
  const [runForm, setRunForm]     = useState({ agent_key: '', task_type: '', payload_json: '{}' })
  const [running, setRunning]     = useState(false)
  const [runResult, setRunResult] = useState(null)

  const CATEGORY_COLOR = {
    operations:'#3b82f6', communication:'#8b5cf6', sales:'#f59e0b',
    finance:'#22c55e', marketing:'#ec4899', technology:'#06b6d4',
    media:'#f97316', healthcare:'#14b8a6', marketplace:'#6366f1',
    compliance:'#ef4444', general:'#64748b',
  }

  const load = async () => {
    setLoading(true)
    try {
      const [r, t] = await Promise.all([apiFetch('/agents/roster'), apiFetch('/agents/tasks')])
      setRoster(r); setTasks(t)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const runTask = async (e) => {
    e.preventDefault(); setError(''); setRunResult(null); setRunning(true)
    try {
      const payload = JSON.parse(runForm.payload_json)
      const res = await apiFetch('/agents/run', {
        method: 'POST',
        body: JSON.stringify({ agent_key: runForm.agent_key, task_type: runForm.task_type, payload }),
      })
      setRunResult(res); load()
    } catch (e) { setError(e.message) }
    finally { setRunning(false) }
  }

  return (
    <div>
      <Alert msg={error} type="error" />
      <div style={{ display:'flex', gap:10, marginBottom:16 }}>
        {['roster','run','history'].map(p => (
          <button key={p} className={`tab-btn ${panel===p?'active':''}`} style={{ fontSize:'.8rem', padding:'6px 14px' }} onClick={() => setPanel(p)}>
            {p === 'roster' ? '🤖 All 13 Agents' : p === 'run' ? '⚡ Run Agent Task' : '📜 Task History'}
          </button>
        ))}
      </div>

      {/* Roster */}
      {panel === 'roster' && (
        <div>
          {loading ? <Spinner /> : (
            <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill, minmax(260px, 1fr))', gap:14 }}>
              {roster.map((a, i) => {
                const agentKey = a.key || a.name.toLowerCase().replace(/[\s&]+/g,'_').replace(/[^a-z_]/g,'').replace(/_agent$/,'')
                const isActive = a.status === 'active'
                return (
                <div key={i}
                  onClick={() => { if (isActive) { setRunForm(f => ({...f, agent_key: agentKey})); setPanel('run') } }}
                  style={{ background:'#1e293b', border:'1px solid #334155', borderRadius:10, padding:16, position:'relative', overflow:'hidden', cursor: isActive ? 'pointer' : 'default', transition:'border-color .2s, transform .15s' }}
                  onMouseEnter={e => { if (isActive) { e.currentTarget.style.borderColor='#38bdf8'; e.currentTarget.style.transform='translateY(-2px)' }}}
                  onMouseLeave={e => { e.currentTarget.style.borderColor='#334155'; e.currentTarget.style.transform='none' }}>
                  <div style={{ position:'absolute', top:0, left:0, right:0, height:3, background: CATEGORY_COLOR[a.category] || '#64748b' }} />
                  <div style={{ fontSize:'1.8rem', marginBottom:6 }}>{a.icon}</div>
                  <div style={{ fontWeight:600, color:'#f1f5f9', marginBottom:4, fontSize:'.9rem' }}>{a.name}</div>
                  <div style={{ fontSize:'.75rem', color:'#94a3b8', marginBottom:8 }}>{a.description}</div>
                  <div style={{ display:'flex', gap:6, flexWrap:'wrap' }}>
                    <span style={{ background: CATEGORY_COLOR[a.category] || '#64748b', color:'#fff', padding:'2px 8px', borderRadius:12, fontSize:'.68rem' }}>{a.category}</span>
                    <span style={{ background: a.status === 'active' ? '#22c55e' : a.status === 'maintenance' ? '#f59e0b' : '#334155', color:'#fff', padding:'2px 8px', borderRadius:12, fontSize:'.68rem' }}>
                      {a.status === 'active' ? '✅ Active' : a.status === 'coming_soon' ? '🔜 Soon' : '🔧 Maintenance'}
                    </span>
                    {isActive && <span style={{ background:'#1e4d72', color:'#38bdf8', padding:'2px 8px', borderRadius:12, fontSize:'.68rem' }}>▶ Run Task</span>}
                  </div>
                </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Run task */}
      {panel === 'run' && (
        <div className="card" style={{ maxWidth:600 }}>
          <h3 style={{ marginBottom:12 }}>⚡ Dispatch Agent Task</h3>
          <form onSubmit={runTask} style={{ display:'grid', gap:10 }}>
            <select className="input" value={runForm.agent_key} onChange={e => setRunForm(f => ({...f, agent_key: e.target.value}))} required>
              <option value="">Select Agent *</option>
              {roster.filter(a => a.status === 'active').map(a => (
                <option key={a.name} value={a.key || a.name.toLowerCase().replace(/[\s&]+/g,'_').replace(/[^a-z_]/g,'').replace(/_agent$/,'')}>{a.icon} {a.name}</option>
              ))}
            </select>
            <input className="input" placeholder="Task Type (e.g. triage, qualify_lead, generate_copy)" value={runForm.task_type} onChange={e => setRunForm(f => ({...f, task_type: e.target.value}))} required />
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.8rem' }}>Payload (JSON)</label>
              <textarea className="input" style={{ fontFamily:'monospace', fontSize:'.8rem', minHeight:80 }} value={runForm.payload_json} onChange={e => setRunForm(f => ({...f, payload_json: e.target.value}))} required />
            </div>
            <button type="submit" className="btn btn-primary" disabled={running}>{running ? '🔄 Running…' : '⚡ Run Task'}</button>
          </form>
          {runResult && (
            <div style={{ marginTop:20, background:'#0f172a', border:'1px solid #0f766e', borderRadius:8, padding:16 }}>
              <div style={{ display:'flex', gap:8, marginBottom:8, flexWrap:'wrap' }}>
                <span style={{ background: runResult.status === 'success' ? '#22c55e' : '#ef4444', color:'#fff', padding:'2px 10px', borderRadius:12, fontSize:'.75rem' }}>{runResult.status}</span>
                <span style={{ color:'#64748b', fontSize:'.75rem' }}>{runResult.duration_ms}ms</span>
                {runResult.task_id && <span style={{ color:'#64748b', fontSize:'.75rem' }}>Task #{runResult.task_id}</span>}
              </div>
              <pre style={{ color:'#e2e8f0', whiteSpace:'pre-wrap', fontSize:'.8rem', fontFamily:'inherit', margin:0 }}>
                {JSON.stringify(runResult.result || runResult.error, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* History */}
      {panel === 'history' && (
        <div className="card">
          <h3 style={{ marginBottom:12 }}>📜 Agent Task History</h3>
          {loading ? <Spinner /> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Agent</th><th>Task</th><th>Status</th><th>Duration</th><th>Created</th></tr></thead>
                <tbody>
                  {tasks.length === 0 && <tr><td colSpan={6} style={{ textAlign:'center', color:'#64748b' }}>No tasks yet. Run a task to see history.</td></tr>}
                  {tasks.map(t => (
                    <tr key={t.id}>
                      <td>#{t.id}</td>
                      <td style={{ fontSize:'.8rem' }}>{t.agent_name}</td>
                      <td style={{ fontSize:'.8rem' }}>{t.task_type}</td>
                      <td><span style={{ background: t.status === 'success' ? '#22c55e' : t.status === 'error' ? '#ef4444' : '#f59e0b', color:'#fff', padding:'2px 8px', borderRadius:4, fontSize:'.72rem' }}>{t.status}</span></td>
                      <td style={{ fontSize:'.8rem' }}>{t.duration_ms ? `${t.duration_ms}ms` : '—'}</td>
                      <td style={{ fontSize:'.75rem', color:'#64748b' }}>{new Date(t.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Auth Modal (Login + Register) ─────────────────────────────────────────────
function AuthModal({ onClose }) {
  const { login } = useAuth()
  const [tab, setTab]       = useState('login')
  const [email, setEmail]   = useState('')
  const [pass, setPass]     = useState('')
  const [name, setName]     = useState('')
  const [error, setError]   = useState('')
  const [loading, setLoading] = useState(false)

  const handleLogin = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      const form = new URLSearchParams({ username: email, password: pass })
      const res  = await fetch(`${API}/auth/login`, { method: 'POST', body: form })
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        throw new Error(err.detail || 'Login failed')
      }
      const data = await res.json()
      login(data.user, data.access_token)
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  const handleRegister = async (e) => {
    e.preventDefault(); setError(''); setLoading(true)
    try {
      const data = await apiFetch('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password: pass, full_name: name }),
      })
      // Auto-login after register
      const form = new URLSearchParams({ username: email, password: pass })
      const res  = await fetch(`${API}/auth/login`, { method: 'POST', body: form })
      const loginData = await res.json()
      login(loginData.user, loginData.access_token)
      onClose()
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  return (
    <div className="auth-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="auth-modal">
        <button className="auth-close" onClick={onClose}>✕</button>
        <div className="auth-logo">🤖 EZ-NEXUS AI</div>
        <div className="auth-tabs">
          <button className={`auth-tab-btn ${tab === 'login' ? 'active' : ''}`} onClick={() => { setTab('login'); setError('') }}>Login</button>
          <button className={`auth-tab-btn ${tab === 'register' ? 'active' : ''}`} onClick={() => { setTab('register'); setError('') }}>Register</button>
        </div>

        {error && <div className="alert alert-error" style={{ margin: '0 0 12px' }}>{error}</div>}

        {tab === 'login' ? (
          <form onSubmit={handleLogin} className="auth-form">
            <div className="form-group">
              <label className="form-label">Email</label>
              <input className="form-input" type="email" required autoFocus value={email} onChange={e => setEmail(e.target.value)} placeholder="ez.nexusai@gmail.com" />
            </div>
            <div className="form-group">
              <label className="form-label">Password</label>
              <input className="form-input" type="password" required value={pass} onChange={e => setPass(e.target.value)} placeholder="••••••••" />
            </div>
            <button className="btn btn-primary auth-submit" type="submit" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign In'}
            </button>
            <p className="auth-hint">Default admin: ez.nexusai@gmail.com / Commander@2024!</p>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="auth-form">
            <div className="form-group">
              <label className="form-label">Full Name</label>
              <input className="form-input" required value={name} onChange={e => setName(e.target.value)} placeholder="Your Name" />
            </div>
            <div className="form-group">
              <label className="form-label">Email</label>
              <input className="form-input" type="email" required value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com" />
            </div>
            <div className="form-group">
              <label className="form-label">Password (min 8 chars)</label>
              <input className="form-input" type="password" required minLength={8} value={pass} onChange={e => setPass(e.target.value)} placeholder="••••••••" />
            </div>
            <button className="btn btn-primary auth-submit" type="submit" disabled={loading}>
              {loading ? 'Creating account…' : 'Create Account'}
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

// ── Change Password Modal ─────────────────────────────────────────────────────
function ChangePasswordModal({ onClose }) {
  const { token } = useAuth()
  const [oldPass, setOldPass] = useState('')
  const [newPass, setNewPass] = useState('')
  const [error,   setError]   = useState('')
  const [success, setSuccess] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault(); setError(''); setSuccess('')
    try {
      await authFetch('/auth/me/password', token, {
        method: 'PUT',
        body: JSON.stringify({ old_password: oldPass, new_password: newPass }),
      })
      setSuccess('Password updated! Please log in again.')
      setTimeout(onClose, 2000)
    } catch (e) { setError(e.message) }
  }

  return (
    <div className="auth-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="auth-modal">
        <button className="auth-close" onClick={onClose}>✕</button>
        <div className="auth-logo">🔐 Change Password</div>
        {error   && <div className="alert alert-error"   style={{ margin: '0 0 12px' }}>{error}</div>}
        {success && <div className="alert alert-success" style={{ margin: '0 0 12px' }}>{success}</div>}
        <form onSubmit={handleSubmit} className="auth-form">
          <div className="form-group">
            <label className="form-label">Current Password</label>
            <input className="form-input" type="password" required value={oldPass} onChange={e => setOldPass(e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">New Password (min 8 chars)</label>
            <input className="form-input" type="password" required minLength={8} value={newPass} onChange={e => setNewPass(e.target.value)} />
          </div>
          <button className="btn btn-primary auth-submit" type="submit">Update Password</button>
        </form>
      </div>
    </div>
  )
}

// ── Subscriptions Tab ─────────────────────────────────────────────────────────
const PLANS = [
  {
    id: 'starter',
    name: 'Starter',
    price: '$299',
    period: '/month',
    badge: null,
    color: '#1B4FD8',
    features: [
      '1 Business Profile',
      'AI Call Center (up to 500 calls/mo)',
      'Appointment Booking & Management',
      'SMS + Email Confirmations',
      'CRM — up to 500 contacts',
      'Basic Analytics Dashboard',
      '3 AI Agents Active',
      'Email Support',
    ],
  },
  {
    id: 'professional',
    name: 'Professional',
    price: '$799',
    period: '/month',
    badge: 'Most Popular',
    color: '#0F766E',
    features: [
      'Up to 5 Business Profiles',
      'AI Call Center (up to 2,000 calls/mo)',
      'Appointments + Staff Approval Workflow',
      'SMS + Email + WhatsApp Confirmations',
      'CRM — unlimited contacts',
      'Advanced Analytics + Reports',
      '8 AI Agents Active',
      'Website Builder (AI-powered)',
      'SEO + Marketing Agent',
      'Priority Support',
    ],
  },
  {
    id: 'enterprise',
    name: 'Enterprise',
    price: '$1,999',
    period: '/month',
    badge: 'Full Platform',
    color: '#7C3AED',
    features: [
      'Unlimited Business Profiles',
      'Unlimited AI Calls (custom Twilio)',
      'All 13 AI Agents Active',
      'COMMANDER AI — Master Agent',
      'Custom AI Agent Builder',
      'White-Label Platform',
      'API Access + Webhooks',
      'Custom Integrations',
      'Dedicated Account Manager',
      '24/7 Priority Support',
      'SLA Guarantee',
    ],
  },
  {
    id: 'custom',
    name: 'Custom',
    price: 'Contact Us',
    period: '',
    badge: 'Enterprise+',
    color: '#0D1F3C',
    features: [
      'Everything in Enterprise',
      'On-premise deployment',
      'Custom AI model training',
      'Dedicated infrastructure',
      'Custom compliance packages',
      'Volume discounts',
      'Multi-region support',
      'Strategic partnership',
    ],
  },
]

function SubscriptionsTab() {
  const { user } = useAuth()
  return (
    <div>
      <div className="subs-hero">
        <h2 className="subs-title">Simple, Transparent Pricing</h2>
        <p className="subs-subtitle">
          Start free. Scale as you grow. Every plan includes EZ-NEXUS AI's core workforce platform.
        </p>
        {user && <p className="subs-current">Your current plan: <strong style={{ textTransform: 'capitalize' }}>{user.plan}</strong></p>}
      </div>

      <div className="subs-grid">
        {PLANS.map(plan => (
          <div key={plan.id} className={`subs-card ${plan.badge === 'Most Popular' ? 'subs-card--featured' : ''}`}>
            {plan.badge && <div className="subs-badge" style={{ background: plan.color }}>{plan.badge}</div>}
            <div className="subs-plan-name">{plan.name}</div>
            <div className="subs-price">
              <span className="subs-amount" style={{ color: plan.color }}>{plan.price}</span>
              <span className="subs-period">{plan.period}</span>
            </div>
            <ul className="subs-features">
              {plan.features.map((f, i) => (
                <li key={i} className="subs-feature">
                  <span className="subs-check" style={{ color: plan.color }}>✓</span>
                  {f}
                </li>
              ))}
            </ul>
            <button
              className="btn subs-cta"
              style={{ background: plan.color, color: '#fff', borderColor: plan.color }}
              onClick={() => alert(plan.id === 'custom'
                ? 'Contact us at sportstalks786@gmail.com for custom pricing.'
                : `To activate ${plan.name} plan, configure your Twilio account and contact support.`
              )}
            >
              {plan.id === 'custom' ? 'Contact Sales' : user?.plan === plan.id ? '✓ Current Plan' : `Get ${plan.name}`}
            </button>
          </div>
        ))}
      </div>

      <div className="subs-footer">
        <p>All plans include a 14-day free trial. No credit card required to start.</p>
        <p>Questions? Email <strong>sportstalks786@gmail.com</strong></p>
      </div>
    </div>
  )
}

// ── Commander AI Tab ──────────────────────────────────────────────────────────
function CommanderTab() {
  const { token }   = useAuth()
  const [health,    setHealth]    = useState(null)
  const [alerts,    setAlerts]    = useState([])
  const [agents,    setAgents]    = useState([])
  const [chatLog,   setChatLog]   = useState([
    { role: 'ai', text: "Hello, Admin. I'm **EZ-NEXUS COMMANDER AI** — the master intelligence of this platform.\n\nI monitor all your agents, track system health, detect issues before they become problems, and can generate new AI agents on demand.\n\nHow can I help you today?" }
  ])
  const [input,     setInput]     = useState('')
  const [genInput,  setGenInput]  = useState('')
  const [genResult, setGenResult] = useState(null)
  const [activePanel, setActivePanel] = useState('chat')
  const [loading,   setLoading]   = useState(false)
  const [genLoading, setGenLoading] = useState(false)
  const [error,     setError]     = useState('')
  const chatEndRef = useRef(null)

  const loadHealth = useCallback(async () => {
    try {
      const h = await apiFetch('/commander/health')
      setHealth(h)
    } catch (e) { setError(e.message) }
  }, [])

  const loadAlerts = useCallback(async () => {
    try {
      const a = await apiFetch('/commander/alerts?limit=30')
      setAlerts(a)
    } catch (e) {}
  }, [])

  const loadAgents = useCallback(async () => {
    try {
      const a = await apiFetch('/commander/agents')
      setAgents(a)
    } catch (e) {}
  }, [])

  useEffect(() => {
    loadHealth(); loadAlerts(); loadAgents()
    const interval = setInterval(loadHealth, 30000)
    return () => clearInterval(interval)
  }, [loadHealth, loadAlerts, loadAgents])

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chatLog])

  const sendChat = async (e) => {
    e.preventDefault()
    if (!input.trim()) return
    const msg = input.trim(); setInput('')
    setChatLog(prev => [...prev, { role: 'user', text: msg }])
    setLoading(true)
    try {
      const res = await apiFetch('/commander/chat', { method: 'POST', body: JSON.stringify({ message: msg }) })
      setChatLog(prev => [...prev, { role: 'ai', text: res.reply }])
    } catch (e) {
      setChatLog(prev => [...prev, { role: 'ai', text: `Error: ${e.message}` }])
    }
    setLoading(false)
  }

  const generateAgent = async (e) => {
    e.preventDefault()
    if (!genInput.trim()) return
    setGenLoading(true); setGenResult(null); setError('')
    try {
      const spec = await authFetch('/commander/generate-agent', token, {
        method: 'POST',
        body: JSON.stringify({ description: genInput }),
      })
      setGenResult(spec)
      loadAgents()
    } catch (e) { setError(e.message) }
    setGenLoading(false)
  }

  const approveAgent = async (id) => {
    try {
      await authFetch(`/commander/agents/${id}/approve`, token, { method: 'PUT' })
      loadAgents()
    } catch (e) { setError(e.message) }
  }

  const markAllRead = async () => {
    try {
      await apiFetch('/commander/alerts/read-all', { method: 'PUT' })
      loadAlerts()
    } catch (e) {}
  }

  const SEVERITY_COLOR = { critical: '#EF4444', warning: '#F59E0B', info: '#3B82F6' }

  return (
    <div className="commander-wrap">
      {/* ── Header ── */}
      <div className="commander-header">
        <div className="commander-brain">
          <span className="commander-brain-icon">🧠</span>
          <div>
            <h2 className="commander-title">EZ-NEXUS COMMANDER AI</h2>
            <p className="commander-sub">Central Intelligence Layer — Supervising {health?.agent_roster?.filter(a => a.status === 'active').length ?? '—'} Active Agents</p>
          </div>
        </div>
        <div className="commander-status-pills">
          <span className={`cmd-pill ${health?.checks?.ai_engine?.status === 'configured' ? 'cmd-pill--ok' : 'cmd-pill--warn'}`}>
            🤖 AI {health?.checks?.ai_engine?.status === 'configured' ? 'Online' : 'Offline'}
          </span>
          <span className={`cmd-pill ${health?.checks?.twilio?.status === 'configured' ? 'cmd-pill--ok' : 'cmd-pill--warn'}`}>
            📞 Calls {health?.checks?.twilio?.status === 'configured' ? 'Live' : 'TEST'}
          </span>
          <span className={`cmd-pill ${health?.checks?.smtp_email?.status === 'configured' ? 'cmd-pill--ok' : 'cmd-pill--warn'}`}>
            ✉️ Email {health?.checks?.smtp_email?.status === 'configured' ? 'Live' : 'OFF'}
          </span>
        </div>
      </div>

      {/* ── Sub Nav ── */}
      <div className="commander-nav">
        {[['chat','💬 Chat with Commander'],['health','❤️ System Health'],['agents','🤖 Agent Roster'],['create','⚡ Create Agent'],['alerts','🔔 Alerts' + (alerts.filter(a=>!a.is_read).length > 0 ? ` (${alerts.filter(a=>!a.is_read).length})` : '')]].map(([id, label]) => (
          <button key={id} className={`commander-nav-btn ${activePanel === id ? 'active' : ''}`} onClick={() => setActivePanel(id)}>
            {label}
          </button>
        ))}
      </div>

      {error && <Alert msg={error} type="error" />}

      {/* ── CHAT ── */}
      {activePanel === 'chat' && (
        <div className="cmd-chat-wrap">
          <div className="cmd-chat-log">
            {chatLog.map((m, i) => (
              <div key={i} className={`cmd-msg cmd-msg--${m.role}`}>
                <div className="cmd-msg-avatar">{m.role === 'ai' ? '🧠' : '👤'}</div>
                <div className="cmd-msg-bubble">
                  {m.text.split('\n').map((line, j) => (
                    <span key={j}>{line.replace(/\*\*(.*?)\*\*/g, '$1')}<br /></span>
                  ))}
                </div>
              </div>
            ))}
            {loading && (
              <div className="cmd-msg cmd-msg--ai">
                <div className="cmd-msg-avatar">🧠</div>
                <div className="cmd-msg-bubble cmd-msg-typing"><span /><span /><span /></div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
          <form className="cmd-chat-form" onSubmit={sendChat}>
            <input
              className="form-input"
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Ask Commander AI anything… e.g. 'Check system health' or 'Create a dental insurance agent'"
              disabled={loading}
            />
            <button className="btn btn-primary" type="submit" disabled={loading || !input.trim()}>Send</button>
          </form>
          <div className="cmd-quick-btns">
            {['Check system health','What needs my attention today?','How many appointments this week?','What agents are coming soon?'].map(q => (
              <button key={q} className="cmd-quick-btn" onClick={() => setInput(q)}>{q}</button>
            ))}
          </div>
        </div>
      )}

      {/* ── HEALTH ── */}
      {activePanel === 'health' && health && (
        <div>
          <div className="health-grid">
            {Object.entries(health.checks).map(([key, val]) => (
              <div key={key} className={`health-card health-card--${val.status === 'ok' || val.status === 'configured' ? 'ok' : val.status === 'error' ? 'error' : 'warn'}`}>
                <div className="health-card-title">{key.replace(/_/g, ' ').toUpperCase()}</div>
                <div className={`health-card-status health-status--${val.status === 'ok' || val.status === 'configured' ? 'ok' : val.status === 'error' ? 'error' : 'warn'}`}>
                  {val.status === 'ok' || val.status === 'configured' ? '✅' : val.status === 'error' ? '❌' : '⚠️'} {val.status}
                </div>
                {Object.entries(val).filter(([k]) => k !== 'status').map(([k, v]) => (
                  <div key={k} className="health-card-detail">{k}: <strong>{String(v)}</strong></div>
                ))}
              </div>
            ))}
          </div>

          {health.alerts?.length > 0 && (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="card-header"><span className="card-title">⚠️ Active Issues ({health.alerts.length})</span></div>
              {health.alerts.map((a, i) => (
                <div key={i} className="health-alert" style={{ borderLeftColor: SEVERITY_COLOR[a.severity] || '#94a3b8' }}>
                  <strong style={{ color: SEVERITY_COLOR[a.severity], textTransform: 'capitalize' }}>{a.severity}</strong>
                  <span style={{ margin: '0 8px', color: '#94a3b8' }}>|</span>
                  <span>{a.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── AGENT ROSTER ── */}
      {activePanel === 'agents' && (
        <div>
          <div className="roster-grid">
            {(health?.agent_roster || AGENT_ROSTER_FALLBACK).map(agent => (
              <div key={agent.id} className={`roster-card ${agent.status === 'active' ? 'roster-card--active' : 'roster-card--soon'}`}>
                <div className="roster-icon">{agent.icon}</div>
                <div className="roster-name">{agent.name}</div>
                <div className={`roster-status ${agent.status === 'active' ? 'roster-status--active' : 'roster-status--soon'}`}>
                  {agent.status === 'active' ? '● Active' : '○ Coming Soon'}
                </div>
              </div>
            ))}
          </div>

          {agents.length > 0 && (
            <div className="card" style={{ marginTop: 16 }}>
              <div className="card-header"><span className="card-title">📋 Generated Agent Specs ({agents.length})</span></div>
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Name</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead>
                  <tbody>
                    {agents.map(a => (
                      <tr key={a.id}>
                        <td><strong>{a.name}</strong></td>
                        <td><span className={`badge ${a.status === 'approved' ? 'badge-confirmed' : a.status === 'active' ? 'badge-completed' : 'badge-scheduled'}`}>{a.status}</span></td>
                        <td>{new Date(a.created_at).toLocaleDateString()}</td>
                        <td>
                          {a.status === 'draft' && (
                            <button className="btn btn-sm approval-approve" onClick={() => approveAgent(a.id)}>✅ Approve</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── CREATE AGENT ── */}
      {activePanel === 'create' && (
        <div className="card">
          <div className="card-header"><span className="card-title">⚡ Create New AI Agent</span></div>
          <p style={{ fontSize: '.85rem', color: 'var(--gray-600)', marginBottom: 16 }}>
            Describe the agent you need in plain language. Commander AI will generate a complete specification including workflow, APIs, database fields, call script, and testing checklist.
          </p>
          <form onSubmit={generateAgent} className="form">
            <div className="form-group">
              <label className="form-label">Describe the agent *</label>
              <textarea
                className="form-textarea"
                style={{ minHeight: 100 }}
                required
                placeholder={`Example: "Create an AI agent for dental insurance verification that can check patient eligibility, coverage limits, and deductibles by calling the insurance API and report results to staff before the appointment."`}
                value={genInput}
                onChange={e => setGenInput(e.target.value)}
              />
            </div>
            <button className="btn btn-primary" type="submit" disabled={genLoading}>
              {genLoading ? '🧠 Generating…' : '⚡ Generate Agent Spec'}
            </button>
          </form>

          {genResult && (
            <div className="agent-spec-result">
              <div className="agent-spec-header">
                <h3 className="agent-spec-title">{genResult.name}</h3>
                <span className={`badge ${genResult.complexity === 'high' ? 'badge-cancelled' : genResult.complexity === 'medium' ? 'badge-pending' : 'badge-completed'}`}>
                  {genResult.complexity} complexity
                </span>
                <span className="badge badge-scheduled">~{genResult.estimated_dev_days} dev days</span>
              </div>
              <p className="agent-spec-purpose">{genResult.purpose}</p>

              <div className="agent-spec-grid">
                <div className="agent-spec-section">
                  <h4>📋 Workflow</h4>
                  <ol>{genResult.workflow?.map((s, i) => <li key={i}>{s}</li>)}</ol>
                </div>
                <div className="agent-spec-section">
                  <h4>🔧 Required Tools</h4>
                  <ul>{genResult.required_tools?.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
                <div className="agent-spec-section">
                  <h4>🌐 Required APIs</h4>
                  <ul>{genResult.required_apis?.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
                <div className="agent-spec-section">
                  <h4>🗄️ Database Fields</h4>
                  <ul>{genResult.database_fields?.map((s, i) => <li key={i} style={{ fontFamily: 'monospace', fontSize: '.78rem' }}>{s}</li>)}</ul>
                </div>
              </div>

              <div className="agent-spec-section" style={{ marginTop: 12 }}>
                <h4>📞 Call Script</h4>
                <div className="agent-spec-script">{genResult.call_script}</div>
              </div>

              <div className="agent-spec-grid" style={{ marginTop: 12 }}>
                <div className="agent-spec-section">
                  <h4>✅ Testing Checklist</h4>
                  <ul>{genResult.testing_checklist?.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
                <div className="agent-spec-section">
                  <h4>🔒 Approval Rules</h4>
                  <ul>{genResult.approval_rules?.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
              </div>

              <div className="agent-spec-footer">
                <span>Est. monthly API cost: {genResult.monthly_api_cost_estimate || 'TBD'}</span>
                {genResult.agent_definition_id && (
                  <button className="btn btn-sm approval-approve" onClick={() => approveAgent(genResult.agent_definition_id)}>
                    ✅ Approve This Agent
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── ALERTS ── */}
      {activePanel === 'alerts' && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">🔔 System Alerts ({alerts.filter(a => !a.is_read).length} unread)</span>
            {alerts.some(a => !a.is_read) && (
              <button className="btn btn-outline btn-sm" onClick={markAllRead}>Mark All Read</button>
            )}
          </div>
          {alerts.length === 0 ? (
            <div className="empty"><div className="empty-icon">🔔</div><p>No alerts yet. System looks clean!</p></div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '4px 0' }}>
              {alerts.map(a => (
                <div key={a.id} className={`health-alert ${a.is_read ? 'health-alert--read' : ''}`}
                     style={{ borderLeftColor: SEVERITY_COLOR[a.severity] || '#94a3b8' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                    <div>
                      <strong style={{ color: SEVERITY_COLOR[a.severity], textTransform: 'capitalize' }}>{a.severity}</strong>
                      <span className="badge badge-scheduled" style={{ marginLeft: 8, fontSize: '.7rem' }}>{a.module}</span>
                      <p style={{ margin: '4px 0 0', fontSize: '.85rem' }}>{a.message}</p>
                    </div>
                    <span style={{ fontSize: '.75rem', color: 'var(--gray-400)', whiteSpace: 'nowrap' }}>
                      {new Date(a.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Website Builder Tab ──────────────────────────────────────────────────────
const WB_THEMES = [
  { id: 'blue',   name: 'Corporate', swatch: '#1B4FD8' },
  { id: 'teal',   name: 'Fresh',     swatch: '#0F766E' },
  { id: 'purple', name: 'Creative',  swatch: '#7C3AED' },
  { id: 'dark',   name: 'Executive', swatch: '#1e293b' },
]

function WebsiteBuilderTab() {
  const [step, setStep]           = useState('form')
  const [form, setForm]           = useState({ business_name:'', industry:'', tagline:'', description:'', services:'', phone:'', email:'', address:'', color_theme:'blue' })
  const [loading, setLoading]     = useState(false)
  const [websiteHtml, setWebsite] = useState('')
  const [error, setError]         = useState('')

  const generate = async (e) => {
    e.preventDefault(); setLoading(true); setError('')
    try {
      const res = await apiFetch('/ai/build-website', { method: 'POST', body: JSON.stringify(form) })
      setWebsite(res.html); setStep('preview')
    } catch (e) { setError(e.message) }
    setLoading(false)
  }

  const download = () => {
    const blob = new Blob([websiteHtml], { type: 'text/html' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = `${form.business_name.replace(/\s/g,'_') || 'website'}.html`
    document.body.appendChild(a); a.click(); URL.revokeObjectURL(url); a.remove()
  }

  return (
    <div>
      <div className="wb-hero">
        <div className="wb-hero-title">🖥️ AI Website Builder</div>
        <div className="wb-hero-sub">Generate a complete professional website for any business in seconds — powered by Commander AI</div>
      </div>
      <Alert msg={error} type="error" />

      {step === 'form' && (
        <div className="card">
          <div className="card-header"><span className="card-title">Business Details</span></div>
          <form onSubmit={generate}>
            <div className="wb-form-grid" style={{ marginBottom: 14 }}>
              <div className="form-group">
                <label className="form-label">Business Name *</label>
                <input className="form-input" required placeholder="e.g. Dr. Ahmed Family Clinic" value={form.business_name} onChange={e => setForm(f=>({...f,business_name:e.target.value}))} />
              </div>
              <div className="form-group">
                <label className="form-label">Industry *</label>
                <input className="form-input" required placeholder="e.g. Healthcare, Dental, Retail" value={form.industry} onChange={e => setForm(f=>({...f,industry:e.target.value}))} />
              </div>
              <div className="form-group">
                <label className="form-label">Tagline</label>
                <input className="form-input" placeholder="e.g. Caring for your family since 2005" value={form.tagline} onChange={e => setForm(f=>({...f,tagline:e.target.value}))} />
              </div>
              <div className="form-group">
                <label className="form-label">Phone</label>
                <input className="form-input" placeholder="+1 555 000 0000" value={form.phone} onChange={e => setForm(f=>({...f,phone:e.target.value}))} />
              </div>
              <div className="form-group">
                <label className="form-label">Email</label>
                <input className="form-input" type="email" placeholder="info@business.com" value={form.email} onChange={e => setForm(f=>({...f,email:e.target.value}))} />
              </div>
              <div className="form-group">
                <label className="form-label">Address</label>
                <input className="form-input" placeholder="123 Main St, City, State" value={form.address} onChange={e => setForm(f=>({...f,address:e.target.value}))} />
              </div>
              <div className="form-group" style={{ gridColumn:'1/-1' }}>
                <label className="form-label">Services (comma-separated)</label>
                <input className="form-input" placeholder="e.g. General Check-ups, Vaccinations, Lab Tests" value={form.services} onChange={e => setForm(f=>({...f,services:e.target.value}))} />
              </div>
              <div className="form-group" style={{ gridColumn:'1/-1' }}>
                <label className="form-label">About / Description</label>
                <textarea className="form-textarea" style={{ minHeight:70 }} placeholder="What makes your business special?" value={form.description} onChange={e => setForm(f=>({...f,description:e.target.value}))} />
              </div>
            </div>

            <div className="form-group" style={{ marginBottom: 20 }}>
              <label className="form-label">Color Theme</label>
              <div className="wb-theme-grid">
                {WB_THEMES.map(th => (
                  <button key={th.id} type="button" className={`wb-theme-btn ${form.color_theme===th.id?'active':''}`} onClick={() => setForm(f=>({...f,color_theme:th.id}))}>
                    <div className="wb-theme-swatch" style={{ background: th.swatch }} />
                    {th.name}
                  </button>
                ))}
              </div>
            </div>

            <button className="btn btn-primary" type="submit" disabled={loading} style={{ width:'100%', fontSize:'1rem', padding:'12px' }}>
              {loading ? '🧠 Commander AI is building your website…' : '🚀 Generate Website'}
            </button>
          </form>
        </div>
      )}

      {step === 'preview' && (
        <div>
          <div style={{ display:'flex', gap:10, marginBottom:16, justifyContent:'space-between', flexWrap:'wrap' }}>
            <div style={{ display:'flex', gap:8 }}>
              <button className="btn btn-primary" onClick={download}>⬇ Download HTML</button>
              <button className="btn btn-outline" onClick={() => setStep('form')}>✏ Edit Details</button>
            </div>
            <div style={{ fontSize:'.82rem', color:'var(--gray-400)', alignSelf:'center' }}>✅ Download and host anywhere — works on any web host</div>
          </div>
          <div className="wb-preview-bar">
            <div className="wb-dot" style={{ background:'#ef4444' }} />
            <div className="wb-dot" style={{ background:'#f59e0b' }} />
            <div className="wb-dot" style={{ background:'#22c55e' }} />
            <div style={{ flex:1, background:'#334155', borderRadius:4, padding:'3px 12px', color:'#94a3b8', fontSize:'.75rem' }}>
              {form.business_name || 'My Business'} — AI Generated Website Preview
            </div>
          </div>
          <iframe className="wb-preview-iframe" srcDoc={websiteHtml} title="Website Preview" sandbox="allow-scripts" />
        </div>
      )}
    </div>
  )
}

// ── Content Studio Tab ─────────────────────────────────────────────────────
const CS_TYPES = [
  { id:'instagram_post', icon:'📸', label:'Instagram Post',  desc:'Caption + hashtags' },
  { id:'facebook_post',  icon:'👍', label:'Facebook Post',    desc:'Engaging post' },
  { id:'linkedin_post',  icon:'💼', label:'LinkedIn Post',    desc:'Professional update' },
  { id:'blog_article',   icon:'📝', label:'Blog Article',     desc:'SEO-ready content' },
  { id:'email_campaign', icon:'📧', label:'Email Campaign',   desc:'Subject + body' },
  { id:'video_script',   icon:'🎬', label:'Video Script',     desc:'Hook + content + CTA' },
]
const CS_VOICES = ['professional','friendly','urgent','inspiring','humorous','educational']

function ContentStudioTab() {
  const [contentType, setType] = useState('instagram_post')
  const [form, setForm]        = useState({ topic:'', brand_voice:'professional', target_audience:'', keywords:'' })
  const [loading, setLoading]  = useState(false)
  const [result, setResult]    = useState(null)
  const [error, setError]      = useState('')
  const [copied, setCopied]    = useState(false)
  const [history, setHistory]  = useState([])

  const generate = async (e) => {
    e.preventDefault(); setLoading(true); setError(''); setResult(null)
    try {
      const res = await apiFetch('/ai/generate-content', { method:'POST', body: JSON.stringify({ content_type: contentType, ...form }) })
      setResult(res)
      setHistory(prev => [{ contentType, topic: form.topic, content: res.content, ts: new Date().toISOString() }, ...prev.slice(0,9)])
    } catch (e) { setError(e.message) }
    setLoading(false)
  }

  const copy = () => {
    if (!result?.content) return
    const text = result.content + (result.hashtags?.length ? '\n\n' + result.hashtags.join(' ') : '')
    navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000)
  }

  const curType = CS_TYPES.find(t => t.id === contentType)

  return (
    <div>
      <div className="cs-hero">
        <div style={{ fontSize:'1.8rem', fontWeight:800, marginBottom:6 }}>🎬 Content Studio</div>
        <div style={{ color:'rgba(255,255,255,.7)', fontSize:'.9rem' }}>AI-powered content for every platform — posts, blogs, emails, scripts, and more</div>
      </div>
      <Alert msg={error} type="error" />

      <div className="card">
        <div className="card-header"><span className="card-title">Choose Content Type</span></div>
        <div className="cs-type-grid">
          {CS_TYPES.map(t => (
            <button key={t.id} type="button" className={`cs-type-btn ${contentType===t.id?'active':''}`} onClick={() => setType(t.id)}>
              <span className="cs-type-icon">{t.icon}</span>
              <span className="cs-type-label">{t.label}</span>
              <span className="cs-type-desc">{t.desc}</span>
            </button>
          ))}
        </div>
      </div>

      <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16, alignItems:'flex-start' }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Content Details</span></div>
          <form onSubmit={generate} className="form">
            <div className="form-group">
              <label className="form-label">Topic / Subject *</label>
              <input className="form-input" required placeholder="e.g. Summer sale 30% off, New product launch, Patient testimonial..." value={form.topic} onChange={e => setForm(f=>({...f,topic:e.target.value}))} />
            </div>
            <div className="form-group">
              <label className="form-label">Brand Voice</label>
              <select className="form-select" value={form.brand_voice} onChange={e => setForm(f=>({...f,brand_voice:e.target.value}))}>
                {CS_VOICES.map(v => <option key={v} value={v}>{v.charAt(0).toUpperCase()+v.slice(1)}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Target Audience</label>
              <input className="form-input" placeholder="e.g. Small business owners, parents 25-45" value={form.target_audience} onChange={e => setForm(f=>({...f,target_audience:e.target.value}))} />
            </div>
            <div className="form-group">
              <label className="form-label">Keywords (comma-separated)</label>
              <input className="form-input" placeholder="e.g. dental care, smile, family" value={form.keywords} onChange={e => setForm(f=>({...f,keywords:e.target.value}))} />
            </div>
            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? `✨ Generating ${curType?.label}…` : `✨ Generate ${curType?.label}`}
            </button>
          </form>
        </div>

        <div>
          {result ? (
            <div className="cs-result-box">
              <div className="cs-result-header">
                <span className="cs-result-title">{curType?.icon} {curType?.label}</span>
                <button className="btn btn-outline btn-sm" onClick={copy} style={{ color:'#60a5fa', borderColor:'#60a5fa' }}>
                  {copied ? '✅ Copied!' : '📋 Copy All'}
                </button>
              </div>
              <div className="cs-result-content">{result.content}</div>
              {result.subject && (
                <div style={{ marginTop:12, padding:'10px 12px', background:'rgba(27,79,216,.12)', borderRadius:6 }}>
                  <span style={{ color:'#60a5fa', fontSize:'.78rem', fontWeight:700 }}>Subject Line: </span>
                  <span style={{ color:'#e2e8f0', fontSize:'.85rem' }}>{result.subject}</span>
                </div>
              )}
              {result.hashtags?.length > 0 && (
                <div className="cs-hashtags">
                  {result.hashtags.map((h,i) => <span key={i} className="cs-hashtag">{h}</span>)}
                </div>
              )}
            </div>
          ) : (
            <div className="card" style={{ textAlign:'center', padding:'48px 24px', color:'var(--gray-400)' }}>
              <div style={{ fontSize:'3rem', marginBottom:12 }}>✨</div>
              <p style={{ fontSize:'.9rem' }}>Fill in the details and click generate to create your content</p>
            </div>
          )}

          {history.length > 0 && (
            <div className="card" style={{ marginTop:14 }}>
              <div className="card-header"><span className="card-title" style={{ fontSize:'.85rem' }}>Recent Generations</span></div>
              {history.slice(0,4).map((h,i) => (
                <div key={i} style={{ padding:'8px 0', borderBottom:'1px solid var(--gray-100)', cursor:'pointer' }} onClick={() => setResult({ content: h.content, hashtags:[], subject: null })}>
                  <div style={{ fontSize:'.72rem', color:'var(--gray-400)' }}>{new Date(h.ts).toLocaleTimeString()}</div>
                  <div style={{ fontSize:'.82rem', fontWeight:600, color:'var(--gray-900)' }}>{h.topic}</div>
                  <div style={{ fontSize:'.78rem', color:'var(--gray-600)' }}>{h.content.slice(0,70)}…</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Invoices Tab ───────────────────────────────────────────────────────────
const EMPTY_ITEM = { description:'', quantity:'1', unit_price:'' }

function InvoicesTab() {
  const [invoices, setInvoices]     = useState([])
  const [businesses, setBusinesses] = useState([])
  const [loading, setLoading]       = useState(true)
  const [error, setError]           = useState('')
  const [success, setSuccess]       = useState('')
  const [showForm, setShowForm]     = useState(false)
  const [viewInvoice, setView]      = useState(null)
  const [form, setForm]             = useState({ business_id:'', client_name:'', client_email:'', client_phone:'', client_address:'', due_date:'', notes:'', tax_rate:'0' })
  const [items, setItems]           = useState([{...EMPTY_ITEM}])

  const subtotal = items.reduce((s,it) => s + parseFloat(it.quantity||0) * parseFloat(it.unit_price||0), 0)
  const taxRate  = parseFloat(form.tax_rate||0) / 100
  const taxAmt   = subtotal * taxRate
  const total    = subtotal + taxAmt
  const fmt$     = (n) => `$${(n||0).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g,',')}`

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [inv, biz] = await Promise.all([apiFetch('/invoices'), apiFetch('/businesses')])
      setInvoices(inv); setBusinesses(biz)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  const addItem    = () => setItems(p => [...p, {...EMPTY_ITEM}])
  const removeItem = (i) => setItems(p => p.filter((_,idx) => idx !== i))
  const updItem    = (i,f,v) => setItems(p => p.map((it,idx) => idx===i ? {...it,[f]:v} : it))

  const handleSubmit = async (e) => {
    e.preventDefault(); setError(''); setSuccess('')
    try {
      await apiFetch('/invoices', {
        method:'POST',
        body: JSON.stringify({
          ...form,
          business_id: parseInt(form.business_id),
          tax_rate: parseFloat(form.tax_rate||0),
          items: items.map(it => ({ description:it.description, quantity:parseFloat(it.quantity||1), unit_price:parseFloat(it.unit_price||0), total:parseFloat(it.quantity||1)*parseFloat(it.unit_price||0) }))
        })
      })
      setSuccess('Invoice created!'); setShowForm(false)
      setForm({ business_id:'', client_name:'', client_email:'', client_phone:'', client_address:'', due_date:'', notes:'', tax_rate:'0' })
      setItems([{...EMPTY_ITEM}]); load()
    } catch (e) { setError(e.message) }
  }

  const updateStatus  = async (id, status) => {
    try { await apiFetch(`/invoices/${id}`, { method:'PUT', body: JSON.stringify({ status }) }); load() } catch (e) { setError(e.message) }
  }
  const deleteInvoice = async (id) => {
    if (!confirm('Delete this invoice?')) return
    try { await apiFetch(`/invoices/${id}`, { method:'DELETE' }); load() } catch (e) { setError(e.message) }
  }

  const totalInvoiced = invoices.reduce((s,inv) => s + (inv.total||0), 0)
  const totalPaid     = invoices.filter(inv => inv.status==='paid').reduce((s,inv) => s + (inv.total||0), 0)
  const totalPending  = invoices.filter(inv => inv.status==='sent').reduce((s,inv) => s + (inv.total||0), 0)
  const totalOverdue  = invoices.filter(inv => inv.status==='overdue').length
  const STATUS_BADGE  = { draft:'inv-badge-draft', sent:'inv-badge-sent', paid:'inv-badge-paid', overdue:'inv-badge-overdue' }

  return (
    <div>
      <Alert msg={error} type="error" />
      <Alert msg={success} type="success" />

      {/* Stats */}
      <div className="inv-stats">
        {[
          { label:'Total Invoiced', val: fmt$(totalInvoiced), color:'#1B4FD8' },
          { label:'Paid',           val: fmt$(totalPaid),     color:'#22c55e' },
          { label:'Pending',        val: fmt$(totalPending),  color:'#f59e0b' },
          { label:'Overdue',        val: String(totalOverdue),color:'#ef4444' },
        ].map((s,i) => (
          <div key={i} className="inv-stat" style={{ borderColor: s.color }}>
            <div className="inv-stat-label">{s.label}</div>
            <div className="inv-stat-value" style={{ color: s.color }}>{s.val}</div>
          </div>
        ))}
      </div>

      {/* Invoice List */}
      {!showForm && !viewInvoice && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">📄 Invoices ({invoices.length})</span>
            <button className="btn btn-primary btn-sm" onClick={() => setShowForm(true)}>+ New Invoice</button>
          </div>
          {loading ? <Spinner /> : invoices.length === 0 ? (
            <div className="empty"><div className="empty-icon">📄</div><p>No invoices yet. Create your first one above.</p></div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Client</th><th>Business</th><th>Issue Date</th><th>Due</th><th>Total</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>
                  {invoices.map(inv => (
                    <tr key={inv.id}>
                      <td style={{ fontFamily:'monospace', fontWeight:700, color:'var(--blue)' }}>{inv.invoice_number}</td>
                      <td>
                        <strong>{inv.client_name}</strong>
                        {inv.client_email && <div style={{ fontSize:'.75rem', color:'var(--gray-600)' }}>{inv.client_email}</div>}
                      </td>
                      <td style={{ fontSize:'.8rem' }}>{businesses.find(b=>b.id===inv.business_id)?.name || `#${inv.business_id}`}</td>
                      <td style={{ fontSize:'.8rem' }}>{new Date(inv.created_at).toLocaleDateString()}</td>
                      <td style={{ fontSize:'.8rem', color: inv.status==='overdue' ? '#ef4444' : 'inherit' }}>
                        {inv.due_date ? new Date(inv.due_date).toLocaleDateString() : '—'}
                      </td>
                      <td style={{ fontWeight:700, color:'var(--navy)' }}>{fmt$(inv.total)}</td>
                      <td><span className={`badge ${STATUS_BADGE[inv.status]||'badge-scheduled'}`}>{inv.status}</span></td>
                      <td>
                        <div style={{ display:'flex', gap:4, flexWrap:'wrap' }}>
                          <button className="btn btn-outline btn-sm" onClick={() => setView(inv)}>View</button>
                          {inv.status === 'draft' && <button className="btn btn-teal btn-sm" onClick={() => updateStatus(inv.id,'sent')}>Send</button>}
                          {inv.status === 'sent'  && <button className="btn btn-sm" style={{ background:'#dcfce7', color:'#166534', border:'none' }} onClick={() => updateStatus(inv.id,'paid')}>✓ Paid</button>}
                          <button className="btn btn-danger btn-sm" onClick={() => deleteInvoice(inv.id)}>✕</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Create Form */}
      {showForm && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">Create New Invoice</span>
            <button className="btn btn-outline btn-sm" onClick={() => setShowForm(false)}>✕ Cancel</button>
          </div>
          <form onSubmit={handleSubmit}>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:12, marginBottom:16 }}>
              <div className="form-group">
                <label className="form-label">Business *</label>
                <select className="form-select" required value={form.business_id} onChange={e => setForm(f=>({...f,business_id:e.target.value}))}>
                  <option value="">Select Business</option>
                  {businesses.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Client Name *</label>
                <input className="form-input" required value={form.client_name} onChange={e => setForm(f=>({...f,client_name:e.target.value}))} />
              </div>
              <div className="form-group">
                <label className="form-label">Client Email</label>
                <input className="form-input" type="email" value={form.client_email} onChange={e => setForm(f=>({...f,client_email:e.target.value}))} />
              </div>
              <div className="form-group">
                <label className="form-label">Due Date</label>
                <input className="form-input" type="date" value={form.due_date} onChange={e => setForm(f=>({...f,due_date:e.target.value}))} />
              </div>
              <div className="form-group" style={{ gridColumn:'1/-1' }}>
                <label className="form-label">Client Address</label>
                <input className="form-input" placeholder="Billing address" value={form.client_address} onChange={e => setForm(f=>({...f,client_address:e.target.value}))} />
              </div>
            </div>

            {/* Line Items */}
            <div style={{ marginBottom:16 }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:8 }}>
                <label className="form-label" style={{ margin:0 }}>Line Items *</label>
                <button type="button" className="btn btn-outline btn-sm" onClick={addItem}>+ Add Item</button>
              </div>
              <table className="inv-items-table">
                <thead><tr><th style={{ minWidth:200 }}>Description</th><th style={{ width:70 }}>Qty</th><th style={{ width:110 }}>Unit Price</th><th style={{ width:100 }}>Total</th><th style={{ width:40 }}></th></tr></thead>
                <tbody>
                  {items.map((it,i) => (
                    <tr key={i}>
                      <td><input className="form-input" placeholder="Service or product" value={it.description} onChange={e => updItem(i,'description',e.target.value)} required /></td>
                      <td><input className="form-input" type="number" min="1" step="0.5" value={it.quantity} onChange={e => updItem(i,'quantity',e.target.value)} style={{ padding:'7px 8px' }} /></td>
                      <td><input className="form-input" type="number" min="0" step="0.01" placeholder="0.00" value={it.unit_price} onChange={e => updItem(i,'unit_price',e.target.value)} style={{ padding:'7px 8px' }} /></td>
                      <td style={{ fontWeight:700 }}>{fmt$(parseFloat(it.quantity||0)*parseFloat(it.unit_price||0))}</td>
                      <td>{items.length > 1 && <button type="button" className="btn btn-danger btn-sm" onClick={() => removeItem(i)} style={{ padding:'4px 8px' }}>✕</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="inv-totals">
                <div className="inv-total-row"><span>Subtotal</span><span>{fmt$(subtotal)}</span></div>
                <div className="inv-total-row">
                  <span>Tax&nbsp;
                    <input type="number" min="0" max="100" step="0.5" value={form.tax_rate}
                      onChange={e => setForm(f=>({...f,tax_rate:e.target.value}))}
                      style={{ width:45, fontSize:'.8rem', padding:'2px 5px', border:'1px solid #e2e8f0', borderRadius:4 }} />%
                  </span>
                  <span>{fmt$(taxAmt)}</span>
                </div>
                <div className="inv-total-row grand"><span>Total</span><span>{fmt$(total)}</span></div>
              </div>
            </div>

            <div className="form-group" style={{ marginBottom:16 }}>
              <label className="form-label">Notes / Payment Terms</label>
              <textarea className="form-textarea" style={{ minHeight:60 }} placeholder="e.g. Payment due within 30 days. Thank you for your business!" value={form.notes} onChange={e => setForm(f=>({...f,notes:e.target.value}))} />
            </div>
            <div style={{ display:'flex', gap:8 }}>
              <button className="btn btn-primary" type="submit">💾 Save Invoice</button>
              <button className="btn btn-outline" type="button" onClick={() => setShowForm(false)}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      {/* View / Print Invoice */}
      {viewInvoice && (() => {
        let parsedItems = []
        try { parsedItems = typeof viewInvoice.items === 'string' ? JSON.parse(viewInvoice.items) : (viewInvoice.items||[]) } catch {}
        const biz = businesses.find(b => b.id === viewInvoice.business_id)
        return (
          <div className="card" id="inv-print">
            <div className="card-header inv-actions">
              <span className="card-title">Invoice {viewInvoice.invoice_number}</span>
              <div style={{ display:'flex', gap:8 }}>
                <button className="btn btn-primary btn-sm" onClick={() => window.print()}>🖨 Print / PDF</button>
                <button className="btn btn-outline btn-sm" onClick={() => setView(null)}>← Back to Invoices</button>
              </div>
            </div>
            <div style={{ display:'flex', justifyContent:'space-between', marginBottom:28, flexWrap:'wrap', gap:16 }}>
              <div>
                <div style={{ fontSize:'1.4rem', fontWeight:900, color:'var(--navy)' }}>{biz?.name || 'Business'}</div>
                <div style={{ color:'var(--gray-600)', fontSize:'.85rem', marginTop:4, lineHeight:1.8 }}>
                  {biz?.email && <div>{biz.email}</div>}{biz?.phone && <div>{biz.phone}</div>}{biz?.address && <div>{biz.address}</div>}
                </div>
              </div>
              <div style={{ textAlign:'right' }}>
                <div style={{ fontSize:'2rem', fontWeight:900, color:'var(--blue)' }}>INVOICE</div>
                <div style={{ fontFamily:'monospace', color:'var(--gray-600)' }}>{viewInvoice.invoice_number}</div>
                <div style={{ marginTop:8 }}>
                  <span className={`badge ${STATUS_BADGE[viewInvoice.status]||'badge-scheduled'}`} style={{ fontSize:'.85rem', padding:'5px 14px' }}>
                    {viewInvoice.status.toUpperCase()}
                  </span>
                </div>
              </div>
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:20, marginBottom:24, padding:'16px 0', borderTop:'1px solid var(--gray-200)', borderBottom:'1px solid var(--gray-200)' }}>
              <div>
                <div style={{ fontWeight:700, color:'var(--gray-600)', fontSize:'.75rem', marginBottom:6, textTransform:'uppercase', letterSpacing:'.5px' }}>Bill To</div>
                <div style={{ fontWeight:700 }}>{viewInvoice.client_name}</div>
                <div style={{ color:'var(--gray-600)', fontSize:'.85rem', lineHeight:1.7 }}>
                  {viewInvoice.client_email && <div>{viewInvoice.client_email}</div>}
                  {viewInvoice.client_phone && <div>{viewInvoice.client_phone}</div>}
                  {viewInvoice.client_address && <div>{viewInvoice.client_address}</div>}
                </div>
              </div>
              <div style={{ textAlign:'right', fontSize:'.85rem', color:'var(--gray-600)' }}>
                <div><strong>Issue Date:</strong> {new Date(viewInvoice.created_at).toLocaleDateString()}</div>
                {viewInvoice.due_date && <div style={{ marginTop:4 }}><strong>Due Date:</strong> {new Date(viewInvoice.due_date).toLocaleDateString()}</div>}
              </div>
            </div>
            <table className="inv-items-table">
              <thead><tr><th>Description</th><th>Qty</th><th>Unit Price</th><th style={{ textAlign:'right' }}>Total</th></tr></thead>
              <tbody>
                {parsedItems.map((it,i) => (
                  <tr key={i}>
                    <td>{it.description}</td>
                    <td>{it.quantity}</td>
                    <td>{fmt$(it.unit_price)}</td>
                    <td style={{ textAlign:'right', fontWeight:600 }}>{fmt$(it.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="inv-totals">
              <div className="inv-total-row"><span>Subtotal</span><span>{fmt$(viewInvoice.subtotal)}</span></div>
              {viewInvoice.tax_rate > 0 && <div className="inv-total-row"><span>Tax ({viewInvoice.tax_rate}%)</span><span>{fmt$(viewInvoice.tax_amount)}</span></div>}
              <div className="inv-total-row grand"><span>Total Due</span><span>{fmt$(viewInvoice.total)}</span></div>
            </div>
            {viewInvoice.notes && (
              <div style={{ marginTop:20, padding:'12px 16px', background:'var(--blue-light)', borderRadius:6 }}>
                <strong style={{ fontSize:'.8rem', color:'var(--blue)' }}>Notes:</strong>
                <p style={{ fontSize:'.85rem', margin:'4px 0 0', color:'var(--gray-600)' }}>{viewInvoice.notes}</p>
              </div>
            )}
          </div>
        )
      })()}
    </div>
  )
}

// ── E-Commerce / Product Hunting Tab ────────────────────────────────────────
const ECOM_MARKETPLACES = ['Amazon','eBay','Shopify','Walmart','Etsy','TikTok Shop','Facebook Marketplace']
const ECOM_CATEGORIES   = ['Home & Kitchen','Electronics','Pet Supplies','Beauty','Fitness','Kids','Outdoor','Office','Automotive']
const SCORE_COLOR = s => s >= 80 ? '#10b981' : s >= 65 ? '#f59e0b' : '#ef4444'

function ScoreBar({ label, value }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display:'flex', justifyContent:'space-between', fontSize:'.75rem', color:'#94a3b8', marginBottom:2 }}>
        <span>{label}</span><span style={{ color: SCORE_COLOR(value), fontWeight:700 }}>{value}</span>
      </div>
      <div style={{ background:'#1e293b', borderRadius:4, height:6 }}>
        <div style={{ width:`${value}%`, height:'100%', borderRadius:4, background: SCORE_COLOR(value), transition:'width .4s' }} />
      </div>
    </div>
  )
}

function EcommerceTab() {
  const [panel, setPanel]             = React.useState('hunter')
  const [huntForm, setHuntForm]       = React.useState({ category:'Home & Kitchen', marketplace:'Amazon', keywords:'', budget:'50' })
  const [hunting, setHunting]         = React.useState(false)
  const [huntResults, setHuntResults] = React.useState([])
  const [huntSummary, setHuntSummary] = React.useState('')
  const [products, setProducts]       = React.useState([])
  const [listings, setListings]       = React.useState([])
  const [ecomStats, setEcomStats]     = React.useState({})

  // Dropship directory states
  const [dsSuppliers, setDsSuppliers]   = React.useState([])
  const DS_EMPTY = { region:'', platform_type:'', has_usa_warehouse:'', dropship_ready:'', search:'' }
  const [dsFilter, setDsFilter]         = React.useState(DS_EMPTY)
  const [dsLoading, setDsLoading]       = React.useState(false)
  const [dsSelected, setDsSelected]     = React.useState(null)
  const dsFilterRef                     = React.useRef(DS_EMPTY)

  const [profitForm, setProfitForm]   = React.useState({
    selling_price:'', product_cost:'', marketplace_fee:'', shipping_cost:'',
    packaging_cost:'', advertising_cost:'', return_allowance:'', other_costs:''
  })
  const [profitResult, setProfitResult] = React.useState(null)

  const [listForm, setListForm]   = React.useState({
    marketplace:'Amazon', product_name:'', features:'', target_audience:'general consumers',
    keywords:'', brand_voice:'professional'
  })
  const [listing, setListing]     = React.useState(null)
  const [building, setBuilding]   = React.useState(false)
  const [savingListing, setSaving] = React.useState(false)

  const [error, setError]   = React.useState('')
  const [success, setSuccess] = React.useState('')

  const loadProducts = async () => {
    try {
      const r = await fetch(`${API}/ecom/products?limit=50`)
      if (r.ok) setProducts(await r.json())
    } catch {}
  }
  const loadListings = async () => {
    try {
      const r = await fetch(`${API}/ecom/listings?limit=50`)
      if (r.ok) setListings(await r.json())
    } catch {}
  }
  const loadStats = async () => {
    try {
      const r = await fetch(`${API}/ecom/stats`)
      if (r.ok) setEcomStats(await r.json())
    } catch {}
  }

  const loadDropship = async (filters) => {
    const f = filters || dsFilterRef.current
    setDsLoading(true)
    try {
      const params = new URLSearchParams()
      if (f.region)            params.set('region', f.region)
      if (f.platform_type)     params.set('platform_type', f.platform_type)
      if (f.has_usa_warehouse) params.set('has_usa_warehouse', f.has_usa_warehouse)
      if (f.dropship_ready)    params.set('dropship_ready', f.dropship_ready)
      if (f.search)            params.set('search', f.search)
      params.set('limit', '100')
      const r = await fetch(`${API}/ecom/dropship-directory?${params}`)
      if (r.ok) setDsSuppliers(await r.json())
    } catch {}
    setDsLoading(false)
  }

  const updateDsFilter = (key, val) => {
    const f = { ...dsFilterRef.current, [key]: val }
    dsFilterRef.current = f
    setDsFilter(f)
    loadDropship(f)
  }

  const clearDsFilters = () => {
    dsFilterRef.current = DS_EMPTY
    setDsFilter(DS_EMPTY)
    loadDropship(DS_EMPTY)
  }

  React.useEffect(() => { loadProducts(); loadListings(); loadStats(); loadDropship(DS_EMPTY) }, [])

  const doHunt = async () => {
    setError(''); setSuccess(''); setHunting(true); setHuntResults([])
    try {
      const r = await fetch(`${API}/ecom/hunt`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ category: huntForm.category, marketplace: huntForm.marketplace, keywords: huntForm.keywords, budget: parseFloat(huntForm.budget)||50 })
      })
      if (!r.ok) throw new Error(await r.text())
      const d = await r.json()
      setHuntResults(d.products || [])
      setHuntSummary(d.summary || '')
    } catch(e) { setError(e.message) }
    setHunting(false)
  }

  const saveProduct = async (prod) => {
    try {
      const r = await fetch(`${API}/ecom/products`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(prod)
      })
      if (!r.ok) throw new Error(await r.text())
      setSuccess('Product saved to database!'); loadProducts(); loadStats()
    } catch(e) { setError(e.message) }
  }

  const updateProductStatus = async (id, status) => {
    try {
      await fetch(`${API}/ecom/products/${id}`, {
        method:'PUT', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ status })
      })
      loadProducts()
    } catch {}
  }

  const deleteProduct = async (id) => {
    try {
      await fetch(`${API}/ecom/products/${id}`, { method:'DELETE' })
      loadProducts(); loadStats()
    } catch {}
  }

  const calcProfit = async () => {
    setError('')
    const p = {}
    for (const k in profitForm) p[k] = parseFloat(profitForm[k])||0
    try {
      const r = await fetch(`${API}/ecom/profit-calc`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(p)
      })
      if (!r.ok) throw new Error(await r.text())
      setProfitResult(await r.json())
    } catch(e) { setError(e.message) }
  }

  const doBuildListing = async () => {
    setError(''); setBuilding(true); setListing(null)
    try {
      const r = await fetch(`${API}/ecom/listings/build`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify(listForm)
      })
      if (!r.ok) throw new Error(await r.text())
      setListing(await r.json())
    } catch(e) { setError(e.message) }
    setBuilding(false)
  }

  const saveListing = async () => {
    if (!listing) return
    setSaving(true)
    try {
      const r = await fetch(`${API}/ecom/listings`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body: JSON.stringify({ marketplace: listForm.marketplace, title: listing.title, bullets: listing.bullets, description: listing.description, keywords: listing.keywords, ad_headline: listing.ad_headline })
      })
      if (!r.ok) throw new Error(await r.text())
      setSuccess('Listing saved!'); loadListings(); loadStats()
    } catch(e) { setError(e.message) }
    setSaving(false)
  }

  const copyText = (txt) => { navigator.clipboard.writeText(txt).catch(()=>{}); setSuccess('Copied!'); setTimeout(()=>setSuccess(''),2000) }

  const panels = [
    { id:'hunter',    label:'🎯 Product Hunter' },
    { id:'products',  label:'📦 My Products' },
    { id:'profit',    label:'💰 Profit Calculator' },
    { id:'listing',   label:'📝 Listing Builder' },
    { id:'listings',  label:'🗂️ My Listings' },
    { id:'dropship',  label:'🏭 Supplier Directory' },
  ]

  const STATUS_COLOR = { research:'#64748b', approved:'#10b981', rejected:'#ef4444', listed:'#3b82f6' }

  return (
    <div className="tab-content">
      <div className="ecom-hero">
        <div>
          <h2 className="ecom-hero-title">🛒 EZ-NEXUS AI E-Commerce Hub</h2>
          <p className="ecom-hero-sub">AI Product Hunting · Profit Calculator · Listing Builder · Multi-Marketplace</p>
        </div>
        <div className="ecom-stats-row">
          <div className="ecom-stat-pill"><strong>{ecomStats.total_products||0}</strong><span>Products</span></div>
          <div className="ecom-stat-pill"><strong>{ecomStats.approved||0}</strong><span>Approved</span></div>
          <div className="ecom-stat-pill"><strong>{ecomStats.total_listings||0}</strong><span>Listings</span></div>
          <div className="ecom-stat-pill"><strong>{ecomStats.avg_ai_score||0}</strong><span>Avg Score</span></div>
        </div>
      </div>

      {error   && <div className="alert alert-danger"  style={{margin:'0 0 12px'}}>{error}</div>}
      {success && <div className="alert alert-success" style={{margin:'0 0 12px'}}>{success}</div>}

      <div className="ecom-panel-tabs">
        {panels.map(p => (
          <button key={p.id} className={`ecom-panel-btn ${panel===p.id?'active':''}`} onClick={()=>setPanel(p.id)}>
            {p.label}
          </button>
        ))}
      </div>

      {panel === 'hunter' && (
        <div>
          <div className="card" style={{marginBottom:20}}>
            <h3 style={{color:'#f1f5f9',marginBottom:16}}>AI Product Hunting Engine</h3>
            <div className="ecom-hunt-grid">
              <div>
                <label className="form-label">Category</label>
                <select className="form-control" value={huntForm.category} onChange={e=>setHuntForm(f=>({...f,category:e.target.value}))}>
                  {ECOM_CATEGORIES.map(c=><option key={c}>{c}</option>)}
                </select>
              </div>
              <div>
                <label className="form-label">Target Marketplace</label>
                <select className="form-control" value={huntForm.marketplace} onChange={e=>setHuntForm(f=>({...f,marketplace:e.target.value}))}>
                  {ECOM_MARKETPLACES.map(m=><option key={m}>{m}</option>)}
                </select>
              </div>
              <div>
                <label className="form-label">Keywords (optional)</label>
                <input className="form-control" placeholder="e.g. portable, LED, eco-friendly" value={huntForm.keywords} onChange={e=>setHuntForm(f=>({...f,keywords:e.target.value}))} />
              </div>
              <div>
                <label className="form-label">Max Budget / Unit ($)</label>
                <input className="form-control" type="number" placeholder="50" value={huntForm.budget} onChange={e=>setHuntForm(f=>({...f,budget:e.target.value}))} />
              </div>
            </div>
            <button className="btn btn-primary" style={{marginTop:16}} onClick={doHunt} disabled={hunting}>
              {hunting ? '🔍 AI Hunting Products...' : '🚀 Hunt Winning Products'}
            </button>
          </div>

          {huntSummary && <div className="ecom-summary-bar">{huntSummary}</div>}

          {huntResults.length > 0 && (
            <div className="ecom-product-grid">
              {huntResults.map((p,i) => (
                <div className="ecom-product-card" key={i}>
                  <div className="ecom-product-header">
                    <div>
                      <div className="ecom-product-name">{p.product_name}</div>
                      <div className="ecom-product-meta">{p.marketplace} · {p.category}</div>
                    </div>
                    <div className="ecom-ai-score" style={{color: SCORE_COLOR(p.ai_score)}}>
                      {p.ai_score}<span style={{fontSize:'.7rem',color:'#94a3b8'}}>/100</span>
                    </div>
                  </div>
                  <div style={{padding:'0 16px 4px'}}>
                    <ScoreBar label="Demand"      value={p.demand_score} />
                    <ScoreBar label="Competition" value={p.competition_score} />
                    <ScoreBar label="Profit"      value={p.profit_score} />
                    <ScoreBar label="Supplier"    value={p.supplier_score} />
                    <ScoreBar label="Trend"       value={p.trend_score} />
                  </div>
                  <div className="ecom-product-financials">
                    <div><span>Cost</span><strong>${p.supplier_cost?.toFixed(2)}</strong></div>
                    <div><span>Sell</span><strong>${p.selling_price?.toFixed(2)}</strong></div>
                    <div><span>Profit</span><strong style={{color:'#10b981'}}>${p.estimated_profit?.toFixed(2)}</strong></div>
                    <div><span>Units/Mo</span><strong>{p.estimated_monthly_sales}</strong></div>
                  </div>
                  <div className="ecom-supplier-tag">
                    🏭 {p.supplier_name} ({p.supplier_country})
                  </div>
                  <div className="ecom-rec-text">{p.ai_recommendation}</div>
                  <button className="btn btn-teal" style={{width:'100%',marginTop:10}} onClick={()=>saveProduct(p)}>
                    + Save to My Products
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {panel === 'products' && (
        <div>
          <h3 style={{color:'#f1f5f9',marginBottom:16}}>My Product Database</h3>
          {products.length === 0 ? (
            <div className="card" style={{textAlign:'center',color:'#94a3b8',padding:'40px'}}>
              No products saved yet. Use the Product Hunter to find winning products.
            </div>
          ) : (
            <div style={{overflowX:'auto'}}>
              <table className="inv-items-table" style={{minWidth:900}}>
                <thead>
                  <tr>
                    <th>Product</th><th>Marketplace</th><th>AI Score</th>
                    <th>Cost</th><th>Price</th><th>Profit</th><th>Status</th><th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {products.map(p=>(
                    <tr key={p.id}>
                      <td style={{color:'#f1f5f9',fontWeight:600}}>{p.product_name}</td>
                      <td>{p.marketplace}</td>
                      <td><span style={{color:SCORE_COLOR(p.ai_score),fontWeight:700}}>{p.ai_score}</span></td>
                      <td>${p.supplier_cost?.toFixed(2)}</td>
                      <td>${p.selling_price?.toFixed(2)}</td>
                      <td style={{color:'#10b981'}}>${p.estimated_profit?.toFixed(2)}</td>
                      <td>
                        <select value={p.status} onChange={e=>updateProductStatus(p.id,e.target.value)}
                          style={{background:'#1e293b',color:STATUS_COLOR[p.status]||'#94a3b8',border:'1px solid #334155',borderRadius:4,padding:'2px 6px',fontSize:'.78rem'}}>
                          <option value="research">Research</option>
                          <option value="approved">Approved</option>
                          <option value="listed">Listed</option>
                          <option value="rejected">Rejected</option>
                        </select>
                      </td>
                      <td>
                        <button className="btn btn-sm" style={{background:'#ef4444',color:'#fff',border:'none',borderRadius:4,padding:'2px 8px',cursor:'pointer'}} onClick={()=>deleteProduct(p.id)}>Delete</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {panel === 'profit' && (
        <div>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20}}>
            <div className="card">
              <h3 style={{color:'#f1f5f9',marginBottom:16}}>Profit Calculator</h3>
              {[
                ['selling_price','Selling Price ($)'],
                ['product_cost','Product Cost ($)'],
                ['marketplace_fee','Marketplace Fee ($)'],
                ['shipping_cost','Shipping Cost ($)'],
                ['packaging_cost','Packaging Cost ($)'],
                ['advertising_cost','Advertising Cost ($)'],
                ['return_allowance','Return Allowance ($)'],
                ['other_costs','Other Costs ($)'],
              ].map(([k,lbl])=>(
                <div key={k} style={{marginBottom:10}}>
                  <label className="form-label">{lbl}</label>
                  <input className="form-control" type="number" placeholder="0.00" value={profitForm[k]}
                    onChange={e=>setProfitForm(f=>({...f,[k]:e.target.value}))} />
                </div>
              ))}
              <button className="btn btn-primary" style={{width:'100%',marginTop:8}} onClick={calcProfit}>
                Calculate Profit
              </button>
            </div>

            {profitResult && (
              <div className="card" style={{display:'flex',flexDirection:'column',gap:14}}>
                <h3 style={{color:'#f1f5f9',marginBottom:4}}>Results</h3>
                {[
                  ['Selling Price', `$${profitResult.selling_price}`, '#f1f5f9'],
                  ['Total Costs',   `$${profitResult.total_cost}`,    '#ef4444'],
                  ['Net Profit',    `$${profitResult.net_profit}`,    profitResult.net_profit >= 0 ? '#10b981' : '#ef4444'],
                  ['ROI',           `${profitResult.roi_percent}%`,   profitResult.roi_percent >= 20 ? '#10b981' : '#f59e0b'],
                  ['Margin',        `${profitResult.margin_percent}%`,profitResult.margin_percent >= 20 ? '#10b981' : '#f59e0b'],
                  ['Break Even',    `$${profitResult.break_even}`,    '#94a3b8'],
                ].map(([lbl,val,clr])=>(
                  <div key={lbl} style={{display:'flex',justifyContent:'space-between',padding:'10px 0',borderBottom:'1px solid #1e293b'}}>
                    <span style={{color:'#94a3b8'}}>{lbl}</span>
                    <strong style={{color:clr,fontSize:'1.1rem'}}>{val}</strong>
                  </div>
                ))}
                <div style={{marginTop:8,padding:12,background:'#0f172a',borderRadius:8,border:`1px solid ${profitResult.net_profit>=0?'#10b981':'#ef4444'}`}}>
                  <span style={{color:profitResult.net_profit>=0?'#10b981':'#ef4444',fontWeight:700}}>
                    {profitResult.net_profit >= 0 ? '✅ Profitable' : '❌ Not Profitable'}
                    {profitResult.roi_percent >= 30 ? ' — Excellent ROI!' : profitResult.roi_percent >= 15 ? ' — Good ROI' : ''}
                  </span>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {panel === 'listing' && (
        <div>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20}}>
            <div className="card">
              <h3 style={{color:'#f1f5f9',marginBottom:16}}>AI Listing Builder</h3>
              <div style={{marginBottom:10}}>
                <label className="form-label">Marketplace</label>
                <select className="form-control" value={listForm.marketplace} onChange={e=>setListForm(f=>({...f,marketplace:e.target.value}))}>
                  {ECOM_MARKETPLACES.map(m=><option key={m}>{m}</option>)}
                </select>
              </div>
              <div style={{marginBottom:10}}>
                <label className="form-label">Product Name</label>
                <input className="form-control" placeholder="e.g. Portable Mini Blender" value={listForm.product_name} onChange={e=>setListForm(f=>({...f,product_name:e.target.value}))} />
              </div>
              <div style={{marginBottom:10}}>
                <label className="form-label">Product Features</label>
                <textarea className="form-control" rows={3} placeholder="e.g. 6-blade design, USB-C charging, 300ml capacity, BPA-free..." value={listForm.features} onChange={e=>setListForm(f=>({...f,features:e.target.value}))} />
              </div>
              <div style={{marginBottom:10}}>
                <label className="form-label">Target Audience</label>
                <input className="form-control" placeholder="e.g. gym enthusiasts, college students" value={listForm.target_audience} onChange={e=>setListForm(f=>({...f,target_audience:e.target.value}))} />
              </div>
              <div style={{marginBottom:10}}>
                <label className="form-label">SEO Keywords</label>
                <input className="form-control" placeholder="e.g. portable blender, smoothie maker" value={listForm.keywords} onChange={e=>setListForm(f=>({...f,keywords:e.target.value}))} />
              </div>
              <div style={{marginBottom:16}}>
                <label className="form-label">Brand Voice</label>
                <select className="form-control" value={listForm.brand_voice} onChange={e=>setListForm(f=>({...f,brand_voice:e.target.value}))}>
                  {['professional','friendly','energetic','luxury','minimalist','playful'].map(v=><option key={v}>{v}</option>)}
                </select>
              </div>
              <button className="btn btn-primary" style={{width:'100%'}} onClick={doBuildListing} disabled={building||!listForm.product_name}>
                {building ? '⚙️ Building Listing...' : '✨ Generate AI Listing'}
              </button>
            </div>

            {listing && (
              <div className="card">
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:16}}>
                  <h3 style={{color:'#f1f5f9',margin:0}}>Generated Listing</h3>
                  <div style={{display:'flex',gap:8}}>
                    <button className="btn btn-sm btn-teal" onClick={saveListing} disabled={savingListing}>{savingListing?'Saving...':'Save'}</button>
                  </div>
                </div>
                {[
                  ['SEO Title', listing.title],
                  ['Bullet Points', listing.bullets],
                  ['Description', listing.description],
                  ['Backend Keywords', listing.keywords],
                  ['Ad Headline', listing.ad_headline],
                ].map(([lbl, val])=>(
                  <div key={lbl} style={{marginBottom:14}}>
                    <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:4}}>
                      <span style={{fontSize:'.78rem',fontWeight:700,color:'#64748b',textTransform:'uppercase',letterSpacing:'.05em'}}>{lbl}</span>
                      <button onClick={()=>copyText(val)} style={{fontSize:'.7rem',background:'#1e293b',color:'#94a3b8',border:'none',borderRadius:4,padding:'2px 8px',cursor:'pointer'}}>Copy</button>
                    </div>
                    <div style={{background:'#0f172a',border:'1px solid #1e293b',borderRadius:6,padding:'8px 12px',color:'#e2e8f0',fontSize:'.85rem',whiteSpace:'pre-wrap',lineHeight:1.6}}>{val}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {panel === 'listings' && (
        <div>
          <h3 style={{color:'#f1f5f9',marginBottom:16}}>My Saved Listings</h3>
          {listings.length === 0 ? (
            <div className="card" style={{textAlign:'center',color:'#94a3b8',padding:'40px'}}>No listings saved yet. Use Listing Builder to create your first listing.</div>
          ) : (
            <div className="ecom-listing-grid">
              {listings.map(l=>(
                <div className="card" key={l.id} style={{borderLeft:`3px solid ${STATUS_COLOR[l.status]||'#334155'}`}}>
                  <div style={{display:'flex',justifyContent:'space-between',marginBottom:8}}>
                    <span style={{color:'#f1f5f9',fontWeight:600}}>{l.marketplace}</span>
                    <span style={{fontSize:'.75rem',color:STATUS_COLOR[l.status]||'#94a3b8',textTransform:'uppercase'}}>{l.status}</span>
                  </div>
                  <div style={{color:'#e2e8f0',fontSize:'.9rem',marginBottom:6,fontWeight:600}}>{l.title}</div>
                  <div style={{color:'#94a3b8',fontSize:'.78rem',display:'grid',gridTemplateColumns:'1fr 1fr',gap:4,marginTop:8}}>
                    <button onClick={()=>copyText(l.title||'')} style={{background:'#1e293b',color:'#94a3b8',border:'none',borderRadius:4,padding:'4px 8px',cursor:'pointer',fontSize:'.75rem'}}>Copy Title</button>
                    <button onClick={()=>copyText(l.bullets||'')} style={{background:'#1e293b',color:'#94a3b8',border:'none',borderRadius:4,padding:'4px 8px',cursor:'pointer',fontSize:'.75rem'}}>Copy Bullets</button>
                    <button onClick={()=>copyText(l.description||'')} style={{background:'#1e293b',color:'#94a3b8',border:'none',borderRadius:4,padding:'4px 8px',cursor:'pointer',fontSize:'.75rem'}}>Copy Desc</button>
                    <button onClick={()=>copyText(l.keywords||'')} style={{background:'#1e293b',color:'#94a3b8',border:'none',borderRadius:4,padding:'4px 8px',cursor:'pointer',fontSize:'.75rem'}}>Copy Keywords</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {panel === 'dropship' && (
        <div>
          <div className="ds-hero">
            <div>
              <h3 style={{color:'#f1f5f9',margin:'0 0 4px',fontSize:'1.2rem',fontWeight:800}}>🏭 Dropship & Wholesale Supplier Directory</h3>
              <p style={{color:'#64748b',margin:0,fontSize:'.88rem'}}>
                {dsSuppliers.length} vetted suppliers — USA, EU, Asia, India &amp; Global. Filter by region, type, and shipping.
              </p>
            </div>
          </div>

          {/* Filters */}
          <div className="ds-filter-bar">
            <input className="form-control" placeholder="Search suppliers, categories..."
              autoComplete="off" value={dsFilter.search}
              onChange={e=>updateDsFilter('search', e.target.value)}
              style={{maxWidth:240}} />
            <select className="form-control" value={dsFilter.region}
              onChange={e=>updateDsFilter('region', e.target.value)}>
              <option value="">All Regions</option>
              {['USA','EU','Asia','India','LatAm','Global'].map(r=><option key={r}>{r}</option>)}
            </select>
            <select className="form-control" value={dsFilter.platform_type}
              onChange={e=>updateDsFilter('platform_type', e.target.value)}>
              <option value="">All Types</option>
              {['dropshipper','wholesaler','distributor','POD','aggregator'].map(t=><option key={t} value={t}>{t.charAt(0).toUpperCase()+t.slice(1)}</option>)}
            </select>
            <select className="form-control" value={dsFilter.has_usa_warehouse}
              onChange={e=>updateDsFilter('has_usa_warehouse', e.target.value)}>
              <option value="">USA Warehouse: Any</option>
              <option value="true">USA Warehouse: Yes</option>
              <option value="false">USA Warehouse: No</option>
            </select>
            <select className="form-control" value={dsFilter.dropship_ready}
              onChange={e=>updateDsFilter('dropship_ready', e.target.value)}>
              <option value="">Dropship: Any</option>
              <option value="true">Dropship Ready</option>
            </select>
            <button className="btn btn-sm" style={{background:'#1e293b',color:'#94a3b8',border:'1px solid #334155',borderRadius:6,padding:'6px 14px',cursor:'pointer',whiteSpace:'nowrap'}}
              onClick={clearDsFilters}>
              ✕ Clear
            </button>
            <button className="btn btn-sm" style={{background:'#1e293b',color:'#38bdf8',border:'1px solid #1e4d72',borderRadius:6,padding:'6px 14px',cursor:'pointer',whiteSpace:'nowrap'}}
              onClick={()=>loadDropship(dsFilterRef.current)}>
              ↺ Reload
            </button>
          </div>

          {dsLoading && <div style={{textAlign:'center',color:'#64748b',padding:24}}>Loading suppliers...</div>}

          {/* Supplier Detail Modal */}
          {dsSelected && (
            <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,.7)',zIndex:1000,display:'flex',alignItems:'center',justifyContent:'center',padding:20}}>
              <div style={{background:'#0f172a',border:'1px solid #1e293b',borderRadius:16,maxWidth:600,width:'100%',maxHeight:'85vh',overflowY:'auto',padding:28}}>
                <div style={{display:'flex',justifyContent:'space-between',alignItems:'flex-start',marginBottom:16}}>
                  <div>
                    <h3 style={{color:'#f1f5f9',margin:'0 0 4px',fontSize:'1.15rem'}}>{dsSelected.name}</h3>
                    <div style={{display:'flex',gap:6,flexWrap:'wrap'}}>
                      <span className="ds-badge ds-badge-region">{dsSelected.region}</span>
                      <span className="ds-badge ds-badge-type">{dsSelected.platform_type}</span>
                      {dsSelected.has_usa_warehouse && <span className="ds-badge ds-badge-usa">🇺🇸 USA Warehouse</span>}
                      {dsSelected.dropship_ready && <span className="ds-badge ds-badge-drop">Dropship Ready</span>}
                      {dsSelected.api_integration && <span className="ds-badge ds-badge-api">API</span>}
                    </div>
                  </div>
                  <button onClick={()=>setDsSelected(null)} style={{background:'none',border:'none',color:'#94a3b8',fontSize:'1.4rem',cursor:'pointer',lineHeight:1}}>×</button>
                </div>
                <p style={{color:'#94a3b8',fontSize:'.9rem',lineHeight:1.7,marginBottom:16}}>{dsSelected.description}</p>
                <div className="ds-detail-grid">
                  <div><span>Country</span><strong>{dsSelected.country}</strong></div>
                  <div><span>Min Order</span><strong>{dsSelected.min_order_usd === 0 ? 'No Minimum' : `$${dsSelected.min_order_usd}`}</strong></div>
                  <div><span>USA Ship Time</span><strong style={{color:'#10b981'}}>{dsSelected.shipping_days_usa} days</strong></div>
                  <div><span>Intl Ship Time</span><strong>{dsSelected.shipping_days_intl} days</strong></div>
                  <div><span>Rating</span><strong style={{color:'#f59e0b'}}>⭐ {dsSelected.rating}</strong></div>
                  <div><span>Website</span><strong style={{color:'#38bdf8'}}>{dsSelected.website}</strong></div>
                </div>
                {dsSelected.categories && (() => {
                  try {
                    const cats = JSON.parse(dsSelected.categories)
                    return (
                      <div style={{marginTop:16}}>
                        <div style={{fontSize:'.78rem',color:'#64748b',fontWeight:700,textTransform:'uppercase',marginBottom:8}}>Categories</div>
                        <div style={{display:'flex',flexWrap:'wrap',gap:6}}>
                          {cats.map(c=><span key={c} style={{background:'#1e293b',color:'#94a3b8',borderRadius:6,padding:'3px 10px',fontSize:'.78rem'}}>{c}</span>)}
                        </div>
                      </div>
                    )
                  } catch { return null }
                })()}
                <button className="btn btn-primary" style={{width:'100%',marginTop:20}}
                  onClick={()=>window.open(`https://${dsSelected.website}`,'_blank')}>
                  Visit Website →
                </button>
              </div>
            </div>
          )}

          <div className="ds-grid">
            {dsSuppliers.map(s=>(
              <div key={s.id} className="ds-card" onClick={()=>setDsSelected(s)}>
                <div className="ds-card-header">
                  <div className="ds-card-name">{s.name}</div>
                  <div className="ds-card-rating">⭐ {s.rating}</div>
                </div>
                <div style={{display:'flex',gap:4,flexWrap:'wrap',margin:'8px 0'}}>
                  <span className="ds-badge ds-badge-region">{s.region}</span>
                  <span className="ds-badge ds-badge-type">{s.platform_type}</span>
                  {s.has_usa_warehouse && <span className="ds-badge ds-badge-usa">🇺🇸 USA</span>}
                  {s.dropship_ready && <span className="ds-badge ds-badge-drop">Dropship</span>}
                  {s.api_integration && <span className="ds-badge ds-badge-api">API</span>}
                </div>
                <div className="ds-card-ships">
                  <span>🚚 USA: <strong style={{color:'#10b981'}}>{s.shipping_days_usa}d</strong></span>
                  <span>🌍 Intl: <strong>{s.shipping_days_intl}d</strong></span>
                  <span>Min: <strong>{s.min_order_usd===0?'None':'$'+s.min_order_usd}</strong></span>
                </div>
                <div className="ds-card-desc">{s.description?.slice(0,110)}{s.description?.length>110?'…':''}</div>
                <div className="ds-card-footer">
                  <span style={{color:'#38bdf8',fontSize:'.78rem'}}>{s.website}</span>
                  <span style={{color:'#64748b',fontSize:'.75rem'}}>Click for details →</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

const AGENT_ROSTER_FALLBACK = [
  {id:'call-center',name:'Call Center Agent',icon:'🎧',status:'active'},
  {id:'appointment',name:'Appointment Agent',icon:'📅',status:'active'},
  {id:'sales',name:'Sales Agent',icon:'💼',status:'active'},
  {id:'crm',name:'CRM Agent',icon:'👥',status:'active'},
  {id:'analytics',name:'Analytics Agent',icon:'📈',status:'active'},
  {id:'website',name:'Website Builder Agent',icon:'🖥️',status:'coming_soon'},
  {id:'seo',name:'SEO Agent',icon:'🔍',status:'coming_soon'},
  {id:'marketing',name:'Marketing Agent',icon:'📣',status:'coming_soon'},
]

// ── App Root ─────────────────────────────────────────────────────────────────
// ── Language Switcher ─────────────────────────────────────────────────────────
function LangSwitcher() {
  const { lang, setLang } = useLang()
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const cur = LANG_LIST.find(l => l.code === lang) || LANG_LIST[0]

  return (
    <div className="lang-switcher" ref={ref}>
      <button className="lang-btn" onClick={() => setOpen(v => !v)} title="Change language">
        <span>{cur.flag}</span>
        <span className="lang-name">{cur.name}</span>
        <span className="lang-caret">{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className="lang-dropdown">
          {LANG_LIST.map(l => (
            <button
              key={l.code}
              className={`lang-option ${l.code === lang ? 'lang-option--active' : ''}`}
              onClick={() => { setLang(l.code); setOpen(false) }}
            >
              <span>{l.flag}</span>
              <span>{l.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── CRM & Sales Tab ───────────────────────────────────────────────────────────
function CRMTab() {
  const { token } = useAuth()
  const [panel, setPanel]   = useState('leads')
  const [leads, setLeads]   = useState([])
  const [deals, setDeals]   = useState([])
  const [quotes, setQuotes] = useState([])
  const [stats, setStats]   = useState(null)
  const [form, setForm]     = useState({})
  const [dealForm, setDealForm] = useState({})
  const [msg, setMsg]       = useState('')
  const [loading, setLoading] = useState(false)

  const authH = token ? { Authorization: `Bearer ${token}` } : {}

  async function loadData() {
    setLoading(true)
    try {
      const [l, d, q, s] = await Promise.all([
        apiFetch('/crm/leads?limit=50', { headers: authH }),
        apiFetch('/crm/deals?limit=50', { headers: authH }),
        apiFetch('/crm/quotes?limit=50', { headers: authH }),
        apiFetch('/crm/stats', { headers: authH }),
      ])
      setLeads(l); setDeals(d); setQuotes(q); setStats(s)
    } catch (e) { setMsg('Error: ' + e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [panel])

  async function createLead(e) {
    e.preventDefault()
    setMsg('')
    try {
      await apiFetch('/crm/leads', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...form }) })
      setMsg('Lead created! AI scoring in progress...')
      setForm({})
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function updateLeadStatus(id, status) {
    try {
      await apiFetch(`/crm/leads/${id}`, { method:'PUT', headers: authH, body: JSON.stringify({ status }) })
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function createDeal(e) {
    e.preventDefault()
    setMsg('')
    try {
      await apiFetch('/crm/deals', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...dealForm }) })
      setMsg('Deal created!')
      setDealForm({})
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  const statusColors = { new:'#3b82f6', contacted:'#f59e0b', qualified:'#10b981', unqualified:'#ef4444', converted:'#8b5cf6' }
  const dealStageColors = { prospecting:'#64748b', proposal:'#f59e0b', negotiation:'#f97316', won:'#10b981', lost:'#ef4444' }

  const panels = [
    { id:'leads',    label:'👥 Leads & Pipeline' },
    { id:'deals',    label:'💼 Deals' },
    { id:'quotes',   label:'📄 Quotes' },
    { id:'new-lead', label:'➕ Add Lead' },
    { id:'new-deal', label:'➕ Add Deal' },
  ]

  return (
    <div style={{ padding:'24px', maxWidth:1200, margin:'0 auto' }}>
      <h2 style={{ color:'#3b82f6', marginBottom:8 }}>💼 CRM & Sales</h2>
      {stats && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))', gap:12, marginBottom:20 }}>
          {[
            { label:'Total Leads',    val: stats.total_leads,    color:'#3b82f6' },
            { label:'New Leads',      val: stats.new_leads,      color:'#f59e0b' },
            { label:'Qualified',      val: stats.qualified_leads, color:'#10b981' },
            { label:'Open Deals',     val: stats.open_deals,     color:'#f97316' },
            { label:'Pipeline Value', val: '$' + stats.pipeline_value?.toLocaleString(), color:'#8b5cf6' },
            { label:'Won Value',      val: '$' + stats.won_value?.toLocaleString(), color:'#10b981' },
          ].map((s,i) => (
            <div key={i} style={{ background:'#1e293b', borderRadius:8, padding:12, borderLeft:`3px solid ${s.color}` }}>
              <div style={{ fontSize:'1.4rem', fontWeight:'bold', color:s.color }}>{s.val}</div>
              <div style={{ fontSize:'.75rem', color:'#94a3b8' }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
        {panels.map(p => (
          <button key={p.id} className={`tab-btn ${panel===p.id?'active':''}`}
            style={{ fontSize:'.8rem', padding:'6px 12px' }} onClick={() => setPanel(p.id)}>
            {p.label}
          </button>
        ))}
      </div>

      {msg && <div style={{ background:'#1e293b', padding:10, borderRadius:6, marginBottom:12, color:'#94a3b8' }}>{msg}</div>}

      {panel === 'leads' && (
        <div>
          <h3 style={{ color:'#94a3b8', marginBottom:12 }}>Leads ({leads.length})</h3>
          {loading ? <p style={{ color:'#64748b' }}>Loading...</p> : (
            <table style={{ width:'100%', borderCollapse:'collapse' }}>
              <thead>
                <tr style={{ background:'#1e293b' }}>
                  {['Name','Company','Email','Source','Status','AI Score','Actions'].map(h => (
                    <th key={h} style={{ padding:'8px 12px', textAlign:'left', color:'#94a3b8', fontSize:'.8rem' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {leads.map(l => (
                  <tr key={l.id} style={{ borderBottom:'1px solid #1e293b' }}>
                    <td style={{ padding:'8px 12px', color:'#f1f5f9' }}>{l.first_name} {l.last_name}</td>
                    <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.85rem' }}>{l.company || '—'}</td>
                    <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.8rem' }}>{l.email || '—'}</td>
                    <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.8rem' }}>{l.source || '—'}</td>
                    <td style={{ padding:'8px 12px' }}>
                      <span style={{ background: statusColors[l.status] || '#64748b', color:'#fff', padding:'2px 8px', borderRadius:12, fontSize:'.75rem' }}>
                        {l.status}
                      </span>
                    </td>
                    <td style={{ padding:'8px 12px' }}>
                      <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                        <div style={{ width:40, height:6, background:'#1e293b', borderRadius:3 }}>
                          <div style={{ width: `${l.score}%`, height:'100%', background:'#3b82f6', borderRadius:3 }} />
                        </div>
                        <span style={{ fontSize:'.75rem', color:'#94a3b8' }}>{l.score}</span>
                      </div>
                    </td>
                    <td style={{ padding:'8px 12px' }}>
                      <div style={{ display:'flex', gap:4 }}>
                        {['contacted','qualified','converted'].map(s => (
                          <button key={s} onClick={() => updateLeadStatus(l.id, s)}
                            style={{ background:'#334155', border:'none', borderRadius:4, padding:'3px 7px', color:'#94a3b8', cursor:'pointer', fontSize:'.7rem' }}>
                            {s}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
                {leads.length === 0 && <tr><td colSpan={7} style={{ padding:20, color:'#64748b', textAlign:'center' }}>No leads yet.</td></tr>}
              </tbody>
            </table>
          )}
        </div>
      )}

      {panel === 'deals' && (
        <div>
          <h3 style={{ color:'#94a3b8', marginBottom:12 }}>Deals ({deals.length})</h3>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(260px,1fr))', gap:12 }}>
            {deals.map(d => (
              <div key={d.id} style={{ background:'#1e293b', borderRadius:10, padding:16, borderTop:`3px solid ${dealStageColors[d.stage] || '#64748b'}` }}>
                <div style={{ fontWeight:'bold', color:'#f1f5f9', marginBottom:4 }}>{d.title}</div>
                <div style={{ fontSize:'.8rem', color:'#94a3b8', marginBottom:8 }}>Stage: {d.stage}</div>
                <div style={{ fontSize:'1.2rem', fontWeight:'bold', color:'#10b981' }}>${d.value?.toLocaleString() || 0}</div>
                <div style={{ fontSize:'.75rem', color:'#64748b', marginTop:4 }}>Probability: {d.probability}% | {d.status}</div>
                {d.expected_close && <div style={{ fontSize:'.75rem', color:'#94a3b8', marginTop:4 }}>Close: {d.expected_close}</div>}
              </div>
            ))}
            {deals.length === 0 && <p style={{ color:'#64748b' }}>No deals yet.</p>}
          </div>
        </div>
      )}

      {panel === 'quotes' && (
        <div>
          <h3 style={{ color:'#94a3b8', marginBottom:12 }}>Quotes ({quotes.length})</h3>
          <table style={{ width:'100%', borderCollapse:'collapse' }}>
            <thead>
              <tr style={{ background:'#1e293b' }}>
                {['Quote #','Title','Client','Total','Status','Valid Until'].map(h => (
                  <th key={h} style={{ padding:'8px 12px', textAlign:'left', color:'#94a3b8', fontSize:'.8rem' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {quotes.map(q => (
                <tr key={q.id} style={{ borderBottom:'1px solid #0f172a' }}>
                  <td style={{ padding:'8px 12px', color:'#3b82f6', fontSize:'.85rem' }}>{q.quote_number}</td>
                  <td style={{ padding:'8px 12px', color:'#f1f5f9' }}>{q.title}</td>
                  <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.85rem' }}>{q.client_name || '—'}</td>
                  <td style={{ padding:'8px 12px', color:'#10b981', fontWeight:'bold' }}>${q.total?.toFixed(2)}</td>
                  <td style={{ padding:'8px 12px' }}><Badge value={q.status} /></td>
                  <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.8rem' }}>{q.valid_until || '—'}</td>
                </tr>
              ))}
              {quotes.length === 0 && <tr><td colSpan={6} style={{ padding:20, color:'#64748b', textAlign:'center' }}>No quotes yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {panel === 'new-lead' && (
        <div style={{ maxWidth:500 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Add New Lead</h3>
          <form onSubmit={createLead} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { key:'first_name', label:'First Name *', type:'text', required:true },
              { key:'last_name',  label:'Last Name',    type:'text' },
              { key:'email',      label:'Email',        type:'email' },
              { key:'phone',      label:'Phone',        type:'tel' },
              { key:'company',    label:'Company',      type:'text' },
            ].map(f => (
              <div key={f.key}>
                <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>{f.label}</label>
                <input type={f.type} required={f.required}
                  value={form[f.key] || ''}
                  onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                  style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
              </div>
            ))}
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Source</label>
              <select value={form.source || ''} onChange={e => setForm(p => ({ ...p, source: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }}>
                <option value=''>— Select —</option>
                {['web','call','referral','social','campaign','email'].map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Notes</label>
              <textarea value={form.notes || ''} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
                rows={3} style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4, resize:'vertical' }} />
            </div>
            <button type='submit' className='btn btn-primary'>🚀 Create Lead (AI will score)</button>
          </form>
        </div>
      )}

      {panel === 'new-deal' && (
        <div style={{ maxWidth:500 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Add New Deal</h3>
          <form onSubmit={createDeal} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { key:'title',          label:'Deal Title *',     type:'text', required:true },
              { key:'value',          label:'Deal Value ($)',   type:'number' },
              { key:'probability',    label:'Probability (%)',  type:'number' },
              { key:'expected_close', label:'Expected Close',   type:'date' },
              { key:'assigned_to',    label:'Assigned To',      type:'text' },
            ].map(f => (
              <div key={f.key}>
                <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>{f.label}</label>
                <input type={f.type} required={f.required}
                  value={dealForm[f.key] || ''}
                  onChange={e => setDealForm(p => ({ ...p, [f.key]: e.target.value }))}
                  style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
              </div>
            ))}
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Stage</label>
              <select value={dealForm.stage || 'prospecting'} onChange={e => setDealForm(p => ({ ...p, stage: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }}>
                {['prospecting','qualification','proposal','negotiation','won','lost'].map(s => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <button type='submit' className='btn btn-primary'>💼 Create Deal</button>
          </form>
        </div>
      )}
    </div>
  )
}


// ── Recruitment & Staffing Tab ─────────────────────────────────────────────────
function RecruitmentTab() {
  const { token } = useAuth()
  const [panel, setPanel]         = useState('jobs')
  const [jobs, setJobs]           = useState([])
  const [candidates, setCandidates] = useState([])
  const [applications, setApplications] = useState([])
  const [stats, setStats]         = useState(null)
  const [jobForm, setJobForm]     = useState({})
  const [candForm, setCandForm]   = useState({})
  const [msg, setMsg]             = useState('')
  const [loading, setLoading]     = useState(false)

  const authH = token ? { Authorization: `Bearer ${token}` } : {}

  async function loadData() {
    setLoading(true)
    try {
      const [j, c, a, s] = await Promise.all([
        apiFetch('/recruitment/jobs?limit=50', { headers: authH }),
        apiFetch('/recruitment/candidates?limit=50', { headers: authH }),
        apiFetch('/recruitment/applications?limit=50', { headers: authH }),
        apiFetch('/recruitment/stats', { headers: authH }),
      ])
      setJobs(j); setCandidates(c); setApplications(a); setStats(s)
    } catch(e) { setMsg('Error: ' + e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [])

  async function createJob(e) {
    e.preventDefault(); setMsg('')
    try {
      await apiFetch('/recruitment/jobs', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...jobForm }) })
      setMsg('Job posted! AI writing optimized description...')
      setJobForm({}); loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function createCandidate(e) {
    e.preventDefault(); setMsg('')
    try {
      await apiFetch('/recruitment/candidates', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...candForm }) })
      setMsg('Candidate added!')
      setCandForm({}); loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function updateAppStage(id, stage) {
    try {
      await apiFetch(`/recruitment/applications/${id}`, { method:'PUT', headers: authH, body: JSON.stringify({ stage }) })
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  const stageColors = { applied:'#64748b', screening:'#f59e0b', interview:'#3b82f6', offer:'#f97316', hired:'#10b981', rejected:'#ef4444' }
  const panels = [
    { id:'jobs',       label:'💼 Job Postings' },
    { id:'candidates', label:'👤 Candidates' },
    { id:'pipeline',   label:'📊 ATS Pipeline' },
    { id:'post-job',   label:'➕ Post Job' },
    { id:'add-cand',   label:'➕ Add Candidate' },
  ]

  return (
    <div style={{ padding:'24px', maxWidth:1200, margin:'0 auto' }}>
      <h2 style={{ color:'#10b981', marginBottom:8 }}>👔 Recruitment & Staffing</h2>
      {stats && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))', gap:12, marginBottom:20 }}>
          {[
            { label:'Active Jobs',   val: stats.active_jobs,      color:'#10b981' },
            { label:'Candidates',    val: stats.total_candidates,  color:'#3b82f6' },
            { label:'Applications',  val: stats.total_applications, color:'#f59e0b' },
            { label:'Interviewing',  val: stats.in_interview,      color:'#f97316' },
            { label:'Offers Sent',   val: stats.offers_sent,       color:'#8b5cf6' },
            { label:'Hired',         val: stats.hired,             color:'#10b981' },
          ].map((s,i) => (
            <div key={i} style={{ background:'#1e293b', borderRadius:8, padding:12, borderLeft:`3px solid ${s.color}` }}>
              <div style={{ fontSize:'1.4rem', fontWeight:'bold', color:s.color }}>{s.val}</div>
              <div style={{ fontSize:'.75rem', color:'#94a3b8' }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
        {panels.map(p => (
          <button key={p.id} className={`tab-btn ${panel===p.id?'active':''}`}
            style={{ fontSize:'.8rem', padding:'6px 12px' }} onClick={() => setPanel(p.id)}>
            {p.label}
          </button>
        ))}
      </div>

      {msg && <div style={{ background:'#1e293b', padding:10, borderRadius:6, marginBottom:12, color:'#94a3b8' }}>{msg}</div>}

      {panel === 'jobs' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(300px,1fr))', gap:16 }}>
          {loading ? <p style={{ color:'#64748b' }}>Loading...</p> : jobs.map(j => (
            <div key={j.id} style={{ background:'#1e293b', borderRadius:10, padding:16, borderTop:'3px solid #10b981' }}>
              <div style={{ fontWeight:'bold', color:'#f1f5f9', marginBottom:4 }}>{j.title}</div>
              <div style={{ fontSize:'.8rem', color:'#94a3b8', marginBottom:6 }}>{j.department} · {j.location || 'Remote'}</div>
              <div style={{ display:'flex', gap:6, flexWrap:'wrap', marginBottom:8 }}>
                <span style={{ background:'#0f172a', padding:'2px 7px', borderRadius:10, fontSize:'.7rem', color:'#94a3b8' }}>{j.job_type}</span>
                <span style={{ background:'#0f172a', padding:'2px 7px', borderRadius:10, fontSize:'.7rem', color:'#94a3b8' }}>{j.remote_option}</span>
                <Badge value={j.status} />
              </div>
              {j.salary_min && <div style={{ color:'#10b981', fontSize:'.85rem', fontWeight:'bold' }}>{j.salary_currency} {j.salary_min?.toLocaleString()} – {j.salary_max?.toLocaleString()}</div>}
              {j.ai_description && (
                <div style={{ marginTop:8, padding:8, background:'#0f172a', borderRadius:6, fontSize:'.75rem', color:'#94a3b8', maxHeight:80, overflow:'auto' }}>
                  <span style={{ color:'#8b5cf6' }}>AI: </span>{j.ai_description.substring(0,200)}...
                </div>
              )}
            </div>
          ))}
          {!loading && jobs.length === 0 && <p style={{ color:'#64748b' }}>No jobs posted yet.</p>}
        </div>
      )}

      {panel === 'candidates' && (
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead>
            <tr style={{ background:'#1e293b' }}>
              {['Name','Email','Location','Experience','AI Score','Status'].map(h => (
                <th key={h} style={{ padding:'8px 12px', textAlign:'left', color:'#94a3b8', fontSize:'.8rem' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {candidates.map(c => (
              <tr key={c.id} style={{ borderBottom:'1px solid #0f172a' }}>
                <td style={{ padding:'8px 12px', color:'#f1f5f9', fontWeight:'bold' }}>{c.first_name} {c.last_name}</td>
                <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.85rem' }}>{c.email || '—'}</td>
                <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.85rem' }}>{c.location || '—'}</td>
                <td style={{ padding:'8px 12px', color:'#f59e0b' }}>{c.experience_years ? `${c.experience_years} yrs` : '—'}</td>
                <td style={{ padding:'8px 12px' }}>
                  <div style={{ display:'flex', alignItems:'center', gap:6 }}>
                    <div style={{ width:40, height:6, background:'#0f172a', borderRadius:3 }}>
                      <div style={{ width:`${c.ai_score || 0}%`, height:'100%', background:'#10b981', borderRadius:3 }} />
                    </div>
                    <span style={{ fontSize:'.75rem', color:'#94a3b8' }}>{c.ai_score?.toFixed(0) || 0}</span>
                  </div>
                </td>
                <td style={{ padding:'8px 12px' }}><Badge value={c.status} /></td>
              </tr>
            ))}
            {candidates.length === 0 && <tr><td colSpan={6} style={{ padding:20, color:'#64748b', textAlign:'center' }}>No candidates yet.</td></tr>}
          </tbody>
        </table>
      )}

      {panel === 'pipeline' && (
        <div>
          <h3 style={{ color:'#94a3b8', marginBottom:12 }}>ATS Pipeline ({applications.length} applications)</h3>
          <div style={{ display:'flex', gap:12, overflowX:'auto', paddingBottom:16 }}>
            {['applied','screening','interview','offer','hired','rejected'].map(stage => (
              <div key={stage} style={{ minWidth:200, background:'#1e293b', borderRadius:8, padding:12, borderTop:`3px solid ${stageColors[stage]}` }}>
                <div style={{ fontWeight:'bold', color:stageColors[stage], marginBottom:8, textTransform:'capitalize' }}>{stage} ({applications.filter(a=>a.stage===stage).length})</div>
                {applications.filter(a=>a.stage===stage).map(a => (
                  <div key={a.id} style={{ background:'#0f172a', borderRadius:6, padding:8, marginBottom:6 }}>
                    <div style={{ fontSize:'.8rem', color:'#f1f5f9', fontWeight:'bold' }}>App #{a.id}</div>
                    <div style={{ fontSize:'.7rem', color:'#94a3b8' }}>Job #{a.job_posting_id} · Cand #{a.candidate_id}</div>
                    <div style={{ fontSize:'.7rem', color:'#10b981', marginTop:4 }}>Match: {a.ai_match_score?.toFixed(0)}%</div>
                    <div style={{ display:'flex', gap:4, marginTop:6, flexWrap:'wrap' }}>
                      {['screening','interview','offer','hired','rejected'].filter(s=>s!==stage).slice(0,2).map(s => (
                        <button key={s} onClick={() => updateAppStage(a.id, s)}
                          style={{ background:'#1e293b', border:'none', borderRadius:4, padding:'2px 6px', color:'#94a3b8', cursor:'pointer', fontSize:'.65rem' }}>
                          → {s}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                {applications.filter(a=>a.stage===stage).length === 0 && (
                  <div style={{ fontSize:'.75rem', color:'#475569', textAlign:'center', padding:8 }}>Empty</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {panel === 'post-job' && (
        <div style={{ maxWidth:600 }}>
          <h3 style={{ color:'#94a3b4', marginBottom:16 }}>Post a Job Opening</h3>
          <form onSubmit={createJob} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { key:'title',      label:'Job Title *',    type:'text',   required:true },
              { key:'department', label:'Department',     type:'text' },
              { key:'location',   label:'Location',       type:'text' },
              { key:'salary_min', label:'Salary Min',     type:'number' },
              { key:'salary_max', label:'Salary Max',     type:'number' },
            ].map(f => (
              <div key={f.key}>
                <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>{f.label}</label>
                <input type={f.type} required={f.required}
                  value={jobForm[f.key] || ''}
                  onChange={e => setJobForm(p => ({ ...p, [f.key]: e.target.value }))}
                  style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
              </div>
            ))}
            {[
              { key:'job_type', label:'Job Type', opts:['full_time','part_time','contract','temporary','internship'] },
              { key:'remote_option', label:'Remote Option', opts:['on_site','remote','hybrid'] },
            ].map(f => (
              <div key={f.key}>
                <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>{f.label}</label>
                <select value={jobForm[f.key] || f.opts[0]} onChange={e => setJobForm(p => ({ ...p, [f.key]: e.target.value }))}
                  style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }}>
                  {f.opts.map(o => <option key={o} value={o}>{o.replace(/_/g,' ')}</option>)}
                </select>
              </div>
            ))}
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Requirements</label>
              <textarea value={jobForm.requirements || ''} onChange={e => setJobForm(p => ({ ...p, requirements: e.target.value }))}
                rows={3} placeholder="List key requirements..."
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4, resize:'vertical' }} />
            </div>
            <button type='submit' className='btn btn-primary'>🚀 Post Job (AI will optimize description)</button>
          </form>
        </div>
      )}

      {panel === 'add-cand' && (
        <div style={{ maxWidth:500 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Add Candidate</h3>
          <form onSubmit={createCandidate} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { key:'first_name',       label:'First Name *',     type:'text',   required:true },
              { key:'last_name',        label:'Last Name *',      type:'text',   required:true },
              { key:'email',            label:'Email',            type:'email' },
              { key:'phone',            label:'Phone',            type:'tel' },
              { key:'location',         label:'Location',         type:'text' },
              { key:'experience_years', label:'Years Experience', type:'number' },
              { key:'education',        label:'Education',        type:'text' },
              { key:'linkedin_url',     label:'LinkedIn URL',     type:'url' },
            ].map(f => (
              <div key={f.key}>
                <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>{f.label}</label>
                <input type={f.type} required={f.required}
                  value={candForm[f.key] || ''}
                  onChange={e => setCandForm(p => ({ ...p, [f.key]: e.target.value }))}
                  style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
              </div>
            ))}
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Skills (comma-separated)</label>
              <input type='text' value={candForm.skills || ''} onChange={e => setCandForm(p => ({ ...p, skills: e.target.value }))}
                placeholder='React, Python, Sales, CRM...'
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <button type='submit' className='btn btn-primary'>➕ Add Candidate</button>
          </form>
        </div>
      )}
    </div>
  )
}


// ── Marketing Suite Tab ────────────────────────────────────────────────────────
function MarketingSuiteTab() {
  const { token } = useAuth()
  const [panel, setPanel]           = useState('campaigns')
  const [campaigns, setCampaigns]   = useState([])
  const [forms, setForms]           = useState([])
  const [stats, setStats]           = useState(null)
  const [campForm, setCampForm]     = useState({})
  const [formData, setFormData]     = useState({})
  const [msg, setMsg]               = useState('')
  const [loading, setLoading]       = useState(false)

  const authH = token ? { Authorization: `Bearer ${token}` } : {}

  async function loadData() {
    setLoading(true)
    try {
      const [c, f, s] = await Promise.all([
        apiFetch('/marketing/campaigns?limit=50', { headers: authH }),
        apiFetch('/marketing/forms', { headers: authH }),
        apiFetch('/marketing/stats', { headers: authH }),
      ])
      setCampaigns(c); setForms(f); setStats(s)
    } catch(e) { setMsg('Error: ' + e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [])

  async function createCampaign(e) {
    e.preventDefault(); setMsg('')
    try {
      await apiFetch('/marketing/campaigns', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...campForm }) })
      setMsg('Campaign created! AI generating content...')
      setCampForm({}); loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function launchCampaign(id) {
    try {
      await apiFetch(`/marketing/campaigns/${id}/launch`, { method:'POST', headers: authH })
      setMsg('Campaign launched!')
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function createForm(e) {
    e.preventDefault(); setMsg('')
    try {
      await apiFetch('/marketing/forms', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...formData }) })
      setMsg('Form created!')
      setFormData({}); loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  const statusColors = { draft:'#64748b', scheduled:'#f59e0b', active:'#10b981', paused:'#f97316', completed:'#3b82f6', cancelled:'#ef4444' }
  const typeIcons = { email:'📧', sms:'📱', voice:'📞', social:'📣', multi_channel:'🌐' }

  const panels = [
    { id:'campaigns',    label:'📢 Campaigns' },
    { id:'forms',        label:'📝 Forms' },
    { id:'new-campaign', label:'➕ New Campaign' },
    { id:'new-form',     label:'➕ New Form' },
  ]

  return (
    <div style={{ padding:'24px', maxWidth:1200, margin:'0 auto' }}>
      <h2 style={{ color:'#f59e0b', marginBottom:8 }}>📢 Marketing Suite</h2>
      {stats && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(140px,1fr))', gap:12, marginBottom:20 }}>
          {[
            { label:'Total Campaigns', val: stats.total_campaigns,  color:'#f59e0b' },
            { label:'Active',          val: stats.active_campaigns,  color:'#10b981' },
            { label:'Total Sent',      val: stats.total_sent?.toLocaleString(), color:'#3b82f6' },
            { label:'Total Opens',     val: stats.total_opens?.toLocaleString(), color:'#8b5cf6' },
            { label:'Open Rate',       val: stats.open_rate_pct + '%', color:'#f97316' },
            { label:'Form Submissions',val: stats.total_submissions, color:'#10b981' },
          ].map((s,i) => (
            <div key={i} style={{ background:'#1e293b', borderRadius:8, padding:12, borderLeft:`3px solid ${s.color}` }}>
              <div style={{ fontSize:'1.4rem', fontWeight:'bold', color:s.color }}>{s.val}</div>
              <div style={{ fontSize:'.75rem', color:'#94a3b8' }}>{s.label}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
        {panels.map(p => (
          <button key={p.id} className={`tab-btn ${panel===p.id?'active':''}`}
            style={{ fontSize:'.8rem', padding:'6px 12px' }} onClick={() => setPanel(p.id)}>
            {p.label}
          </button>
        ))}
      </div>

      {msg && <div style={{ background:'#1e293b', padding:10, borderRadius:6, marginBottom:12, color:'#94a3b8' }}>{msg}</div>}

      {panel === 'campaigns' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(320px,1fr))', gap:16 }}>
          {loading ? <p style={{ color:'#64748b' }}>Loading...</p> : campaigns.map(c => (
            <div key={c.id} style={{ background:'#1e293b', borderRadius:10, padding:16, borderLeft:`4px solid ${statusColors[c.status] || '#64748b'}` }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:8 }}>
                <div>
                  <div style={{ fontSize:'1rem', fontWeight:'bold', color:'#f1f5f9' }}>
                    {typeIcons[c.campaign_type] || '📢'} {c.name}
                  </div>
                  {c.subject && <div style={{ fontSize:'.8rem', color:'#94a3b8', marginTop:2 }}>{c.subject}</div>}
                </div>
                <Badge value={c.status} />
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:6, marginBottom:10 }}>
                {[['Sent', c.sent_count], ['Opens', c.open_count], ['Clicks', c.click_count]].map(([l,v]) => (
                  <div key={l} style={{ textAlign:'center', background:'#0f172a', borderRadius:6, padding:6 }}>
                    <div style={{ fontWeight:'bold', color:'#f1f5f9' }}>{v}</div>
                    <div style={{ fontSize:'.7rem', color:'#64748b' }}>{l}</div>
                  </div>
                ))}
              </div>
              {c.ai_generated_body && (
                <div style={{ background:'#0f172a', borderRadius:6, padding:8, fontSize:'.75rem', color:'#94a3b8', marginBottom:8, maxHeight:60, overflow:'hidden' }}>
                  <span style={{ color:'#8b5cf6' }}>AI: </span>{c.ai_generated_body.substring(0,120)}...
                </div>
              )}
              {c.status === 'draft' && (
                <button onClick={() => launchCampaign(c.id)} className='btn btn-primary' style={{ width:'100%', fontSize:'.8rem', padding:'6px 12px' }}>
                  🚀 Launch Campaign
                </button>
              )}
            </div>
          ))}
          {!loading && campaigns.length === 0 && <p style={{ color:'#64748b' }}>No campaigns yet.</p>}
        </div>
      )}

      {panel === 'forms' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(260px,1fr))', gap:16 }}>
          {forms.map(f => (
            <div key={f.id} style={{ background:'#1e293b', borderRadius:10, padding:16 }}>
              <div style={{ fontWeight:'bold', color:'#f1f5f9', marginBottom:4 }}>{f.name}</div>
              <div style={{ fontSize:'.8rem', color:'#94a3b8', marginBottom:8 }}>{f.form_type}</div>
              <div style={{ display:'flex', justifyContent:'space-between' }}>
                <span style={{ fontSize:'.8rem', color:'#10b981' }}>📩 {f.submission_count} submissions</span>
                <Badge value={f.is_active ? 'active' : 'inactive'} />
              </div>
            </div>
          ))}
          {forms.length === 0 && <p style={{ color:'#64748b' }}>No forms yet.</p>}
        </div>
      )}

      {panel === 'new-campaign' && (
        <div style={{ maxWidth:500 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Create Campaign</h3>
          <form onSubmit={createCampaign} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Campaign Name *</label>
              <input type='text' required value={campForm.name || ''}
                onChange={e => setCampForm(p => ({ ...p, name: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Type</label>
              <select value={campForm.campaign_type || 'email'} onChange={e => setCampForm(p => ({ ...p, campaign_type: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }}>
                {['email','sms','voice','social','multi_channel'].map(t => <option key={t} value={t}>{t.replace(/_/g,' ')}</option>)}
              </select>
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Subject / Topic</label>
              <input type='text' value={campForm.subject || ''}
                onChange={e => setCampForm(p => ({ ...p, subject: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Target Segment</label>
              <select value={campForm.target_segment || 'all'} onChange={e => setCampForm(p => ({ ...p, target_segment: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }}>
                {['all','leads','customers','inactive','vip'].map(t => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Body (or leave blank for AI generation)</label>
              <textarea value={campForm.body || ''} onChange={e => setCampForm(p => ({ ...p, body: e.target.value }))}
                rows={4} placeholder='Leave blank for AI to generate...'
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4, resize:'vertical' }} />
            </div>
            <button type='submit' className='btn btn-primary'>📢 Create Campaign (AI will generate content)</button>
          </form>
        </div>
      )}

      {panel === 'new-form' && (
        <div style={{ maxWidth:500 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Create Lead Capture Form</h3>
          <form onSubmit={createForm} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Form Name *</label>
              <input type='text' required value={formData.name || ''}
                onChange={e => setFormData(p => ({ ...p, name: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Form Type</label>
              <select value={formData.form_type || 'lead_capture'} onChange={e => setFormData(p => ({ ...p, form_type: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }}>
                {['lead_capture','survey','contact','appointment'].map(t => <option key={t} value={t}>{t.replace(/_/g,' ')}</option>)}
              </select>
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Thank You Message</label>
              <textarea value={formData.thank_you_message || ''} onChange={e => setFormData(p => ({ ...p, thank_you_message: e.target.value }))}
                rows={2} placeholder='Thank you for contacting us!'
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4, resize:'vertical' }} />
            </div>
            <button type='submit' className='btn btn-primary'>📝 Create Form</button>
          </form>
        </div>
      )}
    </div>
  )
}


// ── SmartBoss AI Tab ───────────────────────────────────────────────────────────
function SmartBossTab() {
  const { token } = useAuth()
  const [overview, setOverview]   = useState(null)
  const [insights, setInsights]   = useState([])
  const [question, setQuestion]   = useState('')
  const [answer, setAnswer]       = useState('')
  const [loading, setLoading]     = useState(false)
  const [genLoading, setGenLoading] = useState(false)
  const [msg, setMsg]             = useState('')

  const authH = token ? { Authorization: `Bearer ${token}` } : {}

  async function loadData() {
    setLoading(true)
    try {
      const [ov, ins] = await Promise.all([
        apiFetch('/smartboss/overview', { headers: authH }),
        apiFetch('/smartboss/insights?limit=10', { headers: authH }),
      ])
      setOverview(ov); setInsights(ins)
    } catch(e) { setMsg('Error: ' + e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [])

  async function askSmartBoss(e) {
    e.preventDefault(); setAnswer(''); setMsg('')
    setLoading(true)
    try {
      const res = await apiFetch('/smartboss/query', { method:'POST', headers: authH, body: JSON.stringify({ question }) })
      setAnswer(res.answer)
    } catch(e) { setMsg('Error: ' + e.message) }
    finally { setLoading(false) }
  }

  async function generateInsights() {
    setGenLoading(true); setMsg('')
    try {
      const res = await apiFetch('/smartboss/insights/generate', { method:'POST', headers: authH })
      setMsg(`Generated ${res.insights_created} new insights!`)
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
    finally { setGenLoading(false) }
  }

  async function markRead(id) {
    try {
      await apiFetch(`/smartboss/insights/${id}/read`, { method:'PUT', headers: authH })
      loadData()
    } catch(e) {}
  }

  const priorityColors = { high:'#ef4444', medium:'#f59e0b', low:'#10b981' }

  const MODULE_ICONS = {
    crm:'💼', recruitment:'👔', marketing:'📢', operations:'⚙️', revenue:'💰', calltrack:'📞', automation:'⚡'
  }

  return (
    <div style={{ padding:'24px', maxWidth:1200, margin:'0 auto' }}>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:20 }}>
        <h2 style={{ color:'#8b5cf6', margin:0 }}>🧠 SmartBoss AI — Executive Intelligence</h2>
        <button onClick={generateInsights} disabled={genLoading} className='btn btn-primary' style={{ fontSize:'.85rem' }}>
          {genLoading ? '⏳ Analyzing...' : '✨ Generate Insights'}
        </button>
      </div>

      {msg && <div style={{ background:'#1e293b', padding:10, borderRadius:6, marginBottom:16, color:'#94a3b8' }}>{msg}</div>}

      {/* Platform Overview Grid */}
      {overview && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(280px,1fr))', gap:16, marginBottom:24 }}>
          {Object.entries(overview).filter(([k]) => !['module','generated_at'].includes(k)).map(([key, data]) => (
            <div key={key} style={{ background:'#1e293b', borderRadius:10, padding:16 }}>
              <h4 style={{ color:'#94a3b8', marginTop:0, marginBottom:10, display:'flex', alignItems:'center', gap:8 }}>
                {MODULE_ICONS[key] || '📊'} {key.replace(/_/g,' ').toUpperCase()}
              </h4>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:6 }}>
                {Object.entries(data).slice(0, 6).map(([k, v]) => (
                  <div key={k} style={{ background:'#0f172a', borderRadius:6, padding:8 }}>
                    <div style={{ fontSize:'1rem', fontWeight:'bold', color:'#f1f5f9' }}>{typeof v === 'number' ? v.toLocaleString() : v}</div>
                    <div style={{ fontSize:'.65rem', color:'#64748b', marginTop:2 }}>{k.replace(/_/g,' ')}</div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Natural Language Q&A */}
      <div style={{ background:'#1e293b', borderRadius:12, padding:20, marginBottom:24 }}>
        <h3 style={{ color:'#8b5cf6', marginTop:0, marginBottom:12 }}>💬 Ask SmartBoss AI</h3>
        <form onSubmit={askSmartBoss} style={{ display:'flex', gap:10 }}>
          <input
            type='text'
            value={question}
            onChange={e => setQuestion(e.target.value)}
            placeholder='Ask anything: "What are my top leads this week?" "How is recruitment performing?" ...'
            style={{ flex:1, background:'#0f172a', border:'1px solid #334155', borderRadius:6, padding:'10px 14px', color:'#f1f5f9', fontSize:'.9rem' }}
          />
          <button type='submit' disabled={loading || !question} className='btn btn-primary'>
            {loading ? '⏳' : '🔍 Ask'}
          </button>
        </form>
        {answer && (
          <div style={{ marginTop:16, padding:16, background:'#0f172a', borderRadius:8, color:'#e2e8f0', lineHeight:1.6, whiteSpace:'pre-wrap', fontSize:'.9rem' }}>
            <span style={{ color:'#8b5cf6', fontWeight:'bold' }}>SmartBoss: </span>{answer}
          </div>
        )}
      </div>

      {/* Insights Feed */}
      <div>
        <h3 style={{ color:'#94a3b8', marginBottom:12 }}>🔔 AI Insights ({insights.length})</h3>
        {insights.length === 0 ? (
          <div style={{ background:'#1e293b', borderRadius:8, padding:20, textAlign:'center', color:'#64748b' }}>
            No insights yet. Click "Generate Insights" to analyze your platform data.
          </div>
        ) : (
          <div style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {insights.map(ins => (
              <div key={ins.id} style={{
                background:'#1e293b', borderRadius:8, padding:16,
                borderLeft:`4px solid ${priorityColors[ins.priority] || '#64748b'}`,
                opacity: ins.is_read ? 0.6 : 1
              }}>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:6 }}>
                  <div style={{ fontWeight:'bold', color:'#f1f5f9' }}>{ins.title}</div>
                  <div style={{ display:'flex', gap:8, alignItems:'center' }}>
                    <span style={{ background: priorityColors[ins.priority], color:'#fff', padding:'2px 8px', borderRadius:10, fontSize:'.7rem' }}>{ins.priority}</span>
                    {!ins.is_read && (
                      <button onClick={() => markRead(ins.id)} style={{ background:'#334155', border:'none', borderRadius:4, padding:'2px 8px', color:'#94a3b8', cursor:'pointer', fontSize:'.7rem' }}>
                        Mark Read
                      </button>
                    )}
                  </div>
                </div>
                {ins.summary && <p style={{ margin:'0 0 6px', color:'#94a3b8', fontSize:'.85rem' }}>{ins.summary}</p>}
                {ins.recommendation && (
                  <div style={{ background:'#0f172a', borderRadius:6, padding:8, fontSize:'.8rem', color:'#10b981' }}>
                    💡 {ins.recommendation}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}


// ── Automation & Workflow Tab ───────────────────────────────────────────────────
function AutomationTab() {
  const { token } = useAuth()
  const [panel, setPanel]           = useState('workflows')
  const [workflows, setWorkflows]   = useState([])
  const [executions, setExecutions] = useState([])
  const [webhooks, setWebhooks]     = useState([])
  const [wfForm, setWfForm]         = useState({})
  const [whForm, setWhForm]         = useState({})
  const [msg, setMsg]               = useState('')
  const [loading, setLoading]       = useState(false)

  const authH = token ? { Authorization: `Bearer ${token}` } : {}

  async function loadData() {
    setLoading(true)
    try {
      const [wf, ex, wh] = await Promise.all([
        apiFetch('/automation/workflows', { headers: authH }),
        apiFetch('/automation/executions?limit=20', { headers: authH }),
        apiFetch('/automation/webhooks', { headers: authH }),
      ])
      setWorkflows(wf); setExecutions(ex); setWebhooks(wh)
    } catch(e) { setMsg('Error: ' + e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { loadData() }, [])

  async function createWorkflow(e) {
    e.preventDefault(); setMsg('')
    try {
      await apiFetch('/automation/workflows', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...wfForm }) })
      setMsg('Workflow created!')
      setWfForm({}); loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function toggleWorkflow(id, current) {
    try {
      await apiFetch(`/automation/workflows/${id}`, { method:'PUT', headers: authH, body: JSON.stringify({ is_active: !current }) })
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function runWorkflow(id) {
    try {
      const res = await apiFetch(`/automation/workflows/${id}/run`, { method:'POST', headers: authH })
      setMsg(`Workflow run complete: ${res.steps_run} steps executed.`)
      loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  async function createWebhook(e) {
    e.preventDefault(); setMsg('')
    try {
      await apiFetch('/automation/webhooks', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...whForm }) })
      setMsg('Webhook configured!')
      setWhForm({}); loadData()
    } catch(e) { setMsg('Error: ' + e.message) }
  }

  const triggerIcons = { new_lead:'👥', appointment:'📅', form_submit:'📝', schedule:'⏰', webhook:'🔗', manual:'▶️' }
  const statusColors = { running:'#f59e0b', completed:'#10b981', failed:'#ef4444', cancelled:'#64748b' }

  const panels = [
    { id:'workflows',  label:'⚡ Workflows' },
    { id:'executions', label:'📋 Run History' },
    { id:'webhooks',   label:'🔗 Webhooks' },
    { id:'new-wf',     label:'➕ New Workflow' },
    { id:'new-wh',     label:'➕ New Webhook' },
  ]

  return (
    <div style={{ padding:'24px', maxWidth:1200, margin:'0 auto' }}>
      <h2 style={{ color:'#f97316', marginBottom:8 }}>⚡ Automation & Workflow Engine</h2>
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:12, marginBottom:20, maxWidth:500 }}>
        {[
          { label:'Total Workflows', val: workflows.length,                                    color:'#f97316' },
          { label:'Active',          val: workflows.filter(w=>w.is_active).length,             color:'#10b981' },
          { label:'Total Runs',      val: workflows.reduce((a,w)=>a+(w.run_count||0),0),       color:'#3b82f6' },
        ].map((s,i) => (
          <div key={i} style={{ background:'#1e293b', borderRadius:8, padding:12, borderLeft:`3px solid ${s.color}` }}>
            <div style={{ fontSize:'1.4rem', fontWeight:'bold', color:s.color }}>{s.val}</div>
            <div style={{ fontSize:'.75rem', color:'#94a3b8' }}>{s.label}</div>
          </div>
        ))}
      </div>

      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
        {panels.map(p => (
          <button key={p.id} className={`tab-btn ${panel===p.id?'active':''}`}
            style={{ fontSize:'.8rem', padding:'6px 12px' }} onClick={() => setPanel(p.id)}>
            {p.label}
          </button>
        ))}
      </div>

      {msg && <div style={{ background:'#1e293b', padding:10, borderRadius:6, marginBottom:12, color:'#94a3b8' }}>{msg}</div>}

      {panel === 'workflows' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(300px,1fr))', gap:16 }}>
          {loading ? <p style={{ color:'#64748b' }}>Loading...</p> : workflows.map(wf => (
            <div key={wf.id} style={{ background:'#1e293b', borderRadius:10, padding:16, border:`1px solid ${wf.is_active ? '#f97316' : '#334155'}` }}>
              <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:8 }}>
                <div>
                  <div style={{ fontWeight:'bold', color:'#f1f5f9' }}>{wf.name}</div>
                  <div style={{ fontSize:'.75rem', color:'#94a3b8', marginTop:2 }}>{wf.description || 'No description'}</div>
                </div>
                <div style={{ textAlign:'right' }}>
                  <div style={{ fontSize:'.7rem', color: wf.is_active ? '#10b981' : '#64748b', fontWeight:'bold' }}>
                    {wf.is_active ? '● ACTIVE' : '○ INACTIVE'}
                  </div>
                </div>
              </div>
              <div style={{ display:'flex', gap:6, marginBottom:10 }}>
                <span style={{ background:'#0f172a', padding:'3px 8px', borderRadius:10, fontSize:'.7rem', color:'#94a3b8' }}>
                  {triggerIcons[wf.trigger_type] || '⚡'} {wf.trigger_type}
                </span>
                <span style={{ background:'#0f172a', padding:'3px 8px', borderRadius:10, fontSize:'.7rem', color:'#64748b' }}>
                  {wf.run_count || 0} runs
                </span>
              </div>
              <div style={{ display:'flex', gap:8 }}>
                <button onClick={() => toggleWorkflow(wf.id, wf.is_active)}
                  style={{ flex:1, background: wf.is_active ? '#374151' : '#10b981', border:'none', borderRadius:6, padding:'6px 10px', color:'#fff', cursor:'pointer', fontSize:'.8rem' }}>
                  {wf.is_active ? '⏸ Pause' : '▶ Activate'}
                </button>
                {wf.is_active && (
                  <button onClick={() => runWorkflow(wf.id)}
                    style={{ flex:1, background:'#f97316', border:'none', borderRadius:6, padding:'6px 10px', color:'#fff', cursor:'pointer', fontSize:'.8rem' }}>
                    ▶ Run Now
                  </button>
                )}
              </div>
            </div>
          ))}
          {!loading && workflows.length === 0 && (
            <div style={{ background:'#1e293b', borderRadius:10, padding:24, textAlign:'center', color:'#64748b' }}>
              No workflows yet. Create one to automate your business processes.
            </div>
          )}
        </div>
      )}

      {panel === 'executions' && (
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead>
            <tr style={{ background:'#1e293b' }}>
              {['ID','Workflow','Status','Steps','Started','Completed'].map(h => (
                <th key={h} style={{ padding:'8px 12px', textAlign:'left', color:'#94a3b8', fontSize:'.8rem' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {executions.map(ex => (
              <tr key={ex.id} style={{ borderBottom:'1px solid #0f172a' }}>
                <td style={{ padding:'8px 12px', color:'#64748b', fontSize:'.8rem' }}>#{ex.id}</td>
                <td style={{ padding:'8px 12px', color:'#f1f5f9', fontSize:'.85rem' }}>WF-{ex.workflow_id}</td>
                <td style={{ padding:'8px 12px' }}>
                  <span style={{ background: statusColors[ex.status] || '#64748b', color:'#fff', padding:'2px 8px', borderRadius:10, fontSize:'.75rem' }}>{ex.status}</span>
                </td>
                <td style={{ padding:'8px 12px', color:'#94a3b8' }}>{ex.steps_completed}</td>
                <td style={{ padding:'8px 12px', color:'#64748b', fontSize:'.75rem' }}>{new Date(ex.started_at).toLocaleString()}</td>
                <td style={{ padding:'8px 12px', color:'#64748b', fontSize:'.75rem' }}>{ex.completed_at ? new Date(ex.completed_at).toLocaleString() : '—'}</td>
              </tr>
            ))}
            {executions.length === 0 && <tr><td colSpan={6} style={{ padding:20, color:'#64748b', textAlign:'center' }}>No executions yet.</td></tr>}
          </tbody>
        </table>
      )}

      {panel === 'webhooks' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(300px,1fr))', gap:16 }}>
          {webhooks.map(wh => (
            <div key={wh.id} style={{ background:'#1e293b', borderRadius:10, padding:16, borderLeft:'4px solid #6366f1' }}>
              <div style={{ fontWeight:'bold', color:'#f1f5f9', marginBottom:4 }}>{wh.name}</div>
              <div style={{ fontSize:'.75rem', color:'#6366f1', wordBreak:'break-all', marginBottom:6 }}>{wh.url}</div>
              {wh.events && <div style={{ fontSize:'.7rem', color:'#94a3b8' }}>Events: {wh.events}</div>}
              <div style={{ fontSize:'.7rem', color:'#64748b', marginTop:4 }}>Fails: {wh.fail_count}</div>
            </div>
          ))}
          {webhooks.length === 0 && <p style={{ color:'#64748b' }}>No webhooks configured yet.</p>}
        </div>
      )}

      {panel === 'new-wf' && (
        <div style={{ maxWidth:500 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Create Workflow</h3>
          <form onSubmit={createWorkflow} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Workflow Name *</label>
              <input type='text' required value={wfForm.name || ''}
                onChange={e => setWfForm(p => ({ ...p, name: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Description</label>
              <input type='text' value={wfForm.description || ''}
                onChange={e => setWfForm(p => ({ ...p, description: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Trigger</label>
              <select value={wfForm.trigger_type || 'new_lead'} onChange={e => setWfForm(p => ({ ...p, trigger_type: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }}>
                {['new_lead','appointment','form_submit','schedule','webhook','manual'].map(t => (
                  <option key={t} value={t}>{triggerIcons[t] || '⚡'} {t.replace(/_/g,' ')}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Steps (JSON array of step objects)</label>
              <textarea value={wfForm.steps || ''} onChange={e => setWfForm(p => ({ ...p, steps: e.target.value }))}
                rows={4} placeholder='[{"action":"send_email","to":"{{lead.email}}"},{"action":"create_task","title":"Follow up"}]'
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4, resize:'vertical', fontFamily:'monospace', fontSize:'.8rem' }} />
            </div>
            <button type='submit' className='btn btn-primary'>⚡ Create Workflow</button>
          </form>
        </div>
      )}

      {panel === 'new-wh' && (
        <div style={{ maxWidth:500 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Configure Webhook</h3>
          <form onSubmit={createWebhook} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Name *</label>
              <input type='text' required value={whForm.name || ''}
                onChange={e => setWhForm(p => ({ ...p, name: e.target.value }))}
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Webhook URL *</label>
              <input type='url' required value={whForm.url || ''}
                onChange={e => setWhForm(p => ({ ...p, url: e.target.value }))}
                placeholder='https://your-service.com/webhook'
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <div>
              <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>Events (comma-separated)</label>
              <input type='text' value={whForm.events || ''}
                onChange={e => setWhForm(p => ({ ...p, events: e.target.value }))}
                placeholder='new_lead,appointment,form_submit'
                style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
            </div>
            <button type='submit' className='btn btn-primary'>🔗 Add Webhook</button>
          </form>
        </div>
      )}
    </div>
  )
}


// ── CallTrack AI Tab ───────────────────────────────────────────────────────────
function CallTrackTab() {
  const { token }  = useAuth()
  const [numbers, setNumbers]   = useState([])
  const [events, setEvents]     = useState([])
  const [analytics, setAnalytics] = useState(null)
  const [form, setForm]         = useState({})
  const [panel, setPanel]       = useState('analytics')
  const [msg, setMsg]           = useState('')

  const authH = token ? { Authorization: `Bearer ${token}` } : {}

  async function loadData() {
    try {
      const [n, e, a] = await Promise.all([
        apiFetch('/calltrack/numbers', { headers: authH }),
        apiFetch('/calltrack/events?limit=20', { headers: authH }),
        apiFetch('/calltrack/analytics', { headers: authH }),
      ])
      setNumbers(n); setEvents(e); setAnalytics(a)
    } catch(ex) { setMsg('Error: ' + ex.message) }
  }

  useEffect(() => { loadData() }, [])

  async function addNumber(e) {
    e.preventDefault(); setMsg('')
    try {
      await apiFetch('/calltrack/numbers', { method:'POST', headers: authH, body: JSON.stringify({ business_id:1, ...form }) })
      setMsg('Tracking number added!')
      setForm({}); loadData()
    } catch(ex) { setMsg('Error: ' + ex.message) }
  }

  const panels = [
    { id:'analytics', label:'📊 Analytics' },
    { id:'numbers',   label:'📱 Tracking Numbers' },
    { id:'events',    label:'📋 Call Events' },
    { id:'add',       label:'➕ Add Number' },
  ]

  return (
    <div style={{ padding:'24px', maxWidth:1200, margin:'0 auto' }}>
      <h2 style={{ color:'#06b6d4', marginBottom:8 }}>📊 CallTrack AI</h2>

      <div style={{ display:'flex', gap:8, marginBottom:16, flexWrap:'wrap' }}>
        {panels.map(p => (
          <button key={p.id} className={`tab-btn ${panel===p.id?'active':''}`}
            style={{ fontSize:'.8rem', padding:'6px 12px' }} onClick={() => setPanel(p.id)}>
            {p.label}
          </button>
        ))}
      </div>

      {msg && <div style={{ background:'#1e293b', padding:10, borderRadius:6, marginBottom:12, color:'#94a3b8' }}>{msg}</div>}

      {panel === 'analytics' && analytics && (
        <div>
          <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))', gap:12, marginBottom:20 }}>
            {[
              { label:'Tracking Numbers',    val: analytics.total_tracking_numbers, color:'#06b6d4' },
              { label:'Total Calls',         val: analytics.total_calls,            color:'#3b82f6' },
              { label:'Conversions',         val: analytics.total_conversions,      color:'#10b981' },
              { label:'Conversion Rate',     val: analytics.conversion_rate_pct + '%', color:'#f59e0b' },
              { label:'Avg Duration (s)',    val: analytics.avg_call_duration_secs, color:'#f97316' },
              { label:'Revenue Attributed',  val: '$' + analytics.total_revenue_attributed?.toLocaleString(), color:'#10b981' },
            ].map((s,i) => (
              <div key={i} style={{ background:'#1e293b', borderRadius:8, padding:12, borderLeft:`3px solid ${s.color}` }}>
                <div style={{ fontSize:'1.4rem', fontWeight:'bold', color:s.color }}>{s.val}</div>
                <div style={{ fontSize:'.75rem', color:'#94a3b8' }}>{s.label}</div>
              </div>
            ))}
          </div>
          <div style={{ background:'#1e293b', borderRadius:10, padding:20, color:'#94a3b8', textAlign:'center' }}>
            <div style={{ fontSize:'2rem', marginBottom:8 }}>📞</div>
            <div>Call attribution analytics. Add tracking numbers to campaigns and monitor which sources drive conversions.</div>
          </div>
        </div>
      )}

      {panel === 'numbers' && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(260px,1fr))', gap:16 }}>
          {numbers.map(n => (
            <div key={n.id} style={{ background:'#1e293b', borderRadius:10, padding:16, borderLeft:'4px solid #06b6d4' }}>
              <div style={{ fontSize:'1.1rem', fontWeight:'bold', color:'#06b6d4' }}>{n.campaign_name}</div>
              <div style={{ fontSize:'.9rem', color:'#f1f5f9', marginTop:4 }}>Source: {n.source || '—'}</div>
              {n.medium && <div style={{ fontSize:'.8rem', color:'#94a3b8' }}>Medium: {n.medium}</div>}
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8, marginTop:10 }}>
                <div style={{ background:'#0f172a', borderRadius:6, padding:8, textAlign:'center' }}>
                  <div style={{ fontWeight:'bold', color:'#f1f5f9' }}>{n.total_calls}</div>
                  <div style={{ fontSize:'.7rem', color:'#64748b' }}>Total Calls</div>
                </div>
                <div style={{ background:'#0f172a', borderRadius:6, padding:8, textAlign:'center' }}>
                  <div style={{ fontWeight:'bold', color:'#10b981' }}>{n.conversions}</div>
                  <div style={{ fontSize:'.7rem', color:'#64748b' }}>Conversions</div>
                </div>
              </div>
            </div>
          ))}
          {numbers.length === 0 && <p style={{ color:'#64748b' }}>No tracking numbers yet.</p>}
        </div>
      )}

      {panel === 'events' && (
        <table style={{ width:'100%', borderCollapse:'collapse' }}>
          <thead>
            <tr style={{ background:'#1e293b' }}>
              {['Caller','Duration','Conversion','Sentiment','AI Summary','Date'].map(h => (
                <th key={h} style={{ padding:'8px 12px', textAlign:'left', color:'#94a3b8', fontSize:'.8rem' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.map(ev => (
              <tr key={ev.id} style={{ borderBottom:'1px solid #0f172a' }}>
                <td style={{ padding:'8px 12px', color:'#f1f5f9', fontSize:'.85rem' }}>{ev.caller_phone || '—'}</td>
                <td style={{ padding:'8px 12px', color:'#94a3b8' }}>{ev.call_duration_secs}s</td>
                <td style={{ padding:'8px 12px', color: ev.is_conversion ? '#10b981' : '#64748b' }}>{ev.is_conversion ? '✅ Yes' : '—'}</td>
                <td style={{ padding:'8px 12px', color:'#f59e0b', fontSize:'.8rem' }}>{ev.sentiment || '—'}</td>
                <td style={{ padding:'8px 12px', color:'#94a3b8', fontSize:'.75rem', maxWidth:200 }}>{ev.ai_summary?.substring(0,80) || '—'}</td>
                <td style={{ padding:'8px 12px', color:'#64748b', fontSize:'.75rem' }}>{new Date(ev.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
            {events.length === 0 && <tr><td colSpan={6} style={{ padding:20, color:'#64748b', textAlign:'center' }}>No call events yet.</td></tr>}
          </tbody>
        </table>
      )}

      {panel === 'add' && (
        <div style={{ maxWidth:400 }}>
          <h3 style={{ color:'#94a3b8', marginBottom:16 }}>Add Tracking Number</h3>
          <form onSubmit={addNumber} style={{ display:'flex', flexDirection:'column', gap:10 }}>
            {[
              { key:'campaign_name', label:'Campaign Name *', required:true },
              { key:'source',        label:'Source (google, facebook, email...)' },
              { key:'medium',        label:'Medium (cpc, organic, email...)' },
              { key:'utm_campaign',  label:'UTM Campaign' },
            ].map(f => (
              <div key={f.key}>
                <label style={{ color:'#94a3b8', fontSize:'.85rem' }}>{f.label}</label>
                <input type='text' required={f.required} value={form[f.key] || ''}
                  onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                  style={{ width:'100%', background:'#1e293b', border:'1px solid #334155', borderRadius:6, padding:'8px 12px', color:'#f1f5f9', marginTop:4 }} />
              </div>
            ))}
            <button type='submit' className='btn btn-primary'>📊 Add Tracking Number</button>
          </form>
        </div>
      )}
    </div>
  )
}


// ── App (inner, wrapped by LangProvider + AuthProvider) ──────────────────────
function AppInner() {
  const { t }               = useLang()
  const { user, logout }    = useAuth()
  const [activeTab, setActiveTab]         = useState('home')
  const [notifications, setNotifications] = useState([])
  const [showAuth,  setShowAuth]          = useState(false)
  const [showChgPw, setShowChgPw]         = useState(false)
  const [userMenuOpen, setUserMenuOpen]   = useState(false)
  const userMenuRef = useRef(null)

  const handleWsMessage = useCallback((msg) => {
    setNotifications(prev => [...prev.slice(-19), msg])
    if (Notification.permission === 'granted') {
      new Notification('EZ-NEXUS AI', { body: msg.message, icon: '/favicon.ico' })
    }
  }, [])

  const wsConnected = useWebSocket(handleWsMessage)

  useEffect(() => {
    if ('Notification' in window && Notification.permission === 'default') {
      Notification.requestPermission()
    }
  }, [])

  // Close user menu on outside click
  useEffect(() => {
    const h = e => { if (userMenuRef.current && !userMenuRef.current.contains(e.target)) setUserMenuOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  const TABS = [
    { id: 'home',            label: t.tabs.home },
    { id: 'smartboss',       label: '🧠 SmartBoss AI' },
    { id: 'dashboard',       label: t.tabs.dashboard },
    { id: 'crm',             label: '💼 CRM & Sales' },
    { id: 'recruitment',     label: '👔 Recruitment' },
    { id: 'marketing',       label: '📢 Marketing' },
    { id: 'call-center',     label: t.tabs.callCenter },
    { id: 'calltrack',       label: '📊 CallTrack AI' },
    { id: 'automation',      label: '⚡ Automation' },
    { id: 'businesses',      label: t.tabs.businesses },
    { id: 'appointments',    label: t.tabs.appointments },
    { id: 'approval',        label: '📋 Approvals' },
    { id: 'invoices',        label: '🧾 Invoices' },
    { id: 'data-entry',      label: '📄 Data Entry AI' },
    { id: 'healthcare',      label: '🏥 Healthcare' },
    { id: 'marketplace',     label: '🏪 DME Market' },
    { id: 'agents',          label: '🤖 Agents' },
    { id: 'commander',       label: '🤖 Commander AI' },
    { id: 'website-builder', label: '🖥️ Website Builder' },
    { id: 'content-studio',  label: '🎬 Content Studio' },
    { id: 'ecommerce',       label: '🛒 E-Commerce' },
    { id: 'ai',              label: t.tabs.ai },
    { id: 'subscriptions',   label: '💎 Pricing' },
  ]

  const COMING_SOON_IDS = []

  return (
    <div className="app">
      <nav className="navbar">
        <div className="navbar-brand">
          🤖 EZ-NEXUS AI
          <span className="tagline">{t.tagline}</span>
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:12 }}>
          <LangSwitcher />
          <div className="navbar-status">
            <div className={`status-dot ${wsConnected ? 'connected' : ''}`} />
            {wsConnected ? t.live : t.reconnecting}
          </div>

          {/* Auth button / user menu */}
          {user ? (
            <div className="user-menu-wrap" ref={userMenuRef}>
              <button className="user-menu-btn" onClick={() => setUserMenuOpen(v => !v)}>
                <span className="user-avatar">{user.full_name?.[0]?.toUpperCase() || '?'}</span>
                <span className="user-name-short">{user.full_name?.split(' ')[0]}</span>
                {user.is_admin && <span className="user-admin-badge">Admin</span>}
                <span style={{ fontSize: '.7rem', color: '#94a3b8' }}>▼</span>
              </button>
              {userMenuOpen && (
                <div className="user-dropdown">
                  <div className="user-dropdown-info">
                    <strong>{user.full_name}</strong>
                    <span>{user.email}</span>
                    <span className="badge badge-scheduled" style={{ width: 'fit-content', textTransform: 'capitalize' }}>{user.plan}</span>
                  </div>
                  <button className="user-dropdown-item" onClick={() => { setUserMenuOpen(false); setShowChgPw(true) }}>
                    🔐 Change Password
                  </button>
                  <button className="user-dropdown-item" onClick={() => { setActiveTab('subscriptions'); setUserMenuOpen(false) }}>
                    💎 Subscription
                  </button>
                  <button className="user-dropdown-item user-dropdown-item--danger" onClick={() => { logout(); setUserMenuOpen(false) }}>
                    ← Sign Out
                  </button>
                </div>
              )}
            </div>
          ) : (
            <button className="btn btn-primary btn-sm" style={{ fontSize: '.8rem' }} onClick={() => setShowAuth(true)}>
              Login / Register
            </button>
          )}
        </div>
      </nav>

      <main className="main">
        <div className="tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'home'            && <HomeTab onNavigate={setActiveTab} />}
        {activeTab === 'smartboss'       && <SmartBossTab />}
        {activeTab === 'dashboard'       && <DashboardTab wsConnected={wsConnected} />}
        {activeTab === 'crm'             && <CRMTab />}
        {activeTab === 'recruitment'     && <RecruitmentTab />}
        {activeTab === 'marketing'       && <MarketingSuiteTab />}
        {activeTab === 'call-center'     && <CallCenterTab />}
        {activeTab === 'calltrack'       && <CallTrackTab />}
        {activeTab === 'automation'      && <AutomationTab />}
        {activeTab === 'businesses'      && <BusinessesTab />}
        {activeTab === 'appointments'    && <AppointmentsTab />}
        {activeTab === 'approval'        && <ApprovalQueueTab />}
        {activeTab === 'invoices'        && <InvoicesTab />}
        {activeTab === 'data-entry'      && <DataEntryTab />}
        {activeTab === 'healthcare'      && <HealthcareTab />}
        {activeTab === 'marketplace'     && <DMEMarketplaceTab />}
        {activeTab === 'agents'          && <AgentsTab />}
        {activeTab === 'commander'       && <CommanderTab />}
        {activeTab === 'website-builder' && <WebsiteBuilderTab />}
        {activeTab === 'content-studio'  && <ContentStudioTab />}
        {activeTab === 'ecommerce'       && <EcommerceTab />}
        {activeTab === 'ai'              && <AIAnalyzerTab />}
        {activeTab === 'subscriptions'   && <SubscriptionsTab />}
        {COMING_SOON_IDS.includes(activeTab) && <ComingSoonTab tabId={activeTab} onBack={() => setActiveTab('home')} />}
      </main>

      <NotificationsPanel notifications={notifications} />

      {showAuth  && <AuthModal onClose={() => setShowAuth(false)} />}
      {showChgPw && <ChangePasswordModal onClose={() => setShowChgPw(false)} />}
    </div>
  )
}

function App() {
  return (
    <AuthProvider>
      <LangProvider>
        <AppInner />
      </LangProvider>
    </AuthProvider>
  )
}

createRoot(document.getElementById('root')).render(<App />)
