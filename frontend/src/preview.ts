import type { LocalIP, PortRow, SourceReport } from './types'

const proc = (pid: number, name: string, cmdline: string[]): PortRow['process'] => ({
  pid,
  status: 'ok',
  name,
  cmdline,
})

export const previewPorts: PortRow[] = [
  {
    id: 'web',
    proto: 'tcp',
    bind: '127.0.0.1',
    port: 3000,
    pid: 8421,
    process: proc(8421, 'bun', ['bun', 'run', 'dev']),
    docker: [],
    tunnels: [
      { pid: 8360, hostname: 'app.example.com', host: 'localhost', port: 3000, path: null },
    ],
    tags: [],
    origin: 'socket',
  },
  {
    id: 'api',
    proto: 'tcp',
    bind: '127.0.0.1',
    port: 8000,
    pid: 8436,
    process: proc(8436, 'python3', ['uvicorn', 'app.main:app', '--reload']),
    docker: [],
    tunnels: [],
    tags: [],
    origin: 'socket',
  },
  {
    id: 'postgres',
    proto: 'tcp',
    bind: '0.0.0.0',
    port: 5432,
    pid: null,
    process: null,
    docker: [
      {
        container_id: '4fba1180',
        container_name: 'workspace-db',
        host_bind: '0.0.0.0',
        host_port: 5432,
        container_port: 5432,
        proto: 'tcp',
        compose_project: 'workspace',
        compose_service: 'db',
      },
    ],
    tunnels: [],
    tags: [],
    origin: 'docker',
  },
  {
    id: 'redis',
    proto: 'tcp',
    bind: '127.0.0.1',
    port: 6379,
    pid: null,
    process: null,
    docker: [
      {
        container_id: '7ae51b21',
        container_name: 'workspace-cache',
        host_bind: '127.0.0.1',
        host_port: 6379,
        container_port: 6379,
        proto: 'tcp',
        compose_project: 'workspace',
        compose_service: 'cache',
      },
    ],
    tunnels: [],
    tags: [],
    origin: 'docker',
  },
  {
    id: 'vite',
    proto: 'tcp',
    bind: '127.0.0.1',
    port: 5173,
    pid: 9120,
    process: proc(9120, 'bun', ['bun', '--bun', 'vite']),
    docker: [],
    tunnels: [],
    tags: [],
    origin: 'socket',
  },
  {
    id: 'dns',
    proto: 'udp',
    bind: '*',
    port: 5353,
    pid: 402,
    process: { pid: 402, status: 'access_denied', name: 'mDNSResponder', cmdline: null },
    docker: [],
    tunnels: [],
    tags: [],
    origin: 'socket',
  },
]
export const previewLocalIPs: LocalIP[] = [
  { interface: 'en0', address: '192.168.1.42', family: 'ipv4' },
  { interface: 'lo0', address: '127.0.0.1', family: 'ipv4' },
]
export const previewReports: SourceReport[] = [
  { source: 'listeners', status: 'ok', message: null },
  { source: 'processes', status: 'partial', message: 'Część danych procesów jest niedostępna.' },
  { source: 'docker', status: 'ok', message: null },
  { source: 'tunnels', status: 'ok', message: null },
]

export function filterPreview(ports: PortRow[], query: string): string[] {
  const text = query.trim().toLowerCase()
  if (!text) return ports.map((row) => row.id)
  if (text.startsWith(':'))
    return /^:\d+$/.test(text)
      ? ports.filter((row) => row.port === Number(text.slice(1))).map((row) => row.id)
      : []
  if (text.startsWith('pid:'))
    return /^pid:\d+$/.test(text)
      ? ports.filter((row) => row.pid === Number(text.slice(4))).map((row) => row.id)
      : []
  return ports
    .filter((row) =>
      [
        row.proto,
        row.bind,
        row.port,
        row.pid,
        row.process?.name,
        ...(row.process?.cmdline ?? []),
        ...row.docker.flatMap((item) => [
          item.container_name,
          item.compose_project,
          item.compose_service,
        ]),
        ...row.tunnels.map((item) => item.hostname),
        ...row.tags.map((item) => item.name),
        row.origin,
      ]
        .join(' ')
        .toLowerCase()
        .includes(text),
    )
    .map((row) => row.id)
}
