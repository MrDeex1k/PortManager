// Wyłącznie fixture prototypu. Integracja i filtry core powstaną w Fazie 7.2.
export interface PreviewPort {
  id: string
  port: number
  protocol: 'TCP' | 'UDP'
  bind: string
  pid: number | null
  process: string
  command: string
  service: string
  container?: { name: string; port: number; project: string }
  tunnel?: string
}

export type SourceFilter = 'all' | 'docker' | 'tunnels'
export type ProtocolFilter = 'all' | 'TCP' | 'UDP'

export const previewPorts: PreviewPort[] = [
  {
    id: 'web',
    port: 3000,
    protocol: 'TCP',
    bind: '127.0.0.1',
    pid: 8421,
    process: 'bun',
    command: 'bun run dev --port 3000',
    service: 'Frontend',
    tunnel: 'app.example.com',
  },
  {
    id: 'api',
    port: 8000,
    protocol: 'TCP',
    bind: '127.0.0.1',
    pid: 8436,
    process: 'python3',
    command: 'uvicorn app.main:app --reload --port 8000',
    service: 'API lokalne',
  },
  {
    id: 'postgres',
    port: 5432,
    protocol: 'TCP',
    bind: '0.0.0.0',
    pid: null,
    process: 'postgres',
    command: 'postgres -c log_statement=none',
    service: 'Baza danych',
    container: { name: 'workspace-db', port: 5432, project: 'workspace' },
  },
  {
    id: 'redis',
    port: 6379,
    protocol: 'TCP',
    bind: '127.0.0.1',
    pid: null,
    process: 'redis-server',
    command: 'redis-server --appendonly yes',
    service: 'Cache',
    container: { name: 'workspace-cache', port: 6379, project: 'workspace' },
  },
  {
    id: 'vite',
    port: 5173,
    protocol: 'TCP',
    bind: '127.0.0.1',
    pid: 9120,
    process: 'bun',
    command: 'bun --bun vite --host 127.0.0.1',
    service: 'PortManager UI',
  },
  {
    id: 'nginx',
    port: 8080,
    protocol: 'TCP',
    bind: '0.0.0.0',
    pid: null,
    process: 'nginx',
    command: 'nginx -g daemon off;',
    service: 'Reverse proxy',
    container: { name: 'workspace-proxy', port: 80, project: 'workspace' },
    tunnel: 'preview.example.com',
  },
  {
    id: 'dns',
    port: 5353,
    protocol: 'UDP',
    bind: '*',
    pid: 402,
    process: 'mDNSResponder',
    command: '/usr/sbin/mDNSResponder',
    service: 'Wykrywanie usług',
  },
  {
    id: 'metrics',
    port: 20241,
    protocol: 'TCP',
    bind: '127.0.0.1',
    pid: 8360,
    process: 'cloudflared',
    command: 'cloudflared tunnel --metrics 127.0.0.1:20241 run workspace',
    service: 'Metryki tunelu',
  },
]

export function filterPreview(
  ports: PreviewPort[],
  query: string,
  source: SourceFilter,
  protocol: ProtocolFilter,
): PreviewPort[] {
  const text = query.trim().toLowerCase()
  return ports.filter((row) => {
    if (source === 'docker' && !row.container) return false
    if (source === 'tunnels' && !row.tunnel) return false
    if (protocol !== 'all' && row.protocol !== protocol) return false
    if (text.startsWith(':')) return /^:\d+$/.test(text) && row.port === Number(text.slice(1))
    if (text.startsWith('pid:')) return /^pid:\d+$/.test(text) && row.pid === Number(text.slice(4))
    return [
      row.port,
      row.pid,
      row.bind,
      row.process,
      row.service,
      row.command,
      row.container?.name,
      row.tunnel,
    ]
      .join(' ')
      .toLowerCase()
      .includes(text)
  })
}
