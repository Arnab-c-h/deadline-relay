import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import type { Health, Operation, Plan, Run, Snapshot } from './types'

const DEFAULT_REQUEST = 'Move Atlas Release 1.0 to September 18, 2026.'
const ACTIVE = new Set(['QUEUED', 'PREFLIGHT', 'EXECUTING', 'VERIFYING'])
const RESUMABLE = new Set(['PARTIAL', 'UNCERTAIN', 'FAILED'])
const UNFINISHED = new Set([...ACTIVE, ...RESUMABLE, 'EXHAUSTED'])

function actionKey() {
  return globalThis.crypto?.randomUUID?.() ?? `action-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function titleCase(value: string) {
  return value.toLowerCase().replace(/(^|_)(\w)/g, (_, space, letter) => `${space ? ' ' : ''}${letter.toUpperCase()}`)
}

function dateLabel(value: string | null) {
  if (!value) return 'Unknown date'
  const date = new Date(`${value}T12:00:00`)
  return new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric' }).format(date)
}

function formatValue(value: unknown) {
  if (typeof value === 'string') return value.replace('T', ' ').replace(/:00(?=[+-]|Z$)/, '')
  return JSON.stringify(value)
}

function timestamp(value: string | undefined) {
  if (!value) return 'Unavailable'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Kolkata' }).format(parsed)
}

function Fields({ value }: { value: Record<string, unknown> }) {
  return <div className="field-list">{Object.entries(value).map(([key, field]) => <span key={key}><small>{key}</small>{formatValue(field)}</span>)}</div>
}

function Source({ url }: { url: string | null }) {
  return url ? <a className="source" href={url} target="_blank" rel="noreferrer">Open source ↗</a> : null
}

function OperationTable({ operations, running = false }: { operations: Operation[]; running?: boolean }) {
  if (!operations.length) return null
  return <div className="table-wrap"><table>
    <thead><tr><th>Source</th><th>Record</th><th>Current</th><th>Approved change</th>{running && <th>Status</th>}</tr></thead>
    <tbody>{operations.map((operation) => <tr key={operation.id}>
      <td><span className={`provider ${operation.provider}`}>{operation.provider}</span></td>
      <td><strong>{operation.name}</strong><Source url={operation.source_url} /></td>
      <td><Fields value={operation.before} /></td><td><Fields value={operation.after} /></td>
      {running && <td><span className={`status status-${operation.status?.toLowerCase()}`}>{titleCase(operation.status ?? 'pending')}</span>{operation.attempts ? <small className="attempts">{operation.attempts} attempt{operation.attempts === 1 ? '' : 's'}</small> : null}{operation.evidence != null && <small className="evidence">Read-back: {formatValue(operation.evidence)}</small>}{operation.error && <small className="op-error">{operation.error}</small>}</td>}
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

  const setupBlocked = Boolean(health?.setup_required.length)
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
    <header className="masthead"><div className="brand"><span className="brand-mark">DR</span><span>Deadline Relay</span></div><div className="mode"><span className={`mode-dot ${health?.mode ?? 'unknown'}`} />{health?.mode === 'simulated' ? 'Simulated mode' : health?.mode === 'live' ? 'Live mode' : 'Checking mode'}</div></header>
    <main>
      <section className="hero"><div><p className="eyebrow">Coordinated release planning</p><h1>Move one deadline.<br />Keep every tool aligned.</h1><p className="lede">Preview the consequences across Notion, GitHub, and Calendar before a single record changes.</p></div><div className="step-index"><span>{run ? '04' : plan?.status === 'ready' ? '03' : plan ? '02' : '01'}</span><small>{run ? 'Run evidence' : plan?.status === 'ready' ? 'Approval' : plan ? 'Impact' : 'Request'}</small></div></section>

      {error && <div role="alert" className="alert error"><strong>Something needs attention</strong><span>{error}</span></div>}
      {setupBlocked && <div className="alert setup"><strong>Connection setup required</strong><span>Planning is paused until the backend can read every required source.</span><div className="setup-list">{health?.setup_required.map((item) => <code key={item}>{item}</code>)}</div></div>}

      <div className="workspace">
        <div className="primary">
          <section className="card request-card"><div className="section-heading"><div><p className="eyebrow">01 · Request</p><h2>What changed?</h2></div><span className="no-write">Preview only · no writes</span></div>
            <label htmlFor="request">Deadline request</label><textarea id="request" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} />
            <button className="button primary-button" onClick={analyze} disabled={!health || setupBlocked || Boolean(loading) || !prompt.trim()}>{loading === 'plan' ? <><span className="spinner" />Reading project state…</> : 'Analyze impact'}</button>
          </section>

          {recentRuns.length > 0 && !run && !plan && <section className="card recent-runs reveal"><div className="section-heading"><div><p className="eyebrow">Continue safely</p><h2>Unfinished runs</h2></div><span className="no-write">Review only</span></div><p className="explanation">Inspect an earlier run and its approved plan. Opening it does not execute or resume anything.</p><div className="run-list">{recentRuns.map((item) => <div key={item.id}><div><strong>{item.id}</strong><span className={`status status-${item.status.toLowerCase()}`}>{titleCase(item.status)}</span><small>Updated {timestamp(item.updated_at)}</small></div><button className="button secondary-button" disabled={Boolean(loading)} onClick={() => openRun(item.id)}>Review run {item.id}</button></div>)}</div></section>}

          {plan && <section className="card reveal"><div className="section-heading"><div><p className="eyebrow">02 · Impact</p><h2>{plan.status === 'ready' ? 'Exact changes for approval' : plan.status === 'infeasible' ? 'That date cannot hold' : plan.status === 'clarification' ? 'Clarification needed' : 'Planning is blocked'}</h2></div><span className={`status status-${plan.status}`}>{titleCase(plan.status)}</span></div>
            <p className="explanation">{plan.explanation}</p>
            {plan.requested_date && <p className="resolved-date"><span>Resolved requested date</span><strong>{dateLabel(plan.requested_date)}, 2026</strong></p>}
            {plan.conflicts.length > 0 && <div className="conflicts">{plan.conflicts.map((conflict) => <div key={conflict}><span>Constraint</span><p>{conflict}</p></div>)}</div>}
            {dependencyItems.length > 0 && <div className="chain-section"><h3>Dependency path</h3><div className="chain" aria-label="Dependency chain">{dependencyItems.map((item, index) => { const next = dependencyItems[index + 1]; const edge = next && snapshot?.nodes.find((node) => node.id === next.id)?.predecessors.includes(item.id); return <div className={`chain-item ${item.disposition}`} key={item.id}><small>{item.id}</small><strong>{item.name}</strong><span>{item.after}</span><Source url={item.source_url} />{edge && <i>→</i>}</div> })}</div></div>}
            {additionalConstraints.length > 0 && <div className="preserved constraints"><h3>Additional constraints</h3>{additionalConstraints.map((item) => <div key={item.id}><span><strong>{item.name}</strong><small>{item.after}</small></span><Source url={item.source_url} /></div>)}</div>}
            {unrelatedItems.length > 0 && <div className="preserved"><h3>Unrelated and preserved</h3>{unrelatedItems.map((item) => <div key={item.id}><span><strong>{item.name}</strong><small>{item.after}</small></span><Source url={item.source_url} /></div>)}</div>}
            {plan.assumptions.length > 0 && <div className="assumptions"><strong>Planning assumptions</strong><ul>{plan.assumptions.map((item) => <li key={item}>{item}</li>)}</ul></div>}
            {plan.status === 'infeasible' && plan.proposed_date && <div className="alternative"><div><p className="eyebrow">Earliest feasible alternative</p><strong>{dateLabel(plan.proposed_date)}, 2026</strong><span>This creates a new plan. You will review it before approval.</span></div><button className="button secondary-button" onClick={chooseAlternative} disabled={Boolean(loading)}>{loading === 'alternative' ? 'Building plan…' : `Plan for ${dateLabel(plan.proposed_date)}`}</button></div>}
            {plan.status === 'ready' && <><OperationTable operations={plan.operations} />{!run && <div className="approval"><div><p className="eyebrow">03 · Explicit approval</p><strong>Plan version {plan.version}</strong><code>{plan.hash}</code><span>Approval authorizes only the {plan.operations.length} exact {plan.operations.length === 1 ? 'change' : 'changes'} above.</span><span>Snapshot captured {timestamp(snapshot?.captured_at)}</span></div><button className="button approve-button" onClick={approve} disabled={Boolean(loading)}>{loading === 'approve' ? 'Submitting once…' : approveFailed ? `Retry approval · v${plan.version}` : `Approve version ${plan.version}`}</button></div>}</>}
          </section>}

          {run && <section className="card reveal run-card"><div className="section-heading"><div><p className="eyebrow">04 · Run evidence</p><h2>{verified ? 'Verified' : titleCase(run.status)}</h2></div><span className={`status status-${run.status.toLowerCase()}`}>{titleCase(run.status)}</span></div>
            <p className="explanation">{verified ? 'Every approved value was read back from its source.' : run.reason || (ACTIVE.has(run.status) ? 'Applying approved changes and reading each source back.' : 'The run stopped before verification completed.')}</p>
            {ACTIVE.has(run.status) && <div className="progress"><span /><small>Run {run.id} · polling for durable status</small></div>}
            <div className="run-times"><span>Started {timestamp(run.created_at)}</span><span>Updated {timestamp(run.updated_at)}</span></div>
            {statusError && <button className="button secondary-button retry-status" onClick={() => void loadRun(run.id)} disabled={Boolean(loading)}>Retry status check</button>}
            <OperationTable operations={run.operations} running />
            {run.verification && <div className="verification"><span>Read-back verification</span><code>{JSON.stringify(run.verification)}</code></div>}
            {RESUMABLE.has(run.status) && <button className="button secondary-button resume" onClick={resume} disabled={Boolean(loading)}>{loading === 'resume' ? 'Resuming safely…' : 'Resume unfinished work'}</button>}
            {run.status === 'EXHAUSTED' && <button className="button secondary-button resume" onClick={reviewRecoveryPlan} disabled={Boolean(loading)}>{loading === 'recovery' ? 'Preparing recovery plan…' : 'Review recovery plan'}</button>}
          </section>}
        </div>

        <aside><section className="side-card"><p className="eyebrow">Project context</p><h3>{health?.project.name ?? 'Loading project…'}</h3><dl><div><dt>Current deadline</dt><dd>{snapshot ? dateLabel(snapshot.project.deadline) : 'September 25, 2026'}</dd></div><div><dt>Timezone</dt><dd>{health?.project.timezone ?? 'Asia/Kolkata'}</dd></div><div><dt>Planning rule</dt><dd>Working days only</dd></div></dl></section>
          <section className="side-card"><p className="eyebrow">Sources</p><div className="connections">{health?.connections.map((connection) => { const name = connection.provider ?? connection.name ?? 'source'; return <div key={name}><span className={`connection-dot ${connection.status}`} /><div><strong>{titleCase(name)}</strong><small>{connection.detail}</small></div><em>{titleCase(connection.status)}</em></div> }) ?? <span className="skeleton" />}</div></section>
          <section className="side-card trust"><p className="eyebrow">Authority boundary</p><p>Reading and planning do not modify records. Execution uses the approved version and hash, then verifies each result.</p></section>
        </aside>
      </div>
    </main>
    <footer><span>Deadline Relay · Local demo</span><span>Notion / GitHub / Google Calendar</span></footer>
  </div>
}
