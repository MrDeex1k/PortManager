import type {
  AppInfo,
  SnapshotSuccess,
  BridgeFailure,
  PrepareSuccess,
  FilterSuccess,
  ActionSuccess,
  ExportSaved,
  Cancelled,
} from './contracts.generated'
export type { AppInfo, SnapshotSuccess, BridgeFailure, KillTargetView } from './contracts.generated'
export type SnapshotResult = SnapshotSuccess | BridgeFailure
export type FilterResult = FilterSuccess | BridgeFailure
export type PrepareResult = PrepareSuccess | BridgeFailure
export type ActionResult = ActionSuccess | BridgeFailure
export type ExportResult = ExportSaved | Cancelled | BridgeFailure
export interface DesktopBridge {
  set_kubernetes(enabled: boolean): Promise<{ ok: true; kube_enabled: boolean } | BridgeFailure>
  get_app_info(): Promise<AppInfo | BridgeFailure>
  read_snapshot(requestId: number, refreshKube?: boolean): Promise<SnapshotResult>
  filter_ports(generation: number, query: string | null): Promise<FilterResult>
  export_ports(generation: number, ids: string[]): Promise<ExportResult>
  cancel_process(token: string): Promise<Cancelled | BridgeFailure>
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
      termination_mode: 'graceful',
    }
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    const result = await Promise.race([
      api.get_app_info(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('Aplikacja desktopowa nie odpowiada.')), 5000)
      }),
    ])
    if ('ok' in result) throw new Error(result.message)
    return result
  } finally {
    clearTimeout(timer)
  }
}
