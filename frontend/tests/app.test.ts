import { afterEach, expect, test } from 'bun:test'
import { markRaw } from 'vue'
import { deferred, mountScript, settle } from './helpers/component'
import type { DesktopBridge, SnapshotResult, ActionResult } from '../src/desktop'
import type { AppInfo, PortRow } from '../src/types'
import { previewPorts } from '../src/preview'

const App = (await import('../src/App.vue')).default
const Inspector = (await import('../src/components/PortInspector.vue')).default
const row: PortRow = { ...previewPorts[0]!, id: 'real', bind: '::1', port: 9999 }
const info: AppInfo = {
  name: 'Audit',
  version: '1',
  mode: 'desktop',
  stage: 'live',
  kube_enabled: false,
  termination_mode: 'graceful',
}
function snapshot(id = 1, kube = false) {
  return {
    ok: true as const,
    busy: false as const,
    request_id: id,
    generation: id,
    kube_enabled: kube,
    collected_at: new Date().toISOString(),
    ports: [row],
    local_ips: [],
    reports: [],
    tunnels: [],
  }
}
const target = { pid: 123, name: 'audit', executable: '/audit', cmdline: [] }
function bridge(overrides: Partial<DesktopBridge> = {}): DesktopBridge {
  return {
    get_app_info: async () => info,
    read_snapshot: async (id) => snapshot(id),
    filter_ports: async (generation) => ({ ok: true, generation, ids: ['real'] }),
    set_kubernetes: async (enabled) => ({ ok: true, kube_enabled: enabled }),
    prepare_process: async () => ({ ok: true, token: 'one', target, escalation: false }),
    terminate_process: async () => ({ ok: true, pid: 123, status: 'terminated' }),
    cancel_process: async () => ({ ok: true, status: 'cancelled' }),
    export_ports: async () => ({ ok: true, status: 'cancelled' }),
    ...overrides,
  }
}
const mounted: ReturnType<typeof mountScript>[] = []
const originalWindow = Object.getOwnPropertyDescriptor(globalThis, 'window')
const originalNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
function mount(api?: DesktopBridge) {
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: Object.assign(new EventTarget(), api ? { pywebview: { api } } : {}),
  })
  const result = mountScript(App)
  mounted.push(result)
  return result
}
afterEach(() => {
  mounted.splice(0).forEach((instance) => instance.unmount())
  for (const [key, descriptor] of [
    ['window', originalWindow],
    ['navigator', originalNavigator],
  ] as const) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor)
    else Reflect.deleteProperty(globalThis, key)
  }
})

test('desktop never falls back to demo, including a busy first snapshot', async () => {
  const read = deferred<SnapshotResult>()
  const { state: s } = mount(bridge({ read_snapshot: () => read.promise }))
  await settle()
  expect(s.isPreview.value).toBe(false)
  expect(s.ports.value).toEqual([])
  expect(s.localIps.value).toEqual([])
  expect(s.partialReports.value).toEqual([])
  read.resolve({ ok: false, code: 'busy', message: 'busy', busy: true })
  await settle()
  expect(s.snapshot.value).toBeNull()
  expect(s.visible.value).toEqual([])
  expect(s.snapshotQuery.isError.value).toBe(false)
})

test('demo refresh is harmless and switching to desktop clears demo selection', async () => {
  const { state: s } = mount()
  await settle()
  s.refreshSnapshot()
  await settle()
  expect(s.snapshotQuery.isError.value).toBe(false)
  expect(s.ports.value.length).toBeGreaterThan(0)
  s.selectedId.value = 'web'
  const read = deferred<SnapshotResult>()
  window.pywebview = { api: bridge({ read_snapshot: () => read.promise }) }
  window.dispatchEvent(new Event('pywebviewready'))
  await settle()
  expect(s.selected.value).toBeNull()
  expect(s.ports.value).toEqual([])
  read.resolve(snapshot())
  await settle()
  expect(s.ports.value.map((p: PortRow) => p.id)).toEqual(['real'])
})

test('filter rejection is handled and the next query recovers', async () => {
  let fail = true
  const { state: s } = mount(
    bridge({
      filter_ports: async (generation) => {
        if (fail) throw new Error('connection lost')
        return { ok: true, generation, ids: [] }
      },
    }),
  )
  await settle()
  s.search.value = 'missing'
  await settle(170)
  expect(s.searchError.value).toContain('Nie udało się zastosować filtra')
  fail = false
  s.search.value = 'different'
  await settle(170)
  expect(s.searchError.value).toBe('')
  expect(s.visible.value).toEqual([])
})

test('a late rejection cannot overwrite a newer filter or mutate an unmounted component', async () => {
  const old = deferred<never>()
  const { state: s, unmount } = mount(
    bridge({
      filter_ports: async (generation, query) => {
        if (query === 'old') return old.promise
        return { ok: true, generation, ids: [] }
      },
    }),
  )
  await settle()
  s.search.value = 'old'
  await settle(170)
  s.search.value = 'new'
  await settle(170)
  old.reject(new Error('obsolete'))
  await settle()
  expect(s.searchError.value).toBe('')
  const pending = deferred<never>()
  window.pywebview!.api!.filter_ports = () => pending.promise
  s.search.value = 'last'
  await settle(170)
  unmount()
  pending.reject(new Error('after unmount'))
  await settle()
  expect(s.searchError.value).toBe('')
})

test('late application metadata cannot revert a confirmed Kubernetes toggle', async () => {
  const metadata = deferred<AppInfo>()
  let enabled = false
  const { state: s } = mount(
    bridge({
      get_app_info: () => metadata.promise,
      set_kubernetes: async (value) => {
        enabled = value
        return { ok: true, kube_enabled: value }
      },
      read_snapshot: async (id) => snapshot(id, enabled),
    }),
  )
  await settle()
  await s.toggleKubernetes()
  metadata.resolve(info)
  await settle()
  expect(s.kubeEnabled.value).toBe(true)
  expect(s.snapshot.value.kube_enabled).toBe(true)
})

test('Escape is prevented during termination and escalation stays visible', async () => {
  const action = deferred<ActionResult>()
  const { state: s } = mount(bridge({ terminate_process: () => action.promise }))
  await settle()
  s.killDialog.value = markRaw({
    open: false,
    showModal() {
      this.open = true
    },
    close() {
      this.open = false
    },
  })
  await s.requestKill(row)
  const operation = s.confirmKill()
  const cancel = new Event('cancel', { cancelable: true })
  s.onKillCancel(cancel)
  expect(cancel.defaultPrevented).toBe(true)
  action.resolve({
    ok: false,
    code: 'termination_pending',
    message: 'pending',
    continuation: {
      ok: true,
      token: 'two',
      target,
      escalation: true,
    },
  })
  await operation
  expect(s.killDialog.value.open).toBe(true)
  expect(s.pendingKill.value.token).toBe('two')
  expect(s.operationBusy.value).toBe(false)
  const idleCancel = new Event('cancel', { cancelable: true })
  s.onKillCancel(idleCancel)
  expect(idleCancel.defaultPrevented).toBe(false)
})

test('escalation arriving after unmount is revoked', async () => {
  const action = deferred<ActionResult>()
  const cancelled: string[] = []
  const { state: s, unmount } = mount(
    bridge({
      terminate_process: () => action.promise,
      cancel_process: async (token) => {
        cancelled.push(token)
        return { ok: true, status: 'cancelled' }
      },
    }),
  )
  await settle()
  s.killDialog.value = markRaw({ open: true, showModal() {}, close() {} })
  await s.requestKill(row)
  const operation = s.confirmKill()
  unmount()
  action.resolve({
    ok: false,
    code: 'termination_pending',
    message: 'pending',
    continuation: {
      ok: true,
      token: 'two',
      target,
      escalation: true,
    },
  })
  await operation
  expect(cancelled).toContain('two')
  expect(s.pendingKill.value).toBeNull()
})

test('inspector copies a bracketed IPv6 endpoint', async () => {
  let copied = ''
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: {
      clipboard: {
        writeText: async (text: string) => {
          copied = text
        },
      },
    },
  })
  const instance = mountScript(Inspector, { port: row, desktop: true, busy: false })
  mounted.push(instance)
  await instance.state.copyAddress()
  expect(copied).toBe('[::1]:9999')
})

test('large lists render one page while export includes all filtered rows in sorted order', async () => {
  let rows = Array.from({ length: 250 }, (_, index) => ({
    ...row,
    id: `row-${index}`,
    port: 10000 + index,
  })).reverse()
  let exported: string[] = []
  const { state: s } = mount(
    bridge({
      read_snapshot: async (id) => ({ ...snapshot(id), ports: rows }),
      export_ports: async (_generation, ids) => {
        exported = ids
        return { ok: true, status: 'cancelled' }
      },
    }),
  )
  await settle()
  expect(s.pageCount.value).toBe(3)
  expect(s.pageRows.value.length).toBe(100)
  s.page.value = 2
  await settle()
  expect(s.pageRows.value.length).toBe(50)
  await s.exportVisible()
  expect(exported).toEqual([...rows].sort((a, b) => a.port - b.port).map((p) => p.id))
  rows = rows.slice(0, 10)
  await s.snapshotQuery.refetch()
  await settle()
  expect(s.page.value).toBe(0)
  expect(s.pageRows.value.length).toBe(10)
})
