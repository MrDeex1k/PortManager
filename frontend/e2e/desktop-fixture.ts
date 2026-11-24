import type { DesktopBridge } from '../src/desktop'
import type { PortRow } from '../src/types'

export interface DesktopFixture {
  ports: PortRow[]
  delayed?: boolean
}

declare global {
  interface Window {
    testDesktop: {
      releaseSnapshot(): void
      continueTermination?: () => void
      refreshes: number
      exported?: { generation: number; ids: string[] }
      cancelled: string[]
      terminated: { token: string; force: boolean }[]
    }
  }
}

// Flashwright serializes this function and executes it inside the page.
export function installDesktop({ ports, delayed }: DesktopFixture) {
  const target = { pid: 8421, name: 'bun', executable: '/test/bun', cmdline: ['bun', 'server.ts'] }
  let ready = !delayed
  let kubeEnabled = false
  let processExited = false
  const state: Window['testDesktop'] = {
    releaseSnapshot: () => {
      ready = true
    },
    refreshes: 0,
    cancelled: [],
    terminated: [],
  }
  const api: DesktopBridge = {
    get_app_info: async () => ({
      name: 'PortManager',
      version: '0.1.0',
      mode: 'desktop',
      stage: 'live',
      kube_enabled: kubeEnabled,
      termination_mode: 'graceful',
    }),
    read_snapshot: async (requestId, refreshKube) => {
      if (refreshKube) state.refreshes++
      if (!ready) return { ok: false, busy: true, code: 'busy', message: 'Trwa odczyt' }
      return {
        ok: true,
        busy: false,
        request_id: requestId,
        generation: 1,
        collected_at: '2026-01-01T00:00:00Z',
        kube_enabled: kubeEnabled,
        ports: processExited ? [] : ports,
        local_ips: [],
        tunnels: [],
        reports: [],
      }
    },
    set_kubernetes: async (enabled) => {
      kubeEnabled = enabled
      return { ok: true, kube_enabled: kubeEnabled }
    },
    filter_ports: async (generation, query) => {
      if (query === 'offline') throw new Error('Utracono połączenie')
      const ids = ports
        .filter((row) => query === null || String(row.port).startsWith(query))
        .map((row) => row.id)
      return { ok: true, generation, ids }
    },
    export_ports: async (generation, ids) => {
      state.exported = { generation, ids }
      return { ok: true, status: 'saved', path: '/test/export.json' }
    },
    prepare_process: async () => ({ ok: true, token: 'initial', target, escalation: false }),
    cancel_process: async (token) => {
      state.cancelled.push(token)
      return { ok: true, status: 'cancelled' }
    },
    terminate_process: async (token, force) => {
      state.terminated.push({ token, force })
      if (token === 'initial') {
        await new Promise<void>((resolve) => {
          state.continueTermination = resolve
        })
        return {
          ok: false,
          code: 'termination_pending',
          message: 'Proces nadal działa',
          continuation: { ok: true, token: 'escalation', target, escalation: true },
        }
      }
      processExited = true
      return { ok: true, pid: target.pid, status: 'terminated' }
    },
  }
  window.testDesktop = state
  window.pywebview = { api }
  window.dispatchEvent(new Event('pywebviewready'))
}
