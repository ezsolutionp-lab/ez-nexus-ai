/*
 * MO NEXUS OMEGA — Builder Studio
 *
 * The minimum functional UI the directive asks for (§41): create a project from
 * a prompt, then inspect requirements, architecture, the project graph, the
 * generated APIs, agents, files and build results — and request a deployment,
 * which always comes back as "needs approval".
 *
 * The UI reports MO result states verbatim. A CREDENTIAL_REQUIRED agent shows
 * as blocked, not as a green tick.
 */
import React, { useCallback, useEffect, useState } from 'react'

const API = import.meta.env.VITE_API_URL || ''

const STATE_TONE = {
  SUCCESS: 'ok',
  PARTIAL: 'warn',
  APPROVAL_REQUIRED: 'warn',
  PENDING_APPROVAL: 'warn',
  CREDENTIAL_REQUIRED: 'cred',
  POLICY_DENIED: 'bad',
  BLOCKED: 'bad',
  RATE_LIMITED: 'bad',
  BUILD_FAILED: 'bad',
  TEST_FAILED: 'bad',
  SECURITY_FAILED: 'bad',
  FAILED: 'bad',
  TIMEOUT: 'bad',
  PROVIDER_UNAVAILABLE: 'bad',
}

function StateChip({ state }) {
  if (!state) return null
  return <span className={`mo-chip mo-chip--${STATE_TONE[state] || 'neutral'}`}>{state}</span>
}

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
    throw Object.assign(new Error(detail?.detail || detail || `HTTP ${response.status}`), {
      status: response.status,
      state: detail?.state,
      meta: detail?.meta,
    })
  }
  return data
}

const PANELS = [
  ['overview', 'Overview'],
  ['requirements', 'Requirements'],
  ['architecture', 'Architecture'],
  ['graph', 'Project Graph'],
  ['apis', 'APIs'],
  ['agents', 'Agents'],
  ['workflows', 'Workflows'],
  ['integrations', 'Integrations'],
  ['files', 'Code'],
  ['builds', 'Builds & Tests'],
  ['deploy', 'Deployments'],
]

export default function BuilderStudio({ token }) {
  const [status, setStatus] = useState(null)
  const [projects, setProjects] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [panel, setPanel] = useState('overview')
  const [panelData, setPanelData] = useState(null)
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [report, setReport] = useState(null)
  const [openFile, setOpenFile] = useState(null)

  const loadProjects = useCallback(async () => {
    try {
      setProjects(await call('/api/mo/builder/projects', { token }))
    } catch (err) { setError(err.message) }
  }, [token])

  useEffect(() => {
    if (!token) return
    call('/api/mo/builder/status', { token }).then(setStatus).catch(err => setError(err.message))
    loadProjects()
  }, [token, loadProjects])

  useEffect(() => {
    if (!selectedId || !token) return
    setPanelData(null)
    const routes = {
      overview: `/api/mo/builder/projects/${selectedId}`,
      requirements: `/api/mo/builder/projects/${selectedId}/requirements`,
      architecture: `/api/mo/builder/projects/${selectedId}/architecture`,
      graph: `/api/mo/builder/projects/${selectedId}/graph`,
      apis: `/api/mo/builder/projects/${selectedId}/apis`,
      agents: `/api/mo/builder/projects/${selectedId}/agents`,
      workflows: `/api/mo/builder/projects/${selectedId}/workflows`,
      integrations: `/api/mo/builder/projects/${selectedId}/integrations`,
      files: `/api/mo/builder/projects/${selectedId}/files`,
      builds: `/api/mo/builder/projects/${selectedId}/builds`,
      deploy: `/api/mo/builder/projects/${selectedId}/deployments`,
    }
    call(routes[panel], { token }).then(setPanelData).catch(err => setError(err.message))
  }, [selectedId, panel, token])

  async function createProject(event) {
    event.preventDefault()
    if (!prompt.trim()) return
    setBusy(true); setError(null); setReport(null)
    try {
      const result = await call('/api/mo/builder/projects', {
        method: 'POST', token, body: { prompt, run_build: true },
      })
      setReport(result.report)
      setSelectedId(result.project.id)
      setPanel('overview')
      setPrompt('')
      await loadProjects()
    } catch (err) {
      setError(`${err.state || 'error'}: ${err.message}`)
    } finally { setBusy(false) }
  }

  async function runBuild() {
    setBusy(true); setError(null)
    try {
      await call(`/api/mo/builder/projects/${selectedId}/build`, { method: 'POST', token })
      setPanel('builds')
    } catch (err) { setError(`${err.state || 'error'}: ${err.message}`) }
    finally { setBusy(false) }
  }

  async function requestDeploy(environment) {
    setBusy(true); setError(null)
    try {
      const result = await call(`/api/mo/builder/projects/${selectedId}/deploy/request`, {
        method: 'POST', token, body: { environment },
      })
      setError(null)
      setReport({ deploy: result })
      setPanel('deploy')
    } catch (err) { setError(`${err.state || 'error'}: ${err.message}`) }
    finally { setBusy(false) }
  }

  if (!token) {
    return <div className="mo-empty">Sign in to use the Builder Studio.</div>
  }

  return (
    <div className="mo-studio">
      <header className="mo-studio__head">
        <div>
          <h2>MO Builder Studio</h2>
          <p className="mo-sub">
            Describe what you want built. MO produces requirements, an architecture,
            a project graph, real source code, and a sandboxed build — then stops at
            the approval gate.
          </p>
        </div>
        {status && (
          <div className="mo-capabilities">
            <div><b>Stacks</b> {status.stacks.implemented.join(', ')}</div>
            <div><b>Requirements</b> {status.requirement_engine}</div>
            <div>
              <b>Model fabric</b>{' '}
              {status.model_fabric.any_configured
                ? 'configured'
                : <span className="mo-chip mo-chip--cred">CREDENTIAL_REQUIRED</span>}
            </div>
          </div>
        )}
      </header>

      {status && !status.model_fabric.any_configured && (
        <div className="mo-notice">
          No model provider is configured, so requirements come from the deterministic
          catalogue and generated agents will stop at <code>CREDENTIAL_REQUIRED</code> rather
          than being marked ready. Set <code>ANTHROPIC_API_KEY</code> to enable model-assisted
          requirements and live agent tests.
        </div>
      )}

      <form className="mo-prompt" onSubmit={createProject}>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          placeholder="Build a plumbing company platform with a website, CRM, online booking, dispatch, invoices and an AI voice receptionist."
          rows={3}
        />
        <button type="submit" disabled={busy || !prompt.trim()}>
          {busy ? 'Building…' : 'Build it'}
        </button>
      </form>

      {error && <div className="mo-error">{error}</div>}

      {report?.stages && (
        <div className="mo-stages">
          {Object.entries(report.stages).map(([stage, info]) => (
            <div key={stage} className="mo-stage">
              <div className="mo-stage__name">{stage.replace(/_/g, ' ')}</div>
              <StateChip state={info.state} />
              <div className="mo-stage__detail">{info.detail}</div>
            </div>
          ))}
        </div>
      )}

      <div className="mo-body">
        <aside className="mo-projects">
          <h3>Projects</h3>
          {projects.length === 0 && <p className="mo-sub">No projects yet.</p>}
          {projects.map(p => (
            <button
              key={p.id}
              className={`mo-project ${p.id === selectedId ? 'is-active' : ''}`}
              onClick={() => { setSelectedId(p.id); setPanel('overview') }}
            >
              <span className="mo-project__name">{p.name}</span>
              <StateChip state={p.status} />
            </button>
          ))}
        </aside>

        <section className="mo-panel">
          {!selectedId && <div className="mo-empty">Select or create a project.</div>}
          {selectedId && (
            <>
              <nav className="mo-tabs">
                {PANELS.map(([key, label]) => (
                  <button key={key}
                          className={panel === key ? 'is-active' : ''}
                          onClick={() => setPanel(key)}>{label}</button>
                ))}
              </nav>

              <div className="mo-actions">
                <button onClick={runBuild} disabled={busy}>Run build &amp; tests</button>
                <button onClick={() => requestDeploy('staging')} disabled={busy}>
                  Request staging deploy
                </button>
                <button onClick={() => requestDeploy('production')} disabled={busy}>
                  Request production deploy
                </button>
                <a href={`${API}/api/mo/builder/projects/${selectedId}/export`}
                   className="mo-link">Export source</a>
              </div>

              <PanelBody panel={panel} data={panelData} projectId={selectedId}
                         token={token} openFile={openFile} setOpenFile={setOpenFile} />
            </>
          )}
        </section>
      </div>
    </div>
  )
}

function PanelBody({ panel, data, projectId, token, openFile, setOpenFile }) {
  if (!data) return <div className="mo-empty">Loading…</div>

  if (panel === 'overview') {
    return (
      <div className="mo-grid">
        {Object.entries(data.counts || {}).map(([key, value]) => (
          <div key={key} className="mo-stat">
            <span className="mo-stat__n">{value}</span>
            <span className="mo-stat__l">{key.replace(/_/g, ' ')}</span>
          </div>
        ))}
        <div className="mo-stat">
          <span className="mo-stat__n">{data.cost?.sandbox_seconds ?? 0}s</span>
          <span className="mo-stat__l">sandbox time</span>
        </div>
        <div className="mo-stat">
          <span className="mo-stat__n">${(data.cost?.model_usd ?? 0).toFixed(4)}</span>
          <span className="mo-stat__l">model cost</span>
        </div>
      </div>
    )
  }

  if (panel === 'requirements') {
    return (
      <>
        {data.assumptions?.length > 0 && (
          <div className="mo-notice">
            <b>Recorded assumptions</b>
            <ul>{data.assumptions.map((a, i) => (
              <li key={i}>{a.statement} <em>{a.rationale}</em></li>
            ))}</ul>
          </div>
        )}
        <table className="mo-table">
          <thead><tr><th>Category</th><th>Key</th><th>Requirement</th><th>Priority</th></tr></thead>
          <tbody>
            {data.requirements.map(r => (
              <tr key={r.key}>
                <td><span className="mo-chip mo-chip--neutral">{r.category}</span></td>
                <td><code>{r.key}</code></td>
                <td>{r.statement}<div className="mo-sub">{r.acceptance_criteria}</div></td>
                <td>{r.priority}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </>
    )
  }

  if (panel === 'architecture') {
    return (
      <div className="mo-arch">
        <h4>{data.recommended} <span className="mo-chip mo-chip--neutral">{data.complexity}</span></h4>
        <p>{data.rationale}</p>
        <h5>Alternatives considered</h5>
        <table className="mo-table">
          <thead><tr><th>Option</th><th>Score</th><th>Why not chosen</th></tr></thead>
          <tbody>{data.alternatives.map(a => (
            <tr key={a.name}><td>{a.name}</td><td>{a.total_score}</td><td>{a.why_not_chosen}</td></tr>
          ))}</tbody>
        </table>
        <h5>Infrastructure</h5>
        <pre className="mo-pre">{JSON.stringify(data.infrastructure, null, 2)}</pre>
      </div>
    )
  }

  if (panel === 'graph') {
    const byType = data.nodes.reduce((acc, n) => {
      (acc[n.type] = acc[n.type] || []).push(n); return acc
    }, {})
    return (
      <div className="mo-graph">
        <p className="mo-sub">{data.node_count} nodes</p>
        {Object.entries(byType).map(([type, nodes]) => (
          <details key={type} open={type === 'model'}>
            <summary>{type} ({nodes.length})</summary>
            <ul className="mo-nodes">
              {nodes.map(n => (
                <li key={n.key}>
                  <code>{n.label}</code>
                  {n.depends_on.length > 0 && (
                    <span className="mo-sub"> → {n.depends_on.join(', ')}</span>
                  )}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    )
  }

  if (panel === 'apis') {
    return (
      <table className="mo-table">
        <thead><tr><th>Method</th><th>Path</th><th>Model</th><th>Auth</th><th>Rate limit</th></tr></thead>
        <tbody>{data.map((a, i) => (
          <tr key={i}>
            <td><code>{a.method}</code></td><td><code>{a.path}</code></td>
            <td>{a.data_model}</td>
            <td>{a.requires_auth ? <StateChip state="SUCCESS" /> : <StateChip state="FAILED" />}</td>
            <td>{a.rate_limit_per_minute}/min</td>
          </tr>
        ))}</tbody>
      </table>
    )
  }

  if (panel === 'agents') {
    return (
      <div className="mo-agents">
        {data.map(a => (
          <div key={a.manifest_id} className="mo-agent">
            <div className="mo-agent__head">
              <b>{a.name}</b> <StateChip state={a.status} />
            </div>
            <p>{a.purpose}</p>
            <div className="mo-sub">
              Tools: {a.tools.join(', ') || 'none'} · Gates: {a.approval_gates.join(', ') || 'none'}
            </div>
            {a.test_report && (
              <table className="mo-table mo-table--tight">
                <tbody>{Object.entries(a.test_report.checks).map(([check, r]) => (
                  <tr key={check}>
                    <td><code>{check}</code></td>
                    <td><StateChip state={r.passed ? 'SUCCESS' : 'FAILED'} /></td>
                    <td className="mo-sub">{r.detail}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
          </div>
        ))}
      </div>
    )
  }

  if (panel === 'workflows') {
    return data.map(w => (
      <div key={w.id} className="mo-agent">
        <div className="mo-agent__head"><b>{w.name}</b> <StateChip state={w.status} /></div>
        <ol className="mo-nodes">
          {w.nodes.map(n => <li key={n.id}><code>{n.type}</code> {n.tool || n.topic || n.event || ''}</li>)}
        </ol>
      </div>
    ))
  }

  if (panel === 'integrations') {
    return (
      <table className="mo-table">
        <thead><tr><th>Provider</th><th>Capability</th><th>Status</th><th>Environment variable</th></tr></thead>
        <tbody>{data.map((i, idx) => (
          <tr key={idx}>
            <td>{i.provider}</td><td>{i.capability}</td>
            <td><StateChip state={i.status} /></td>
            <td><code>{i.credential_env_var}</code></td>
          </tr>
        ))}</tbody>
      </table>
    )
  }

  if (panel === 'files') {
    return (
      <div className="mo-files">
        <ul className="mo-filelist">
          {data.files.map(f => (
            <li key={f.path}>
              <button onClick={async () => {
                const body = await call(
                  `/api/mo/builder/projects/${projectId}/files?path=${encodeURIComponent(f.path)}`,
                  { token })
                setOpenFile(body)
              }}>{f.path}</button>
              <span className="mo-sub">{f.bytes}b</span>
            </li>
          ))}
        </ul>
        {openFile && (
          <div className="mo-code">
            <div className="mo-code__head"><code>{openFile.path}</code></div>
            <pre className="mo-pre">{openFile.content}</pre>
          </div>
        )}
      </div>
    )
  }

  if (panel === 'builds') {
    return data.map(b => (
      <div key={b.id} className="mo-agent">
        <div className="mo-agent__head">
          <b>v{b.version}</b> <StateChip state={b.state} />
          <span className="mo-sub">{b.duration_ms}ms · peak {b.peak_rss_kb}kb</span>
        </div>
        <table className="mo-table mo-table--tight">
          <tbody>{b.stages.map(s => (
            <tr key={s.name}>
              <td><code>{s.name}</code></td>
              <td><StateChip state={s.state === 'PASSED' ? 'SUCCESS'
                : s.state === 'SKIPPED' ? 'PARTIAL' : 'FAILED'} /></td>
              <td className="mo-sub">{s.detail}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    ))
  }

  if (panel === 'deploy') {
    if (data.length === 0) {
      return <div className="mo-empty">
        No deployment requested yet. Every deployment needs a second-party approval.
      </div>
    }
    return (
      <table className="mo-table">
        <thead><tr><th>Environment</th><th>State</th><th>Requested by</th><th>Detail</th></tr></thead>
        <tbody>{data.map(d => (
          <tr key={d.id}>
            <td>{d.environment}</td><td><StateChip state={d.state} /></td>
            <td>{d.requested_by}</td><td className="mo-sub">{d.detail}</td>
          </tr>
        ))}</tbody>
      </table>
    )
  }

  return <pre className="mo-pre">{JSON.stringify(data, null, 2)}</pre>
}
