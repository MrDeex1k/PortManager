import type { LocalIP, PortRow, SourceReport } from './types'

export interface AppInfo {
  name: string
  version: string
  mode: 'desktop' | 'browser'
  stage: 'preview' | 'live'
  kube_enabled: boolean
}

export interface SnapshotSuccess {
  ok: true
  busy: false
  request_id: number
  generation: number
  kube_enabled: boolean
  collected_at: string
  ports: PortRow[]
  local_ips: LocalIP[]
  reports: SourceReport[]
}
export interface BridgeFailure {
  ok: false
  busy?: boolean
  message?: string
  request_id?: number
  generation?: number
}
export type SnapshotResult = SnapshotSuccess | BridgeFailure
export type FilterResult = { ok: true; generation: number; ids: string[] } | BridgeFailure
export interface KillTargetView {
  pid: number
  name: string
  executable: string
  cmdline: string[]
}
export type PrepareResult = { ok: true; token: string; target: KillTargetView } | BridgeFailure
export type ActionResult = { ok: true; status: 'terminated'; pid: number } | BridgeFailure
export type ExportResult =
  { ok: true; status: 'saved'; path: string } | { ok: true; status: 'cancelled' } | BridgeFailure
export interface DesktopBridge {
  set_kubernetes(enabled: boolean): Promise<{ ok: true; kube_enabled: boolean } | BridgeFailure>
  get_app_info(): Promise<AppInfo>
  read_snapshot(requestId: number, refreshKube?: boolean): Promise<SnapshotResult>
  filter_ports(generation: number, query: string | null): Promise<FilterResult>
  export_ports(generation: number, ids: string[]): Promise<ExportResult>
  prepare_process(pid: number): Promise<PrepareResult>
  terminate_process(token: string, force: boolean): Promise<ActionResult>
}

declare global {
  interface Window {
    pywebview?: { api?: DesktopBridge }
  }
}

export function desktopBridge(): DesktopBridge | undefined {
  return window.pywebview?.api
}

export async function getAppInfo(): Promise<AppInfo> {
  const api = window.pywebview?.api
  if (!api)
    return {
      name: 'PortManager',
      version: '0.1.0',
      mode: 'browser',
      stage: 'preview',
      kube_enabled: false,
    }
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      api.get_app_info(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('Aplikacja desktopowa nie odpowiada.')), 5000)
      }),
    ])
  } finally {
    clearTimeout(timer)
  }
}
