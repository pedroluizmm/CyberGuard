// Typed client for the CyberGuard API. Every call hits the real backend through the
// Vite proxy (/api -> 127.0.0.1:3000). Nothing here invents data: failures surface as
// ApiError with a kind the UI uses to tell "invalid", "unavailable" and "missing" apart.

export type Source = 'postgresql' | 'cassandra'
export const SOURCES: readonly Source[] = ['postgresql', 'cassandra']
export const SOURCE_LABEL: Record<Source, string> = { postgresql: 'PostgreSQL', cassandra: 'Cassandra' }
export const SOURCE_KIND: Record<Source, string> = { postgresql: 'Relacional · SQL', cassandra: 'Wide-column · CQL' }
export const SOURCE_SHORT: Record<Source, string> = { postgresql: 'PG', cassandra: 'CS' }
export const SOURCE_ICON: Record<Source, 'relational' | 'widecol'> = { postgresql: 'relational', cassandra: 'widecol' }

export type Probe = { status: 'up' | 'down'; duration_ms: number; error: string | null }
export type StorageHealth = { status: 'ok' | 'degraded'; cassandra: Probe; postgresql: Probe }
export type Health = { status: 'ok'; service: 'cyberguard-api'; version: string; build?: string }
export type Runtime = { build: string; cassandra_read_concurrency: number; postgres_synchronous_commit: string }

export const CATEGORIES = ['authentication', 'network', 'alert'] as const
export type Category = (typeof CATEGORIES)[number]
export const CATEGORY_LABEL: Record<Category, string> = { authentication: 'Autenticação', network: 'Rede', alert: 'Alerta' }
export const SEVERITY_LABEL = ['Informativo', 'Baixo', 'Médio', 'Alto', 'Crítico'] as const

export type Point = { t: string; total: number; by_category: number[]; by_severity: number[] }
export type Overview = {
  from: string
  to: string
  bucket: 'hour'
  filters: { category: Category | null; severity: number | null }
  total: number
  alerts: number
  by_category: number[]
  by_severity: number[]
  series: Point[]
}

export type EventData = {
  event_id: string
  occurred_at: string
  event_date: string
  device_id: string
  source_ip: string
  category: Category
  event_type: string
  severity: number
  outcome: string
  message: string
  metadata: Record<string, unknown>
}
export type Envelope = { data: EventData; revision: number }
export type EventPage = { items: Envelope[]; next_cursor: string | null }

export type ErrorKind = 'network' | 'unavailable' | 'invalid' | 'not_found' | 'timeout' | 'contract'
export class ApiError extends Error {
  constructor(readonly kind: ErrorKind, readonly code: string, message: string, readonly status?: number) {
    super(message)
  }
}

/** JSON with object keys sorted: lets the UI compare business results byte for byte. */
export function canonicalJson(raw: string): string {
  const sort = (v: unknown): unknown => Array.isArray(v) ? v.map(sort)
    : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sort((v as Record<string, unknown>)[k])])) : v
  return JSON.stringify(sort(JSON.parse(raw)))
}

/** Result plus the two latencies shown in the UI. */
export type Timed<T> = { data: T; httpMs: number; dbMs: number | null; raw: string }

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}
const numbers = (value: unknown, length: number) =>
  Array.isArray(value) && value.length === length && value.every((n) => Number.isFinite(n))

async function call<T>(path: string, valid: (body: unknown) => boolean, timeoutMs = 35000): Promise<Timed<T>> {
  const started = performance.now()
  let response: Response
  try {
    response = await fetch(path, { headers: { Accept: 'application/json' }, cache: 'no-store', signal: AbortSignal.timeout(timeoutMs) })
  } catch (error) {
    const timeout = error instanceof DOMException && (error.name === 'TimeoutError' || error.name === 'AbortError')
    throw new ApiError(timeout ? 'timeout' : 'network', timeout ? 'client_timeout' : 'network',
      timeout ? 'A requisição excedeu o tempo limite.' : 'Sem conexão com a API local.')
  }
  const raw = await response.text()
  const httpMs = performance.now() - started
  let body: unknown = null
  try { body = raw ? JSON.parse(raw) : null } catch { /* handled below */ }
  if (!response.ok) {
    const structured = record(body) && record(body.error)
    // Without the API's structured error body, a 5xx comes from the Vite proxy:
    // the API process itself is down, not the selected database.
    if (!structured && response.status >= 500) {
      throw new ApiError('network', 'api_unreachable', 'A API local não respondeu.', response.status)
    }
    const error = structured ? (body as { error: Record<string, unknown> }).error : {}
    const code = typeof error.code === 'string' ? error.code : `http_${response.status}`
    const kind: ErrorKind = response.status === 400 ? 'invalid' : response.status === 404 ? 'not_found'
      : code === 'operation_timeout' ? 'timeout' : 'unavailable'
    const message = typeof error.message === 'string' ? error.message : `HTTP ${response.status}`
    throw new ApiError(kind, code, message, response.status)
  }
  if (!valid(body)) throw new ApiError('contract', 'contract', 'Resposta fora do contrato esperado.', response.status)
  const timing = response.headers.get('Server-Timing')?.match(/dur=([\d.]+)/)
  return { data: body as T, httpMs, dbMs: timing ? Number(timing[1]) : null, raw }
}

const isOverview = (b: unknown) => record(b) && Number.isFinite(b.total) && Number.isFinite(b.alerts)
  && numbers(b.by_category, 3) && numbers(b.by_severity, 5) && Array.isArray(b.series)
  && b.series.every((p) => record(p) && typeof p.t === 'string' && numbers(p.by_category, 3) && numbers(p.by_severity, 5))
const isEnvelope = (e: unknown) => record(e) && Number.isInteger(e.revision) && record(e.data) && typeof e.data.event_id === 'string'
const isPage = (b: unknown) => record(b) && Array.isArray(b.items) && b.items.every(isEnvelope)
  && (b.next_cursor === null || typeof b.next_cursor === 'string')
const isProbe = (v: unknown): v is Probe => record(v) && (v.status === 'up' || v.status === 'down')
  && typeof v.duration_ms === 'number' && (v.status === 'up' ? v.error === null : typeof v.error === 'string')

export function overviewPath(source: Source, params: { from: string; to: string; category?: string | null; severity?: number | null }) {
  const query = new URLSearchParams({ from: params.from, to: params.to })
  if (params.category) query.set('category', params.category)
  if (params.severity) query.set('severity', String(params.severity))
  return `/api/${source}/stats/overview?${query}`
}

export const getOverview = (source: Source, params: Parameters<typeof overviewPath>[1]) =>
  call<Overview>(overviewPath(source, params), isOverview)

export type QueryKind = 'device' | 'ip' | 'alerts'
export function queryPath(source: Source, kind: QueryKind, value: string, from: string, to: string, pageSize: number, cursor?: string | null) {
  const key = kind === 'device' ? 'device_id' : kind === 'ip' ? 'source_ip' : 'severity'
  const query = new URLSearchParams({ [key]: value, from, to, page_size: String(pageSize) })
  if (cursor) query.set('cursor', cursor)
  return `/api/${source}/queries/${kind}?${query}`
}
export const getPage = (path: string) => call<EventPage>(path, isPage)
/** READ by UUID (the E1 operation): GET /api/{source}/events/{id}. */
export const getEvent = (source: Source, id: string) =>
  call<Envelope>(`/api/${source}/events/${encodeURIComponent(id)}`, isEnvelope)

export async function getHealth(): Promise<Health> {
  const { data } = await call<Health>('/api/health', (b) => record(b) && b.status === 'ok' && b.service === 'cyberguard-api', 12000)
  return data
}

export async function getStorageHealth(): Promise<StorageHealth> {
  // 503 is a valid, informative answer here (degraded): read the body either way.
  let response: Response
  try {
    response = await fetch('/api/health/storage', { headers: { Accept: 'application/json' }, cache: 'no-store', signal: AbortSignal.timeout(12000) })
  } catch {
    throw new ApiError('network', 'network', 'Sem conexão com a API local.')
  }
  let body: unknown = null
  try { body = await response.json() } catch { /* invalid */ }
  if (!record(body) || !isProbe(body.cassandra) || !isProbe(body.postgresql)) {
    throw new ApiError(response.status >= 500 ? 'network' : 'contract', 'contract', 'Não foi possível verificar os bancos.')
  }
  return body as unknown as StorageHealth
}

export async function getRuntime(): Promise<Runtime> {
  const { data } = await call<Runtime>('/api/runtime', (b) => record(b) && typeof b.build === 'string', 12000)
  return data
}

export function describeProbe(error: string | null): string {
  switch (error) {
    case 'timeout': return 'Tempo limite excedido'
    case 'connection_failed': return 'Conexão recusada'
    case 'query_failed': return 'Consulta de verificação falhou'
    case 'unexpected_response': return 'Resposta inesperada'
    default: return 'Indisponível'
  }
}

// ---------------------------------------------------------------- benchmarks
export type Stats = { n: number; median: number; p25: number; p75: number; p95: number; min: number; max: number; mean: number; stdev: number }
export type SourceResult = { http: Stats | null; db: Stats | null; errors: number; items: number | null; first_warmup_http_ms: number | null; raw_http: number[]; raw_db: (number | null)[] }
export type Operation = {
  id: string; experiment: string; title: string; params: Record<string, unknown>
  sources: Record<Source, SourceResult>; equivalent: boolean; paired_wins: Record<Source, number>
  faster?: Source; ratio?: number | null; iqr_separated?: boolean
}
export type WriteOp = Record<Source, { latency: Stats | null; throughput_ops_s: Stats | null; errors: number }>
export type Writes = { window: string[]; runs: number; warmup_runs?: number; events_per_run: number; concurrency: number; ops: Record<'create' | 'update' | 'delete', WriteOp>; window_total_after_cleanup: Record<Source, number | null> }
export type ControlEntry = { first_ms: number | null; raw_ms: number[]; stats: Stats | null }
export type BenchmarkRun = {
  run_id: string; suite: string; started_at: string; finished_at: string; complete: boolean
  protocol: Record<string, string | number | null>
  environment: { host?: Record<string, string | number>; docker?: Record<string, string | number>; dataset?: Record<string, unknown> }
  operations: Operation[]
  pg_control?: Record<string, ControlEntry | string>
  writes?: Writes
}
export type BenchmarkSummary = { generated_at: string; main: BenchmarkRun; n1: BenchmarkRun | null; writes?: BenchmarkRun | null; durability: BenchmarkRun | null }

export const getBenchmarks = () => call<BenchmarkSummary>('/api/benchmarks/summary',
  (b) => record(b) && record(b.main) && Array.isArray(b.main.operations), 15000)
