import type { Health, Plan, Run, Snapshot } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init.headers } : init?.headers,
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`)
  return payload as T
}

export const api = {
  health: () => request<Health>('/projects/demo/health'),
  snapshot: () => request<Snapshot>('/projects/demo/snapshots', { method: 'POST', body: '{}' }),
  getSnapshot: (id: string) => request<Snapshot>(`/snapshots/${id}`),
  plan: (snapshotId: string, prompt: string, alternative?: { date: string; parentId: string }) =>
    request<Plan>('/projects/demo/plans', { method: 'POST', body: JSON.stringify({ snapshot_id: snapshotId, request: prompt, ...(alternative && { alternative_date: alternative.date, parent_plan_id: alternative.parentId }) }) }),
  getPlan: (id: string) => request<Plan>(`/plans/${id}`),
  approve: (plan: Plan, key: string) => request<{ run_id: string }>(`/plans/${plan.id}/approve`, { method: 'POST', body: JSON.stringify({ version: plan.version, hash: plan.hash, idempotency_key: key }) }),
  run: (id: string) => request<Run>(`/runs/${id}`),
  resume: (id: string, key: string) => request<{ run_id: string }>(`/runs/${id}/resume`, { method: 'POST', body: JSON.stringify({ idempotency_key: key }) }),
  recoveryPlan: (id: string) => request<Plan>(`/runs/${id}/recovery-plan`, { method: 'POST', body: '{}' }),
}
