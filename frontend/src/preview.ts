import type { LocalIP, PortRow, SourceReport, TunnelInfo } from './types'
import { casefold } from './casefold'

const proc = (pid: number, name: string, cmdline: string[]): PortRow['process'] => ({
  pid,
  status: 'ok',
  name,
  cmdline,
})

export const previewPorts: PortRow[] = [
  {
    id: 'web',
    udp_peer_status: 'not_applicable',
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
    kubernetes: [],
    origin: 'socket',
  },
  {
    id: 'api',
    udp_peer_status: 'not_applicable',
    proto: 'tcp',
    bind: '127.0.0.1',
    port: 8000,
    pid: 8436,
    process: proc(8436, 'python3', ['uvicorn', 'app.main:app', '--reload']),
    docker: [],
    tunnels: [],
    tags: [],
    kubernetes: [],
    origin: 'socket',
  },
  {
    id: 'postgres',
    udp_peer_status: 'not_applicable',
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
    kubernetes: [],
    origin: 'docker',
  },
  {
    id: 'redis',
    udp_peer_status: 'not_applicable',
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
    kubernetes: [],
    origin: 'docker',
  },
  {
    id: 'vite',
    udp_peer_status: 'not_applicable',
    proto: 'tcp',
    bind: '127.0.0.1',
    port: 5173,
    pid: 9120,
    process: proc(9120, 'bun', ['bun', '--bun', 'vite']),
    docker: [],
    tunnels: [],
    tags: [],
    kubernetes: [],
    origin: 'socket',
  },
  {
    id: 'dns',
    udp_peer_status: 'absent',
    proto: 'udp',
    bind: '*',
    port: 5353,
    pid: 402,
    process: { pid: 402, status: 'access_denied', name: 'mDNSResponder', cmdline: null },
    docker: [],
    tunnels: [],
    tags: [],
    kubernetes: [],
    origin: 'socket',
  },
  {
    id: 'kube-nodeport',
    udp_peer_status: 'not_applicable',
    proto: 'tcp',
    bind: '192.168.1.42',
    port: 31080,
    pid: null,
    process: null,
    docker: [],
    tunnels: [],
    tags: [],
    origin: 'kubernetes',
    kubernetes: [
      {
        kind: 'nodeport',
        namespace: 'demo',
        resource: 'service/web',
        remote_port: '80',
        context: null,
        node: 'worker-demo',
      },
    ],
  },
  {
    id: 'kube-forward',
    udp_peer_status: 'not_applicable',
    proto: 'tcp',
    bind: '127.0.0.1',
    port: 8080,
    pid: 9100,
    process: {
      pid: 9100,
      status: 'ok',
      name: 'kubectl',
      cmdline: [
        'kubectl',
        '--context=dev-demo',
        '-n',
        'demo',
        'port-forward',
        'svc/api',
        '8080:http',
      ],
    },
    docker: [],
    tunnels: [],
    tags: [],
    origin: 'socket',
    kubernetes: [
      {
        kind: 'port-forward',
        namespace: 'demo',
        resource: 'svc/api',
        remote_port: 'http',
        context: 'dev-demo',
        node: null,
      },
    ],
  },
]
export const previewLocalIPs: LocalIP[] = [
  { interface: 'en0', address: '192.168.1.42', family: 'ipv4' },
  { interface: 'lo0', address: '127.0.0.1', family: 'ipv4' },
]
const reportDefaults = {
  last_success_at: null,
  age_seconds: null,
  stale: false,
  refreshing: false,
  code: null,
}
export const previewReports: SourceReport[] = [
  { ...reportDefaults, source: 'listeners', status: 'ok', message: null },
  {
    ...reportDefaults,
    source: 'processes',
    status: 'partial',
    message: 'Część danych procesów jest niedostępna.',
  },
  { ...reportDefaults, source: 'docker', status: 'ok', message: null },
  { ...reportDefaults, source: 'tunnels', status: 'ok', message: null },
]

export function filterPreview(ports: PortRow[], query: string): string[] {
  const text = casefold(query.trim())
  if (!text) return ports.map((row) => row.id)
  if (text.startsWith(':') && !text.startsWith('::'))
    return /^:[0-9]+$/.test(text) && Number(text.slice(1)) >= 1 && Number(text.slice(1)) <= 65535
      ? ports.filter((row) => row.port === Number(text.slice(1))).map((row) => row.id)
      : []
  if (text.startsWith('pid:'))
    return /^pid:\d+$/.test(text)
      ? ports.filter((row) => row.pid === Number(text.slice(4))).map((row) => row.id)
      : []
  return ports.filter((row) => casefold(searchText(row)).includes(text)).map((row) => row.id)
}

function searchText(row: PortRow): string {
  const fields = [row.proto, row.bind, String(row.port), row.origin]
  if (row.pid !== null) fields.push(String(row.pid))
  if (row.process) fields.push(row.process.name ?? '', ...(row.process.cmdline ?? []))
  for (const item of row.docker)
    fields.push(
      item.container_id,
      item.container_name,
      item.compose_project ?? '',
      item.compose_service ?? '',
    )
  fields.push(...row.tunnels.map((item) => item.hostname ?? ''))
  fields.push(...row.tags.map((item) => item.name))
  for (const item of row.kubernetes)
    fields.push(
      'kubernetes',
      item.kind,
      item.namespace ?? '',
      item.resource,
      item.remote_port,
      item.context ?? '',
      item.node ?? '',
    )
  return fields.join(' ')
}

export const previewTunnels: TunnelInfo[] = [
  {
    pid: 8360,
    routes: previewPorts[0]!.tunnels,
    config_status: 'explicit',
    metrics_status: 'ok',
    connections: 4,
    config_code: null,
    metrics_code: null,
  },
]
