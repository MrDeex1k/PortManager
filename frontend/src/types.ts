export interface DockerPort {
  container_id: string
  container_name: string
  host_bind: string
  host_port: number
  container_port: number
  proto: 'tcp' | 'udp'
  compose_project: string | null
  compose_service: string | null
}
export interface TunnelRoute {
  pid: number
  hostname: string | null
  host: string
  port: number
  path: string | null
}
export interface ServiceTag {
  name: 'k8s' | 'k3s' | 'microk8s'
  evidence: 'process' | 'port'
}
export interface ProcessInfo {
  pid: number | null
  status: 'ok' | 'unknown' | 'access_denied' | 'gone' | 'error'
  name: string | null
  cmdline: string[] | null
}
export interface PortRow {
  id: string
  proto: 'tcp' | 'udp'
  bind: string
  port: number
  pid: number | null
  process: ProcessInfo | null
  docker: DockerPort[]
  tunnels: TunnelRoute[]
  tags: ServiceTag[]
  origin: 'socket' | 'docker'
}
export interface LocalIP {
  interface: string
  address: string
  family: 'ipv4' | 'ipv6'
}
export interface SourceReport {
  source: string
  status: 'ok' | 'partial' | 'unavailable' | 'error' | 'disabled'
  message: string | null
}
export type SourceFilter = 'all' | 'docker' | 'tunnels'
export type ProtocolFilter = 'all' | 'tcp' | 'udp'
