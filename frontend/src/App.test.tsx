import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

const health = {
  mode: 'simulated', project: { name: 'Atlas Release 1.0', timezone: 'Asia/Kolkata' },
  connections: [
    { provider: 'notion', status: 'simulated', detail: 'Fixture data' },
    { provider: 'github', status: 'simulated', detail: 'Fixture data' },
    { provider: 'calendar', status: 'simulated', detail: 'Fixture data' },
  ],
  model: { status: 'simulated', detail: 'Deterministic parser' }, runs: [], setup_required: [],
}

const snapshot = {
  id: 'snap-1', mode: 'simulated', config_hash: 'cfg', records: {}, nodes: [],
  project: { id: 'demo', name: 'Atlas Release 1.0', timezone: 'Asia/Kolkata', planning_start: '2026-09-14', horizon_days: 30, deadline: '2026-09-25' },
}

const infeasible = {
  id: 'plan-1', version: 1, hash: 'hash-one', snapshot_id: 'snap-1', request: 'Move Atlas Release 1.0 to September 18, 2026.',
  status: 'infeasible', requested_date: '2026-09-18', proposed_date: '2026-09-24', mode: 'simulated',
  explanation: 'The fixed security review occurs after the requested deadline.', conflicts: ['Security review is fixed on September 21.'],
  operations: [], items: [], assumptions: ['Weekends are non-working days.'], created_at: '2026-09-13T18:00:00Z', interpretation: { method: 'deterministic' },
}

const ready = {
  ...infeasible, id: 'plan-2', hash: 'hash-two', status: 'ready', request: 'Move Atlas Release 1.0 to September 24, 2026.',
  requested_date: '2026-09-24', explanation: 'September 24 is feasible.', conflicts: [],
  operations: [{ id: 'op-1', record_key: 'calendar:M2', provider: 'calendar', resource_id: 'm2', name: 'Release sign-off', source_url: 'https://example.test/m2', before: { start: '2026-09-25T15:00:00+05:30' }, after: { start: '2026-09-24T15:00:00+05:30' } }],
  items: [{ id: 'M1', name: 'Security review', kind: 'meeting', before: 'Sep 21', after: 'Sep 21', disposition: 'constraint', source_url: null }],
}

function mockFetch(responses: unknown[]) {
  const queue = [...responses]
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async () => {
    const body = queue.shift()
    if (body instanceof Error) throw body
    return { ok: true, status: 200, json: async () => body } as Response
  })
}

afterEach(() => vi.restoreAllMocks())

describe('Deadline Relay workflow', () => {
  it('shows missing planner configuration and enables planning after a real health refresh', async () => {
    const live = { ...health, mode: 'live', connections: health.connections.map((item) => ({ ...item, status: 'ready', detail: 'Resource accessible' })) }
    const fetcher = mockFetch([
      { ...live, model: { status: 'missing', detail: 'Model runtime required' }, setup_required: ['GEMINI_API_KEY'] },
      { ...live, model: { status: 'ready', detail: 'Planner configured' } },
    ])
    render(<App />)
    expect(await screen.findByText('Live · setup required')).toBeVisible()
    expect(screen.getByText('Model runtime required')).toBeVisible()
    await userEvent.type(screen.getByLabelText('Deadline request'), ready.request)
    expect(screen.getByRole('button', { name: 'Analyze impact' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Refresh connections' }))
    expect(await screen.findByText('Live · connected')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Analyze impact' })).toBeEnabled()
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/projects/demo/health', '/api/projects/demo/health'])
  })

  it('formats schedule values for review without exposing raw objects', async () => {
    const datedPlan = { ...ready, operations: [{ ...ready.operations[0], before: { Schedule: { start: '2026-09-25', end: '2026-09-25' }, Fixed: false }, after: { Schedule: { start: '2026-09-24', end: '2026-09-24' }, Fixed: true } }] }
    mockFetch([health, snapshot, datedPlan])
    render(<App />)
    await screen.findByText('Simulated mode')
    await userEvent.type(screen.getByLabelText('Deadline request'), ready.request)
    await userEvent.click(screen.getByRole('button', { name: 'Analyze impact' }))
    expect(await screen.findByRole('columnheader', { name: 'Proposed value' })).toBeVisible()
    expect(screen.getAllByText('September 25, 2026')).toHaveLength(2)
    expect(screen.getByText('Yes')).toBeVisible()
    expect(screen.queryByText(/\{"start"/)).not.toBeInTheDocument()
  })

  it('explains an infeasible request and requires a separate alternative plan', async () => {
    const fetcher = mockFetch([health, snapshot, infeasible, ready])
    render(<App />)
    expect(await screen.findByText('Simulated mode')).toBeVisible()
    expect(screen.getByLabelText('Deadline request')).toHaveValue('')
    await userEvent.type(screen.getByLabelText('Deadline request'), infeasible.request)
    await userEvent.click(screen.getByRole('button', { name: 'Analyze impact' }))
    expect(await screen.findByText(/fixed security review/i)).toBeVisible()
    expect(screen.queryByRole('button', { name: /approve/i })).not.toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Deadline request'))
    await userEvent.type(screen.getByLabelText('Deadline request'), 'A later unrelated edit')
    await userEvent.click(screen.getByRole('button', { name: /Plan for September 24/i }))
    expect(await screen.findByRole('button', { name: /Approve version 1/i })).toBeEnabled()
    const calls = fetcher.mock.calls
    expect(JSON.parse(String(calls[3][1]?.body))).toMatchObject({ request: infeasible.request, alternative_date: '2026-09-24', parent_plan_id: 'plan-1' })
  })

  it('prevents duplicate approval and keeps one idempotency key after a request failure', async () => {
    const fetcher = mockFetch([health, snapshot, ready, new Error('offline'), { run_id: 'run-1' }, { id: 'run-1', plan_id: 'plan-2', status: 'VERIFIED', mode: 'simulated', created_at: 'now', updated_at: 'now', reason: null, operations: [], verification: { status: 'verified' } }])
    render(<App />)
    await screen.findByText('Simulated mode')
    await userEvent.type(screen.getByLabelText('Deadline request'), infeasible.request)
    await userEvent.click(screen.getByRole('button', { name: 'Analyze impact' }))
    const approve = await screen.findByRole('button', { name: /Approve version 1/i })
    await userEvent.click(approve)
    expect(await screen.findByRole('alert')).toHaveTextContent('offline')
    await userEvent.click(screen.getByRole('button', { name: /Retry approval/i }))
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Verified' })).toBeVisible())
    const approvalBodies = fetcher.mock.calls.slice(3, 5).map((call) => JSON.parse(String(call[1]?.body)))
    expect(approvalBodies[0].idempotency_key).toBe(approvalBodies[1].idempotency_key)
    expect(approvalBodies[1]).toMatchObject({ version: 1, hash: 'hash-two' })
  })

  it('blocks planning when required connections are missing', async () => {
    mockFetch([{ ...health, setup_required: ['NOTION_TOKEN'], connections: [{ provider: 'notion', status: 'missing', detail: 'Token required' }] }])
    render(<App />)
    expect(await screen.findByText('Connection setup required')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Analyze impact' })).toBeDisabled()
    expect(screen.getByText('NOTION_TOKEN')).toBeVisible()
  })

  it('retries a failed status read without submitting approval again', async () => {
    const activeRun = { id: 'run-1', plan_id: 'plan-2', status: 'EXECUTING', mode: 'simulated', created_at: '2026-09-13T18:00:00Z', updated_at: '2026-09-13T18:00:01Z', reason: null, operations: [] }
    const fetcher = mockFetch([health, snapshot, ready, { run_id: 'run-1' }, activeRun, new Error('status connection lost'), { ...activeRun, status: 'VERIFIED', verification: { status: 'verified' } }])
    render(<App />)
    await screen.findByText('Simulated mode')
    await userEvent.type(screen.getByLabelText('Deadline request'), infeasible.request)
    await userEvent.click(screen.getByRole('button', { name: 'Analyze impact' }))
    await userEvent.click(await screen.findByRole('button', { name: /Approve version 1/i }))
    expect(await screen.findByRole('button', { name: 'Retry status check' }, { timeout: 2000 })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Retry status check' }))
    expect(await screen.findByRole('heading', { name: 'Verified' })).toBeVisible()
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes('/approve'))).toHaveLength(1)
  })

  it('shows unfinished runs after reload and opens one only on request', async () => {
    const paused = { id: 'run-old', status: 'PARTIAL', updated_at: '2026-09-13T17:30:00Z' }
    const oldRun = { id: 'run-old', plan_id: 'plan-old', status: 'PARTIAL', mode: 'simulated', created_at: '2026-09-13T17:00:00Z', updated_at: paused.updated_at, reason: 'GitHub needs attention', operations: [] }
    const oldPlan = { ...ready, id: 'plan-old', hash: 'old-hash' }
    const fetcher = mockFetch([{ ...health, runs: [paused, { id: 'done', status: 'VERIFIED', updated_at: 'now' }] }, oldRun, oldPlan, snapshot])
    render(<App />)
    expect(await screen.findByText('Unfinished runs')).toBeVisible()
    expect(fetcher).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: /Review run run-old/i }))
    expect(await screen.findByText('GitHub needs attention')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Resume unfinished work' })).toBeVisible()
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      '/api/projects/demo/health', '/api/runs/run-old', '/api/plans/plan-old', '/api/snapshots/snap-1',
    ])
  })

  it('treats VERIFIED as terminal and omits it from unfinished runs', async () => {
    mockFetch([{ ...health, runs: [{ id: 'verified-run', status: 'VERIFIED', updated_at: '2026-09-13T18:00:00Z' }] }])
    render(<App />)
    await screen.findByText('Simulated mode')
    expect(screen.queryByText('Unfinished runs')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /verified-run/i })).not.toBeInTheDocument()
  })

  it('turns an exhausted run into a fresh recovery plan that still requires approval', async () => {
    const exhausted = { id: 'run-exhausted', status: 'EXHAUSTED', updated_at: '2026-09-13T18:00:00Z' }
    const exhaustedRun = { id: exhausted.id, plan_id: 'plan-old', status: 'EXHAUSTED', mode: 'simulated', created_at: '2026-09-13T17:00:00Z', updated_at: exhausted.updated_at, reason: 'Retry budget exhausted', operations: [] }
    const oldPlan = { ...ready, id: 'plan-old', hash: 'old-hash' }
    const recoveryPlan = { ...ready, id: 'plan-recovery', snapshot_id: 'snap-recovery', hash: 'recovery-hash', request: 'Recover remaining approved edits' }
    const recoverySnapshot = { ...snapshot, id: 'snap-recovery', captured_at: '2026-09-13T18:01:00Z' }
    const fetcher = mockFetch([{ ...health, runs: [exhausted] }, exhaustedRun, oldPlan, snapshot, recoveryPlan, recoverySnapshot])
    render(<App />)
    await screen.findByText('Unfinished runs')
    await userEvent.click(screen.getByRole('button', { name: /Review run run-exhausted/i }))
    await userEvent.click(await screen.findByRole('button', { name: 'Review recovery plan' }))
    expect(await screen.findByRole('button', { name: 'Approve version 1' })).toBeVisible()
    expect(screen.queryByText('Retry budget exhausted')).not.toBeInTheDocument()
    expect(fetcher.mock.calls.at(-2)?.[0]).toBe('/api/runs/run-exhausted/recovery-plan')
    expect(fetcher.mock.calls.at(-2)?.[1]).toMatchObject({ method: 'POST', body: '{}' })
    expect(fetcher.mock.calls.at(-1)?.[0]).toBe('/api/snapshots/snap-recovery')
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes('/approve'))).toHaveLength(0)
  })

  it('uses real predecessor edges and keeps unrelated items outside the dependency chain', async () => {
    const linkedSnapshot = { ...snapshot, captured_at: '2026-09-13T18:00:00Z', nodes: [
      { id: 'M1', name: 'Security review', predecessors: ['T3'], source_url: 'https://example.test/m1' },
      { id: 'REL', name: 'Delivery', predecessors: ['M1'], source_url: null },
      { id: 'U1', name: 'Refresh careers-page copy', predecessors: [], source_url: null },
    ] }
    const linkedPlan = { ...ready, requested_date: '2026-09-24', assumptions: ['Weekends are non-working days.'], items: [
      { id: 'M1', name: 'Security review', kind: 'meeting', before: 'Sep 21', after: 'Sep 21', disposition: 'constraint', source_url: 'https://example.test/m1' },
      { id: 'REL', name: 'Delivery', kind: 'release', before: 'Sep 25', after: 'Sep 24', disposition: 'changed', source_url: null },
      { id: 'BUSY-1', name: 'Owner busy', kind: 'meeting', before: 'Sep 24 15:00', after: 'Sep 24 15:00', disposition: 'constraint', source_url: 'https://example.test/busy' },
      { id: 'U1', name: 'Refresh careers-page copy', kind: 'task', before: 'Sep 22', after: 'Sep 22', disposition: 'unrelated', source_url: null },
    ] }
    mockFetch([health, linkedSnapshot, linkedPlan])
    render(<App />)
    await screen.findByText('Simulated mode')
    await userEvent.type(screen.getByLabelText('Deadline request'), infeasible.request)
    await userEvent.click(screen.getByRole('button', { name: 'Analyze impact' }))
    expect(await screen.findByText('Dependency path')).toBeVisible()
    expect(screen.getByText('Additional constraints')).toBeVisible()
    expect(screen.getByText('Owner busy')).toBeVisible()
    expect(screen.getByText('Unrelated and preserved')).toBeVisible()
    expect(screen.getByText('Weekends are non-working days.')).toBeVisible()
    expect(screen.getByText(/Snapshot captured/)).toBeVisible()
    expect(screen.getAllByText('Open source ↗')).toHaveLength(3)
  })
})
