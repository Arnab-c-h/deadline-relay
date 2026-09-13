import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Health, Operation, Plan, Run, Snapshot } from './types'

const DEFAULT_REQUEST = ''
const ACTIVE = new Set(['QUEUED', 'PREFLIGHT', 'EXECUTING', 'VERIFYING'])
const RESUMABLE = new Set(['PARTIAL', 'UNCERTAIN', 'FAILED'])
const UNFINISHED = new Set([...ACTIVE, ...RESUMABLE, 'EXHAUSTED'])

function actionKey() {
  return globalThis.crypto?.randomUUID?.() ?? `action-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function titleCase(value: string) {
  if (value.toLowerCase() === 'github') return 'GitHub'
  return value.toLowerCase().replace(/(^|_)(\w)/g, (_, space, letter) => `${space ? ' ' : ''}${letter.toUpperCase()}`)
}

function dateLabel(value: string | null) {
  if (!value) return 'Unknown date'
  const date = new Date(`${value}T12:00:00`)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric' }).format(date)
}

function formatValue(value: unknown): string {
  if (value == null || value === '') return 'Not set'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.length ? value.map(formatValue).join(', ') : 'None'
  if (typeof value === 'object') {
    const fields = value as Record<string, unknown>
    if (typeof fields.start === 'string' && typeof fields.end === 'string') {
      return fields.start === fields.end ? formatValue(fields.start) : `${formatValue(fields.start)} – ${formatValue(fields.end)}`
    }
    return Object.entries(fields).map(([key, item]) => `${fieldLabel(key)}: ${formatValue(item)}`).join(' · ')
  }
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return dateLabel(value)
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) return timestamp(value)
  return String(value)
}

function fieldLabel(value: string) {
  const labels: Record<string, string> = { due_on: 'Due date', DeliveryDate: 'Delivery date', AcceptedPlan: 'Accepted plan', EstimateDays: 'Estimate (days)', NotBefore: 'Earliest start', verified_at: 'Verified at', checked_at: 'Checked at', constraints_passed: 'Schedule constraints', preservation_passed: 'Unchanged records', verified_operations: 'Verified changes' }
  return labels[value] ?? titleCase(value.replace(/([a-z])([A-Z])/g, '$1 $2'))
}

function timestamp(value: string | undefined): string {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Kolkata' }).format(parsed)
}

function Fields({ value }: { value: Record<string, unknown> }) {
  return <div className="field-list">{Object.entries(value).map(([key, field]) => <span key={key}><small>{fieldLabel(key)}</small>{key === 'due_on' && typeof field === 'string' ? dateLabel(field.slice(0, 10)) : formatValue(field)}</span>)}</div>
}

function Evidence({ value, label }: { value: unknown; label: string }) {
  const evidence = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  return <details className="evidence"><summary>{label}</summary>
    {evidence.verified_at != null && <p>Read back {timestamp(String(evidence.verified_at))}</p>}
    {evidence.values != null && typeof evidence.values === 'object' && <Fields value={evidence.values as Record<string, unknown>} />}
    <details className="raw-details"><summary>Technical details</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>
  </details>
}

function Source({ url }: { url: string | null }) {
  return url ? <a className="source" href={url} target="_blank" rel="noreferrer">Open source ↗</a> : null
}

function OperationTable({ operations, running = false }: { operations: Operation[]; running?: boolean }) {
  if (!operations.length) return null
  return <div className="table-wrap"><table>
    <caption>{running ? 'Execution results by source' : 'Review each proposed change'} · times in Asia/Kolkata</caption>
    <thead><tr><th>Source / record</th><th>Current</th><th>{running ? 'Approved value' : 'Proposed value'}</th>{running && <th>Status</th>}</tr></thead>
    <tbody>{operations.map((operation) => <tr key={operation.id}>
      <td><span className={`provider ${operation.provider}`}>{titleCase(operation.provider)}</span><strong>{operation.name}</strong><Source url={operation.source_url} /></td>
      <td><Fields value={operation.before} /></td><td><Fields value={operation.after} /></td>
      {running && <td><span className={`status status-${operation.status?.toLowerCase()}`}>{titleCase(operation.status ?? 'pending')}</span>{operation.attempts ? <small className="attempts">{operation.attempts} attempt{operation.attempts === 1 ? '' : 's'}</small> : null}{operation.evidence != null && <Evidence value={operation.evidence} label="Read-back evidence" />}{operation.error && <small className="op-error">{operation.error}</small>}</td>}
    </tr>)}</tbody>
  </table></div>
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [prompt, setPrompt] = useState(DEFAULT_REQUEST)
  const [plan, setPlan] = useState<Plan | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [loading, setLoading] = useState<'health' | 'plan' | 'alternative' | 'approve' | 'resume' | 'open-run' | 'recovery' | null>('health')
  const [error, setError] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const approvalKey = useRef<string | null>(null)
  const resumeKey = useRef<string | null>(null)

  useEffect(() => {
    let live = true
    api.health().then((data) => live && setHealth(data)).catch((e: Error) => live && setError(e.message)).finally(() => live && setLoading(null))
    return () => { live = false }
  }, [])

  async function refreshConnections() {
    setLoading('health'); setError(null)
    try { setHealth(await api.health()) }
    catch (e) { setHealth(null); setError((e as Error).message) }
    finally { setLoading(null) }
  }

  const loadRun = useCallback(async (runId: string) => {
    try { setRun(await api.run(runId)); setStatusError(null); setError(null) }
    catch (e) { setStatusError((e as Error).message); setError((e as Error).message) }
  }, [])

  useEffect(() => {
    if (!run || !ACTIVE.has(run.status) || statusError) return
    const timer = window.setTimeout(() => void loadRun(run.id), 750)
    return () => window.clearTimeout(timer)
  }, [run, loadRun, statusError])

  async function openRun(runId: string) {
    setLoading('open-run'); setError(null); setStatusError(null); approvalKey.current = null; resumeKey.current = null
    try {
      const selectedRun = await api.run(runId)
      const selectedPlan = await api.getPlan(selectedRun.plan_id)
      const selectedSnapshot = await api.getSnapshot(selectedPlan.snapshot_id)
      setPlan(selectedPlan); setSnapshot(selectedSnapshot); setPrompt(selectedPlan.request); setRun(selectedRun)
    } catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }

  async function analyze() {
    setLoading('plan'); setError(null); setPlan(null); setRun(null); approvalKey.current = null
    try {
      const fresh = await api.snapshot()
      setSnapshot(fresh)
      setPlan(await api.plan(fresh.id, prompt))
    } catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }

  async function chooseAlternative() {
    if (!plan?.proposed_date || !snapshot) return
    setLoading('alternative'); setError(null); approvalKey.current = null
    try { setPlan(await api.plan(snapshot.id, plan.request, { date: plan.proposed_date, parentId: plan.id })) }
    catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }

  async function approve() {
    if (!plan) return
    if (!approvalKey.current) approvalKey.current = actionKey()
    setLoading('approve'); setError(null)
    try {
      const result = await api.approve(plan, approvalKey.current)
      await loadRun(result.run_id)
    } catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }

  async function resume() {
    if (!run) return
    if (!resumeKey.current) resumeKey.current = actionKey()
    setLoading('resume'); setError(null)
    try { const result = await api.resume(run.id, resumeKey.current); await loadRun(result.run_id) }
    catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }

  async function reviewRecoveryPlan() {
    if (!run) return
    setLoading('recovery'); setError(null); setStatusError(null)
    try {
      const recovery = await api.recoveryPlan(run.id)
      const recoverySnapshot = await api.getSnapshot(recovery.snapshot_id)
      approvalKey.current = null; resumeKey.current = null
      setPlan(recovery); setSnapshot(recoverySnapshot); setPrompt(recovery.request); setRun(null)
    } catch (e) { setError((e as Error).message) } finally { setLoading(null) }
  }

  const setupBlocked = Boolean(health && (health.setup_required.length || health.connections.some((connection) => !['ready', 'simulated'].includes(connection.status)) || !['ready', 'simulated'].includes(health.model.status)))
  const approveFailed = Boolean(error && approvalKey.current && !run)
  const verified = run?.status === 'VERIFIED'
  const recentRuns = health?.runs.filter((item) => UNFINISHED.has(item.status)) ?? []
  const pathIds = (() => {
    if (!snapshot) return new Set<string>()
    const byId = new Map(snapshot.nodes.map((node) => [node.id, node]))
    const ids = new Set<string>()
    const visit = (id: string) => { if (ids.has(id)) return; ids.add(id); byId.get(id)?.predecessors.forEach(visit) }
    visit('REL')
    return ids
  })()
  const dependencyItems = plan?.items.filter((item) => item.disposition !== 'unrelated' && pathIds.has(item.id)) ?? []
  const additionalConstraints = plan?.items.filter((item) => item.disposition !== 'unrelated' && !pathIds.has(item.id)) ?? []
  const unrelatedItems = plan?.items.filter((item) => item.disposition === 'unrelated') ?? []

  return <div className="app-shell">
    <a className="skip-link" href="#main">Skip to workspace</a>
    <header className="masthead"><div className="brand"><span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M5 6h10l4 4-4 4H5V6Z" stroke="currentColor" strokeWidth="1.7" /><path d="M5 18h10" stroke="currentColor" strokeWidth="1.7" /></svg></span><span>Deadline Relay</span><span className="brand-divider" /><span className="workspace-label">Workspace</span></div><div className="mode" role="status"><span className={`mode-dot ${setupBlocked ? 'missing' : health?.mode ?? 'unknown'}`} />{health?.mode === 'simulated' ? 'Simulated mode' : health?.mode === 'live' ? (setupBlocked ? 'Live · setup required' : 'Live · connected') : loading === 'health' ? 'Checking connection' : 'Connection unavailable'}</div></header>
    <main id="main">
      <section className="project-header"><div><p className="breadcrumb">Projects <span>/</span> Release planning</p><h1>{health?.project.name ?? (loading === 'health' ? 'Loading workspace…' : 'Project workspace')}</h1><p className="lede">Review a deadline change across your connected tools.</p></div><a className="text-link" href="#connections">Manage connections <span aria-hidden="true">↗</span></a></section>
      <nav className="workspace-nav" aria-label="Workspace sections"><a href="#request" aria-current={!plan && !run ? 'step' : undefined}>Request</a>{plan && <a href="#impact" aria-current={!run ? 'step' : undefined}>Plan review</a>}{run && <a href="#execution" aria-current="step">Execution</a>}<a href="#connections">Connections</a></nav>

      {error && <div role="alert" className="alert error"><strong>Something needs attention</strong><span>{error}</span></div>}
      {setupBlocked && <div className="alert setup"><div><strong>Connection setup required</strong><span>Complete the source and planner configuration to analyze a request.</span></div><a href="#connections">Review setup <span aria-hidden="true">→</span></a></div>}

      <div className="workspace">
        <div className="primary">
          <section className="card request-card" aria-labelledby="request-heading"><div className="section-heading"><div><p className="eyebrow">01 / Request</p><h2 id="request-heading">Change the deadline</h2></div><span className="no-write">Preview only</span></div>
            <label htmlFor="request">Deadline request</label><textarea id="request" aria-describedby="request-help" placeholder="Describe the new deadline and any constraints…" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} />
            <div className="request-actions"><p id="request-help">Include a target date. We’ll read the latest project state and prepare a plan for review.</p><button className="button primary-button" onClick={analyze} disabled={!health || setupBlocked || Boolean(loading) || !prompt.trim()}>{loading === 'plan' ? <><span className="spinner" />Reading project state…</> : <>Analyze impact <span aria-hidden="true">→</span></>}</button></div>
          </section>

          {!plan && !run && <section className="empty-review" aria-labelledby="review-heading"><div className="empty-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M7 3h10v18H7zM10 8h4M10 12h4M10 16h2" stroke="currentColor" strokeWidth="1.4" /></svg></div><h2 id="review-heading">Your change plan will appear here</h2><p>See affected records, scheduling constraints, and exact before-and-after values before approving.</p><ol className="workflow-steps"><li><span>1</span>Read current state</li><li><span>2</span>Review changes</li><li><span>3</span>Approve & verify</li></ol></section>}

          {recentRuns.length > 0 && !run && !plan && <section className="card recent-runs reveal"><div className="section-heading"><div><p className="eyebrow">Continue safely</p><h2>Unfinished runs</h2></div><span className="no-write">Review only</span></div><p className="explanation">Inspect an earlier run and its approved plan. Opening it does not execute or resume anything.</p><div className="run-list">{recentRuns.map((item) => <div key={item.id}><div><strong>{item.id}</strong><span className={`status status-${item.status.toLowerCase()}`}>{titleCase(item.status)}</span><small>Updated {timestamp(item.updated_at)}</small></div><button className="button secondary-button" disabled={Boolean(loading)} onClick={() => openRun(item.id)}>Review run {item.id}</button></div>)}</div></section>}

          {plan && <section id="impact" className="card reveal"><div className="section-heading"><div><p className="eyebrow">02 / Plan review</p><h2>{plan.status === 'ready' ? 'Exact changes for approval' : plan.status === 'infeasible' ? 'That date cannot hold' : plan.status === 'clarification' ? 'Clarification needed' : 'Planning is blocked'}</h2></div><span className={`status status-${plan.status}`}>{titleCase(plan.status)}</span></div>
            <p className="explanation">{plan.explanation}</p>
            {plan.requested_date && <p className="resolved-date"><span>Resolved requested date</span><strong>{dateLabel(plan.requested_date)}</strong></p>}
            {plan.status === 'ready' && <OperationTable operations={plan.operations} />}
            {plan.conflicts.length > 0 && <div className="conflicts">{plan.conflicts.map((conflict) => <div key={conflict}><span>Constraint</span><p>{conflict}</p></div>)}</div>}
            {dependencyItems.length > 0 && <div className="chain-section"><h3>Dependency path</h3><div className="chain" aria-label="Dependency chain">{dependencyItems.map((item, index) => { const next = dependencyItems[index + 1]; const edge = next && snapshot?.nodes.find((node) => node.id === next.id)?.predecessors.includes(item.id); return <div className={`chain-item ${item.disposition}`} key={item.id}><small>{item.id}</small><strong>{item.name}</strong><span>{item.after}</span><Source url={item.source_url} />{edge && <i>→</i>}</div> })}</div></div>}
            {additionalConstraints.length > 0 && <div className="preserved constraints"><h3>Additional constraints</h3>{additionalConstraints.map((item) => <div key={item.id}><span><strong>{item.name}</strong><small>{item.after}</small></span><Source url={item.source_url} /></div>)}</div>}
            {unrelatedItems.length > 0 && <div className="preserved"><h3>Unrelated and preserved</h3>{unrelatedItems.map((item) => <div key={item.id}><span><strong>{item.name}</strong><small>{item.after}</small></span><Source url={item.source_url} /></div>)}</div>}
            {plan.assumptions.length > 0 && <div className="assumptions"><strong>Planning assumptions</strong><ul>{plan.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></div>}
            {plan.status === 'infeasible' && plan.proposed_date && <div className="alternative"><div><p className="eyebrow">Earliest feasible alternative</p><strong>{dateLabel(plan.proposed_date)}</strong><span>This creates a new plan. You will review it before approval.</span></div><button className="button secondary-button" onClick={chooseAlternative} disabled={Boolean(loading)}>{loading === 'alternative' ? 'Building plan…' : `Plan for ${dateLabel(plan.proposed_date)}`}</button></div>}
            {plan.status === 'ready' && !run && <div className="approval"><div><p className="eyebrow">03 / Approval</p><strong>{plan.operations.length} {plan.operations.length === 1 ? 'change' : 'changes'} ready for your approval</strong><span>Approval authorizes only the exact changes above.</span><span>Snapshot captured {timestamp(snapshot?.captured_at)}</span><details className="plan-identity"><summary>Plan version {plan.version} · identity</summary><code>{plan.hash}</code></details></div><button className="button approve-button" onClick={approve} disabled={Boolean(loading)}>{loading === 'approve' ? 'Submitting once…' : approveFailed ? `Retry approval · v${plan.version}` : `Approve version ${plan.version}`}</button></div>}
          </section>}

          {run && <section id="execution" className="card reveal run-card" aria-live="polite"><div className="section-heading"><div><p className="eyebrow">04 / Execution</p><h2>{verified ? 'Verified' : titleCase(run.status)}</h2></div><span className={`status status-${run.status.toLowerCase()}`}>{titleCase(run.status)}</span></div>
            <p className="explanation">{verified ? 'Every approved value was read back from its source.' : run.reason || (ACTIVE.has(run.status) ? 'Applying approved changes and reading each source back.' : 'The run stopped before verification completed.')}</p>
            {ACTIVE.has(run.status) && <div className="progress"><span /><small>Run {run.id} · polling for durable status</small></div>}
            <div className="run-times"><span>Started {timestamp(run.created_at)}</span><span>Updated {timestamp(run.updated_at)}</span></div>
            {statusError && <button className="button secondary-button retry-status" onClick={() => void loadRun(run.id)} disabled={Boolean(loading)}>Retry status check</button>}
            <OperationTable operations={run.operations} running />
            {run.verification && <div className="verification"><strong>Read-back verification</strong><Fields value={Object.fromEntries(Object.entries(run.verification).filter(([key]) => ['checked_at', 'constraints_passed', 'preservation_passed', 'verified_operations'].includes(key)))} /><Evidence value={run.verification} label="Verification details" /></div>}
            {RESUMABLE.has(run.status) && <button className="button secondary-button resume" onClick={resume} disabled={Boolean(loading)}>{loading === 'resume' ? 'Resuming safely…' : 'Resume unfinished work'}</button>}
            {run.status === 'EXHAUSTED' && <button className="button secondary-button resume" onClick={reviewRecoveryPlan} disabled={Boolean(loading)}>{loading === 'recovery' ? 'Preparing recovery plan…' : 'Review recovery plan'}</button>}
          </section>}
        </div>

        <aside><section className="side-card" id="connections"><div className="aside-heading"><h2>Connections</h2><button className="refresh-button" onClick={refreshConnections} disabled={Boolean(loading)} aria-label="Refresh connections"><svg className={loading === 'health' ? 'rotating' : ''} viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6.3 7a7 7 0 0 1 11.4-1L20 9M4 15l2.3 3a7 7 0 0 0 11.4-1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /></svg></button></div><p className="aside-description">Source access and request interpretation.</p><div className="connections">{health?.connections.map((connection) => { const name = connection.provider ?? connection.name ?? 'source'; return <div key={name}><span className="provider-icon" aria-hidden="true">{name === 'calendar' ? 'C' : name.slice(0, 1).toUpperCase()}</span><div><strong>{name === 'calendar' ? 'Google Calendar' : titleCase(name)}</strong><small>{connection.detail}</small></div><em><span className={`connection-dot ${connection.status}`} />{titleCase(connection.status)}</em></div> }) ?? <p className="connection-placeholder">{loading === 'health' ? 'Checking source access…' : 'Could not load connection status. Refresh to try again.'}</p>}
          {health && <div><span className="provider-icon" aria-hidden="true">P</span><div><strong>Request planner</strong><small>{health.model.detail}</small></div><em><span className={`connection-dot ${health.model.status}`} />{titleCase(health.model.status)}</em></div>}</div>
          {Boolean(health?.setup_required.length) && <details className="setup-details" open><summary>Required configuration <span>{health?.setup_required.length}</span></summary><p>Configure these values on the backend, then refresh connections.</p><div className="setup-list">{health?.setup_required.map((item) => <code key={item}>{item}</code>)}</div></details>}
          </section>
          <section className="side-card project-context"><h2>Project context</h2><dl><div><dt>Baseline deadline</dt><dd>{snapshot ? dateLabel(snapshot.project.deadline) : 'Awaiting snapshot'}</dd></div><div><dt>Timezone</dt><dd>{health?.project.timezone ?? 'Unavailable'}</dd></div><div><dt>Snapshot</dt><dd>{snapshot ? timestamp(snapshot.captured_at) : 'Read on analysis'}</dd></div></dl></section>
          <section className="side-card trust"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m12 3 8 3v6c0 4-8 9-8 9s-8-5-8-9V6l8-3Z" stroke="currentColor" strokeWidth="1.5"/><path d="m8 12 3 3 5-6" stroke="currentColor" strokeWidth="1.5"/></svg><div><h3>You approve every change</h3><p>Planning is read-only. Approved changes are applied and read back from each source.</p></div></section>
        </aside>
      </div>
    </main>
    <footer><span>Deadline Relay</span><span>Plan → Approve → Verify</span></footer>
  </div>
}
