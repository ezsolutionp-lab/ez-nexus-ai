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
    { id: 'home',          label: t.tabs.home },
    { id: 'dashboard',     label: t.tabs.dashboard },
    { id: 'call-center',   label: t.tabs.callCenter },
    { id: 'businesses',    label: t.tabs.businesses },
    { id: 'appointments',  label: t.tabs.appointments },
    { id: 'approval',      label: '📋 Approvals' },
    { id: 'commander',     label: '🧠 Commander AI' },
    { id: 'ai',            label: t.tabs.ai },
    { id: 'subscriptions', label: '💎 Pricing' },
  ]

  const COMING_SOON_IDS = ['website-builder', 'marketing', 'content-studio', 'automation']

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

        {activeTab === 'home'          && <HomeTab onNavigate={setActiveTab} />}
        {activeTab === 'dashboard'     && <DashboardTab wsConnected={wsConnected} />}
        {activeTab === 'call-center'   && <CallCenterTab />}
        {activeTab === 'businesses'    && <BusinessesTab />}
        {activeTab === 'appointments'  && <AppointmentsTab />}
        {activeTab === 'approval'      && <ApprovalQueueTab />}
        {activeTab === 'commander'     && <CommanderTab />}
        {activeTab === 'ai'            && <AIAnalyzerTab />}
        {activeTab === 'subscriptions' && <SubscriptionsTab />}
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
