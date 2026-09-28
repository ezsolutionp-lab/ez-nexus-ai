/*
 * MO NEXUS OMEGA — Command Center.
 *
 * A thin client over /api/mo/platform: capability manifest, knowledge base, memory,
 * governed runs, autonomy policy, domain intelligence tools, evaluations and protocol
 * peers. Every result shows the server's own state (SUCCESS, PENDING_APPROVAL,
 * CREDENTIAL_REQUIRED, ...) rather than a friendly paraphrase, and nothing here
 * approves on the user's behalf.
 */
import React, { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || ''
const BASE = '/api/mo/platform'
const AUTH_BASE = '/api/mo/authority'

async function call(path, { method = 'GET', body, token, base = BASE } = {}) {
  const response = await fetch(`${API}${base}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  })
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = { raw: text } }
  return { ok: response.ok, status: response.status, data }
}

const TONE = {
  implemented: 'ok', SUCCESS: 'ok', SUCCEEDED: 'ok',
  partial: 'warn', PENDING_APPROVAL: 'warn', AWAITING_APPROVAL: 'warn', PARTIAL: 'warn',
  credential_required: 'cred', CREDENTIAL_REQUIRED: 'cred',
}
function Chip({ value }) {
  return <span className={`mo-chip mo-chip--${TONE[value] || 'neutral'}`}>{value}</span>
}

function Result({ res }) {
  if (!res) return null
  const body = res.data || {}
  const state = body.state || (res.ok ? 'SUCCESS' : `HTTP ${res.status}`)
  return (
    <div className="cc-result">
      <div><Chip value={state} /> <span className="mo-sub">HTTP {res.status}</span></div>
      {body.detail && <p className="cc-detail">{typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)}</p>}
      <pre>{JSON.stringify(body.data ?? body, null, 2)}</pre>
    </div>
  )
}

function Panel({ title, note, children }) {
  return (
    <section className="cc-panel">
      <h3>{title}</h3>
      {note && <p className="mo-sub">{note}</p>}
      {children}
    </section>
  )
}

function useAction(token) {
  const [res, setRes] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = useCallback(async (path, opts) => {
    setBusy(true)
    try { setRes(await call(path, { ...opts, token })) }
    catch (e) { setRes({ ok: false, status: 0, data: { state: 'FAILED', detail: String(e.message || e) } }) }
    finally { setBusy(false) }
  }, [token])
  return [res, run, busy]
}

function ManifestPanel({ token }) {
  const [m, setM] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => {
    call('/manifest', { token }).then(r => (r.ok ? setM(r.data) : setErr(`HTTP ${r.status}`))).catch(e => setErr(String(e)))
  }, [token])
  if (err) return <Panel title="Capability manifest"><div className="mo-error">{err}</div></Panel>
  if (!m) return <Panel title="Capability manifest"><p className="mo-sub">Loading…</p></Panel>
  return (
    <Panel title="Capability manifest" note="What is built, what is partial, and what is not — read from the server, verified by tests.">
      <div className="cc-summary">
        {Object.entries(m.summary || {}).map(([k, v]) => <span key={k}><Chip value={k} /> {String(v)}</span>)}
      </div>
      <table className="cc-table">
        <thead><tr><th>Feature</th><th>Status</th><th>Note</th></tr></thead>
        <tbody>
          {(m.capabilities || []).map(c => (
            <tr key={c.feature}><td>{c.feature}</td><td><Chip value={c.status} /></td><td>{c.note || ''}</td></tr>
          ))}
        </tbody>
      </table>
      {(m.known_blockers || []).length > 0 && (
        <details><summary>Known blockers ({m.known_blockers.length})</summary>
          <ul>{m.known_blockers.map((b, i) => <li key={i}>{typeof b === 'string' ? b : JSON.stringify(b)}</li>)}</ul>
        </details>
      )}
    </Panel>
  )
}

function KnowledgePanel({ token }) {
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [q, setQ] = useState('')
  const [res, run, busy] = useAction(token)
  return (
    <Panel title="Knowledge base" note="Hybrid retrieval (BM25 + n-gram + entity graph). Answers cite sources or refuse.">
      <input placeholder="Document title" value={title} onChange={e => setTitle(e.target.value)} />
      <textarea rows={3} placeholder="Document text" value={text} onChange={e => setText(e.target.value)} />
      <button disabled={busy || !title || !text} onClick={() => run('/knowledge/docs', { method: 'POST', body: { title, text } })}>Ingest</button>
      <input placeholder="Ask a question" value={q} onChange={e => setQ(e.target.value)} />
      <button disabled={busy || !q} onClick={() => run('/knowledge/answer', { method: 'POST', body: { question: q } })}>Answer</button>
      <button disabled={busy || !q} onClick={() => run('/knowledge/search', { method: 'POST', body: { query: q } })}>Search</button>
      <button disabled={busy} onClick={() => run('/knowledge/docs')}>List documents</button>
      <Result res={res} />
    </Panel>
  )
}

function MemoryPanel({ token }) {
  const [content, setContent] = useState('')
  const [query, setQuery] = useState('')
  const [res, run, busy] = useAction(token)
  return (
    <Panel title="Memory" note="Layered memory, private by default. Secrets are refused, not stored.">
      <input placeholder="Something to remember" value={content} onChange={e => setContent(e.target.value)} />
      <button disabled={busy || !content} onClick={() => run('/memory', { method: 'POST', body: { content } })}>Remember</button>
      <input placeholder="Recall query" value={query} onChange={e => setQuery(e.target.value)} />
      <button disabled={busy || !query} onClick={() => run('/memory/recall', { method: 'POST', body: { query } })}>Recall</button>
      <button disabled={busy} onClick={() => run('/memory/stats')}>Stats</button>
      <button disabled={busy} onClick={() => run('/memory/consolidate', { method: 'POST', body: {} })}>Consolidate</button>
      <Result res={res} />
    </Panel>
  )
}

const SAMPLE_PLAN = {
  name: 'quick-forecast',
  steps: [{ key: 'f', kind: 'tool', target: 'domain.forecast', input: { series: [10, 12, 13, 15, 16, 18], horizon: 3 } }],
}

function RunsPanel({ token }) {
  const [plan, setPlan] = useState(JSON.stringify(SAMPLE_PLAN, null, 2))
  const [runId, setRunId] = useState('')
  const [res, run, busy] = useAction(token)
  const create = async () => {
    let body
    try { body = JSON.parse(plan) } catch { return run('/runs', { method: 'POST', body: { name: '', steps: [] } }) }
    await run('/runs', { method: 'POST', body })
  }
  return (
    <Panel title="Governed runs" note="Steps the autonomy policy does not allow unattended stop at PENDING_APPROVAL. At the default level every step does.">
      <textarea rows={8} value={plan} onChange={e => setPlan(e.target.value)} spellCheck={false} />
      <button disabled={busy} onClick={create}>Create run</button>
      <input placeholder="Run id" value={runId} onChange={e => setRunId(e.target.value)} />
      <button disabled={busy || !runId} onClick={() => run(`/runs/${runId}/execute`, { method: 'POST', body: {} })}>Execute</button>
      <button disabled={busy || !runId} onClick={() => run(`/runs/${runId}`)}>Inspect</button>
      <button disabled={busy || !runId} onClick={() => run(`/runs/${runId}/cancel`, { method: 'POST' })}>Cancel</button>
      <button disabled={busy} onClick={() => run('/runs')}>List runs</button>
      <Result res={res} />
    </Panel>
  )
}

function AutonomyPanel({ token }) {
  const [subject, setSubject] = useState('domain.forecast')
  const [level, setLevel] = useState(1)
  const [res, run, busy] = useAction(token)
  return (
    <Panel title="Autonomy policy" note="Administrators only. Level 4+ or a raised ceiling needs an MFA-verified session; promotion needs shadow-mode evidence.">
      <input value={subject} onChange={e => setSubject(e.target.value)} />
      <select value={level} onChange={e => setLevel(Number(e.target.value))}>
        {[0, 1, 2, 3, 4, 5].map(n => <option key={n} value={n}>Level {n}</option>)}
      </select>
      <button disabled={busy || !subject} onClick={() => run('/autonomy', { method: 'PUT', body: { subject, level } })}>Set level</button>
      <button disabled={busy} onClick={() => run('/autonomy')}>Show policy</button>
      <button disabled={busy || !subject} onClick={() => run(`/autonomy/evidence?subject=${encodeURIComponent(subject)}`)}>Evidence</button>
      <button disabled={busy || !subject} onClick={() => run('/autonomy/promote', { method: 'POST', body: { subject } })}>Request promotion</button>
      <Result res={res} />
    </Panel>
  )
}

function DomainPanel({ token }) {
  const [tools, setTools] = useState([])
  const [tool, setTool] = useState('forecast')
  const [input, setInput] = useState('{"series":[10,12,13,15,16,18],"horizon":3}')
  const [res, run, busy] = useAction(token)
  useEffect(() => {
    call('/domain/tools', { token }).then(r => r.ok && setTools(r.data?.tools || [])).catch(() => {})
  }, [token])
  const go = () => {
    let body
    try { body = JSON.parse(input) } catch { return run(`/domain/${tool}`, { method: 'POST', body: { __invalid_json: true } }) }
    return run(`/domain/${tool}`, { method: 'POST', body })
  }
  return (
    <Panel title="Domain intelligence" note="Classical statistics and planning maths — deterministic, not neural models.">
      <select value={tool} onChange={e => setTool(e.target.value)}>
        {(tools.length ? tools.map(t => t.name.replace(/^domain\./, '')) : [tool]).map(n => <option key={n}>{n}</option>)}
      </select>
      <textarea rows={4} value={input} onChange={e => setInput(e.target.value)} spellCheck={false} />
      <button disabled={busy} onClick={go}>Run</button>
      <Result res={res} />
    </Panel>
  )
}

function EvalsPanel({ token }) {
  const [suites, setSuites] = useState([])
  const [suite, setSuite] = useState('')
  const [res, run, busy] = useAction(token)
  useEffect(() => {
    call('/evals/suites', { token }).then(r => {
      const list = r.ok ? (r.data?.suites || []) : []
      setSuites(list)
      if (list.length) setSuite(list[0].name || list[0])
    }).catch(() => {})
  }, [token])
  return (
    <Panel title="Evaluations" note="Deterministic checks only. There is no model-graded judge.">
      <select value={suite} onChange={e => setSuite(e.target.value)}>
        {suites.map(s => { const n = s.name || s; return <option key={n}>{n}</option> })}
      </select>
      <button disabled={busy || !suite} onClick={() => run('/evals/run', { method: 'POST', body: { suite } })}>Run suite</button>
      <button disabled={busy} onClick={() => run('/evals/runs')}>History</button>
      <Result res={res} />
    </Panel>
  )
}

function ProtocolsPanel({ token }) {
  const [res, run, busy] = useAction(token)
  return (
    <Panel title="Protocols (MCP / A2A)" note="Peers are administrator-managed, SSRF-guarded, and need their credential set in the server environment.">
      <button disabled={busy} onClick={() => run('/protocols/peers')}>List peers</button>
      <button disabled={busy} onClick={() => run('/protocols/a2a/card')}>A2A agent card</button>
      <button disabled={busy} onClick={() => run('/protocols/mcp', { method: 'POST', body: { jsonrpc: '2.0', id: 1, method: 'tools/list' } })}>MCP tools/list</button>
      <Result res={res} />
    </Panel>
  )
}

function AuthorityPanel({ token }) {
  const [res, run, busy] = useAction(token)
  const get = path => run(path, { base: AUTH_BASE })
  return (
    <Panel title="Authority" note="Read-only views. Approvals are decided in the approvals queue, never here; grant tokens are shown once to the requester.">
      <button disabled={busy} onClick={() => get('/policy')}>Policy and deny-list</button>
      <button disabled={busy} onClick={() => get('/receipts')}>Receipts</button>
      <button disabled={busy} onClick={() => get('/agents')}>Agents</button>
      <button disabled={busy} onClick={() => get('/releases')}>Releases</button>
      <button disabled={busy} onClick={() => get('/compliance/dependencies?status=QUARANTINED')}>Quarantined dependencies</button>
      <button disabled={busy} onClick={() => get('/compliance/gate')}>Compliance gate</button>
      <Result res={res} />
    </Panel>
  )
}

const PANELS = [
  ['manifest', 'Capabilities', ManifestPanel], ['knowledge', 'Knowledge', KnowledgePanel],
  ['memory', 'Memory', MemoryPanel], ['runs', 'Runs', RunsPanel], ['autonomy', 'Autonomy', AutonomyPanel],
  ['domain', 'Domain tools', DomainPanel], ['evals', 'Evals', EvalsPanel], ['protocols', 'Protocols', ProtocolsPanel], ['authority', 'Authority', AuthorityPanel],
]

export default function CommandCenter({ token }) {
  const [tab, setTab] = useState('manifest')
  if (!token) return <div className="mo-empty">Sign in to use the Command Center.</div>
  const Active = PANELS.find(p => p[0] === tab)[2]
  return (
    <div className="mo-studio cc">
      <header>
        <h2>MO Command Center</h2>
        <p className="mo-sub">Governed platform services. Results show the server’s own state; approvals are never granted from this screen.</p>
      </header>
      <nav className="cc-tabs">
        {PANELS.map(([id, label]) => (
          <button key={id} className={id === tab ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>
        ))}
      </nav>
      <Active token={token} />
    </div>
  )
}
