export type Connection = { provider?: string; name?: string; status: string; detail: string }
export type Health = {
  mode: 'simulated' | 'live'
  project: { name: string; timezone: string }
  connections: Connection[]
  model: { status: string; detail: string }
  runs: { id: string; status: string; updated_at: string }[]
  setup_required: string[]
}

export type Snapshot = {
  id: string
  captured_at?: string
  mode: 'simulated' | 'live'
  project: { id: string; name: string; timezone: string; planning_start: string; horizon_days: number; deadline: string }
  nodes: { id: string; name: string; predecessors: string[]; source_url?: string | null }[]
  records: Record<string, unknown>
  config_hash: string
}

export type Operation = {
  id: string
  record_key: string
  provider: string
  resource_id: string
  name: string
  source_url: string | null
  before: Record<string, unknown>
  after: Record<string, unknown>
  status?: string
  attempts?: number
  evidence?: unknown
  error?: string | null
}

export type PlanItem = { id: string; name: string; kind: string; before: string; after: string; disposition: string; source_url: string | null }
export type Plan = {
  id: string; version: number; hash: string; snapshot_id: string; request: string
  status: 'ready' | 'infeasible' | 'blocked' | 'unsupported' | 'clarification'
  requested_date: string | null; proposed_date: string | null; explanation: string; conflicts: string[]
  operations: Operation[]; items: PlanItem[]; assumptions: string[]; created_at: string
  mode: 'simulated' | 'live'; interpretation: { method: string; model?: string; usage?: unknown }
}

export type Run = {
  id: string; plan_id: string; status: string; mode: 'simulated' | 'live'; created_at: string; updated_at: string
  reason: string | null; operations: Operation[]; verification?: Record<string, unknown>
}
