export type Probe = { status: 'up' | 'down'; duration_ms: number; error: string | null }
export type StorageHealth = { status: 'ok' | 'degraded'; cassandra: Probe; postgresql: Probe }
export type Health = { status: 'ok'; service: 'cyberguard-api'; version: string }

async function request(path: string): Promise<{ response: Response; body: unknown }> {
  const response = await fetch(path, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
    signal: AbortSignal.timeout(12000),
  })
  const body: unknown = await response.json()
  return { response, body }
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object'
}

function isProbe(value: unknown): value is Probe {
  return record(value)
    && (value.status === 'up' || value.status === 'down')
    && typeof value.duration_ms === 'number' && Number.isFinite(value.duration_ms) && value.duration_ms >= 0
    && (value.status === 'up' ? value.error === null : typeof value.error === 'string')
}

export async function getHealth(): Promise<Health> {
  const { response, body } = await request('/api/health')
  if (!response.ok || !record(body) || body.status !== 'ok' || body.service !== 'cyberguard-api' || typeof body.version !== 'string') {
    throw new Error('A API não retornou uma resposta válida.')
  }
  return body as Health
}

export async function getStorageHealth(): Promise<StorageHealth> {
  const { response, body } = await request('/api/health/storage')
  if (!record(body) || !isProbe(body.cassandra) || !isProbe(body.postgresql)) {
    throw new Error('Não foi possível verificar as fontes de dados.')
  }
  const ready = body.cassandra.status === 'up' && body.postgresql.status === 'up'
  if (response.status !== (ready ? 200 : 503) || body.status !== (ready ? 'ok' : 'degraded')) {
    throw new Error('O estado das fontes de dados é inconsistente.')
  }
  return body as StorageHealth
}

export function describeProbe(error: string | null): string {
  switch (error) {
    case 'timeout': return 'Tempo limite excedido.'
    case 'connection_failed': return 'Não foi possível abrir a conexão.'
    case 'query_failed': return 'A consulta de verificação falhou.'
    case 'unexpected_response': return 'Resposta inesperada do banco.'
    case 'connection_close_failed': return 'A conexão não foi encerrada corretamente.'
    default: return 'Verificação indisponível.'
  }
}
