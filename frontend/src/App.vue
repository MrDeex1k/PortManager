<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useQuery } from '@tanstack/vue-query'
import {
  createColumnHelper,
  createSortedRowModel,
  FlexRender,
  rowSortingFeature,
  sortFn_basic,
  sortFn_text,
  tableFeatures,
  useTable,
} from '@tanstack/vue-table'
import {
  Activity,
  ArrowDown,
  ArrowDownToLine,
  ArrowUp,
  ArrowUpDown,
  Box,
  Check,
  ChevronRight,
  CircleAlert,
  CircleHelp,
  Globe2,
  Layers,
  Monitor,
  PanelRight,
  RefreshCw,
  Search,
  Server,
  X,
} from 'lucide-vue-next'
import AppIcon from './components/AppIcon.vue'
import PortInspector from './components/PortInspector.vue'
import { desktopBridge, getAppInfo } from './desktop'
import type { KillTargetView, SnapshotSuccess } from './desktop'
import { filterPreview, previewLocalIPs, previewPorts, previewReports } from './preview'
import type { PortRow, ProtocolFilter, SourceFilter } from './types'

const bridgeReady = ref(Boolean(desktopBridge()))
const requestId = ref(0)
const snapshot = ref<SnapshotSuccess | null>(null)
const source = ref<SourceFilter>('all')
const protocol = ref<ProtocolFilter>('all')
const search = ref('')
const searchError = ref('')
const matchedIds = ref(new Set(previewPorts.map((row) => row.id)))
const selectedId = ref<string | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const helpDialog = ref<HTMLDialogElement | null>(null)
const killDialog = ref<HTMLDialogElement | null>(null)
const pendingKill = ref<{ token: string; target: KillTargetView } | null>(null)
const forceKill = ref(false)
const operationBusy = ref(false)
const notice = ref('')
let filterTimer: ReturnType<typeof setTimeout> | undefined
let noticeTimer: ReturnType<typeof setTimeout> | undefined
let filterRequest = 0

const appQuery = useQuery({ queryKey: ['desktop-info', bridgeReady], queryFn: getAppInfo })
const snapshotQuery = useQuery({
  queryKey: ['system-snapshot', bridgeReady],
  enabled: bridgeReady,
  refetchInterval: 2000,
  queryFn: async () => {
    const api = desktopBridge()
    if (!api) throw new Error('Brak mostu aplikacji desktopowej.')
    const result = await api.read_snapshot(++requestId.value)
    if (!result.ok) {
      if (result.busy) return snapshot.value
      throw new Error(result.message ?? 'Nie udało się odczytać systemu.')
    }
    return result
  },
})
watch(snapshotQuery.data, (value) => {
  if (!value || (snapshot.value && value.request_id < snapshot.value.request_id)) return
  snapshot.value = value
  if (!search.value.trim()) matchedIds.value = new Set(value.ports.map((row) => row.id))
  else void applyCoreFilter()
})

const ports = computed(() => snapshot.value?.ports ?? previewPorts)
const localIps = computed(() => snapshot.value?.local_ips ?? previewLocalIPs)
const reports = computed(() => snapshot.value?.reports ?? previewReports)
const isPreview = computed(() => !bridgeReady.value)
const partialReports = computed(() =>
  reports.value.filter((item) => !['ok', 'disabled'].includes(item.status)),
)
const visible = computed(() =>
  ports.value
    .filter((row) => matchedIds.value.has(row.id))
    .filter((row) => protocol.value === 'all' || row.proto === protocol.value)
    .filter(
      (row) =>
        source.value === 'all' ||
        (source.value === 'docker' ? row.docker.length > 0 : row.tunnels.length > 0),
    ),
)
const selected = computed(() => ports.value.find((row) => row.id === selectedId.value) ?? null)
const sourceItems = computed(() => [
  { id: 'all' as const, label: 'Wszystkie porty', icon: Layers, count: ports.value.length },
  {
    id: 'docker' as const,
    label: 'Docker',
    icon: Box,
    count: ports.value.filter((p) => p.docker.length).length,
  },
  {
    id: 'tunnels' as const,
    label: 'Tunele',
    icon: Globe2,
    count: ports.value.filter((p) => p.tunnels.length).length,
  },
])
const protocols: { id: ProtocolFilter; label: string }[] = [
  { id: 'all', label: 'Wszystkie' },
  { id: 'tcp', label: 'TCP' },
  { id: 'udp', label: 'UDP' },
]
const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() })
const helper = createColumnHelper<typeof features, PortRow>()
const columns = helper.columns([
  helper.accessor('port', { header: 'Port', sortFn: sortFn_basic, sortDescFirst: false }),
  helper.accessor((row) => row.proto.toUpperCase(), {
    id: 'proto',
    header: 'Protokół',
    sortFn: sortFn_text,
  }),
  helper.accessor('bind', { header: 'Bind', sortFn: sortFn_text }),
  helper.accessor('pid', {
    header: 'PID',
    sortFn: sortFn_basic,
    cell: (info) => info.getValue() ?? '—',
  }),
  helper.accessor((row) => row.process?.name ?? '—', {
    id: 'process',
    header: 'Proces',
    sortFn: sortFn_text,
  }),
  helper.display({ id: 'relations', header: 'Powiązania' }),
  helper.accessor('origin', { header: 'Źródło', sortFn: sortFn_text }),
])
const table = useTable({
  features,
  columns,
  data: visible,
  getRowId: (row: PortRow) => row.id,
  initialState: { sorting: [{ id: 'port', desc: false }] },
})

async function applyCoreFilter() {
  clearTimeout(filterTimer)
  const request = ++filterRequest
  const generation = snapshot.value?.generation
  const query = search.value
  filterTimer = setTimeout(async () => {
    if (!bridgeReady.value || generation === undefined) {
      matchedIds.value = new Set(filterPreview(ports.value, query))
      searchError.value = ''
      return
    }
    const result = await desktopBridge()!.filter_ports(generation, query.trim() || null)
    if (request !== filterRequest) return
    if (result.ok && result.generation === snapshot.value?.generation) {
      matchedIds.value = new Set(result.ids)
      searchError.value = ''
    } else if (!result.ok) searchError.value = result.message ?? 'Nieprawidłowy filtr.'
  }, 140)
}
watch(search, () => void applyCoreFilter())
watch(ports, (rows) => {
  if (selectedId.value && !rows.some((row) => row.id === selectedId.value)) selectedId.value = null
})
function showNotice(message: string) {
  clearTimeout(noticeTimer)
  notice.value = message
  noticeTimer = setTimeout(() => {
    notice.value = ''
  }, 3800)
}
function resetFilters() {
  search.value = ''
  source.value = 'all'
  protocol.value = 'all'
}
async function exportVisible() {
  const current = snapshot.value
  if (!current) return showNotice('Natywny eksport jest dostępny w aplikacji desktopowej.')
  operationBusy.value = true
  const result = await desktopBridge()!.export_ports(
    current.generation,
    table.getRowModel().rows.map((row) => row.original.id),
  )
  operationBusy.value = false
  if (!result.ok) showNotice(result.message ?? 'Eksport nie powiódł się.')
  else if (result.status === 'saved') showNotice(`Zapisano ${result.path}`)
}
async function requestKill(row: PortRow) {
  if (row.pid === null || !desktopBridge()) return
  operationBusy.value = true
  const result = await desktopBridge()!.prepare_process(row.pid)
  operationBusy.value = false
  if (!result.ok) return showNotice(result.message ?? 'Procesu nie można zakończyć.')
  pendingKill.value = { token: result.token, target: result.target }
  forceKill.value = false
  killDialog.value?.showModal()
}
async function confirmKill() {
  const consent = pendingKill.value
  if (!consent) return
  operationBusy.value = true
  const result = await desktopBridge()!.terminate_process(consent.token, forceKill.value)
  operationBusy.value = false
  killDialog.value?.close()
  pendingKill.value = null
  if (!result.ok) showNotice(result.message ?? 'Nie udało się zakończyć procesu.')
  else {
    showNotice(`Proces PID ${result.pid} został zakończony.`)
    await snapshotQuery.refetch()
  }
}
function onBridgeReady() {
  bridgeReady.value = true
}
function keyboard(event: KeyboardEvent) {
  if (helpDialog.value?.open || killDialog.value?.open) return
  const editing =
    event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement
  if ((event.key === '/' && !editing) || ((event.metaKey || event.ctrlKey) && event.key === 'k')) {
    event.preventDefault()
    searchInput.value?.focus()
  }
  if (event.key === 'Escape') {
    if (editing) {
      search.value = ''
      searchInput.value?.blur()
    } else selectedId.value = null
  }
}
onMounted(() => {
  window.addEventListener('pywebviewready', onBridgeReady)
  window.addEventListener('keydown', keyboard)
  if (desktopBridge()) onBridgeReady()
  void applyCoreFilter()
})
onBeforeUnmount(() => {
  window.removeEventListener('pywebviewready', onBridgeReady)
  window.removeEventListener('keydown', keyboard)
  clearTimeout(filterTimer)
  clearTimeout(noticeTimer)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <AppIcon /><span
          >PortManager<span class="mt-1 block text-[10px] font-normal tracking-[0.16em] text-muted"
            >LOCAL WORKSPACE</span
          ></span
        >
      </div>
      <div class="machine">
        <Monitor :size="16" class="text-muted" />
        <div>
          <p class="text-xs font-medium">Ten komputer</p>
          <p class="mt-1 font-mono text-[10px] text-muted">localhost</p>
        </div>
        <span class="ml-auto h-1.5 w-1.5 rounded-full bg-accent" />
      </div>
      <nav class="mt-8" aria-label="Źródła portów">
        <p class="eyebrow mb-3 px-3">Przegląd</p>
        <button
          v-for="item in sourceItems"
          :key="item.id"
          class="nav-item"
          :class="{ active: source === item.id }"
          @click="source = item.id"
        >
          <component :is="item.icon" :size="16" /><span>{{ item.label }}</span
          ><span class="ml-auto font-mono text-[11px] opacity-60">{{ item.count }}</span>
        </button>
      </nav>
      <div class="mt-8 px-3">
        <p class="eyebrow mb-3">Adresy lokalne</p>
        <div v-if="localIps.length" class="space-y-2">
          <p
            v-for="ip in localIps"
            :key="`${ip.interface}-${ip.address}`"
            class="truncate font-mono text-[10px] text-muted"
            :title="`${ip.interface} · ${ip.address}`"
          >
            {{ ip.interface }} · {{ ip.address }}
          </p>
        </div>
        <p v-else class="text-[10px] text-muted">Brak dostępnych adresów</p>
      </div>
      <div class="mt-auto px-3 pb-5">
        <button
          class="flex items-center gap-2 text-xs text-muted hover:text-white"
          @click="helpDialog?.showModal()"
        >
          <CircleHelp :size="14" />O aplikacji<ChevronRight :size="12" />
        </button>
      </div>
    </aside>
    <div class="workspace">
      <header class="topbar">
        <div class="flex items-center gap-2 text-xs text-muted">
          <Monitor :size="14" /><span>Workspace</span><ChevronRight :size="12" /><span
            class="text-soft"
            >{{ sourceItems.find((s) => s.id === source)?.label }}</span
          >
        </div>
        <span class="preview-label"
          ><span class="h-1 w-1 rounded-full bg-accent" />{{ isPreview ? 'DEMO' : 'NA ŻYWO' }}</span
        >
      </header>
      <main class="main-content">
        <div class="page-heading">
          <div>
            <p class="eyebrow mb-3 text-accent">Sieć lokalna</p>
            <h1>
              Porty i procesy
              <span class="ml-2 font-mono text-base font-normal text-muted">{{
                ports.length.toString().padStart(2, '0')
              }}</span>
            </h1>
            <p class="mt-3 text-[13px] text-muted">
              Sprawdź, co zajmuje port i z czym jest powiązane.
            </p>
          </div>
          <div class="flex gap-2">
            <button
              class="secondary-button"
              data-testid="refresh"
              :disabled="snapshotQuery.isFetching.value"
              @click="snapshotQuery.refetch()"
            >
              <RefreshCw
                :size="14"
                :class="{ 'animate-spin': snapshotQuery.isFetching.value }"
              />Odśwież</button
            ><button
              class="secondary-button"
              data-testid="export"
              :disabled="operationBusy || isPreview"
              @click="exportVisible"
            >
              <ArrowDownToLine :size="14" />Eksportuj widok
            </button>
          </div>
        </div>
        <div v-if="isPreview" class="preview-note">
          <Activity :size="15" class="text-accent" />
          <p>
            <strong class="text-soft">Tryb przeglądarki.</strong> Dane demonstracyjne pozwalają
            ocenić interfejs; aplikacja desktopowa pokazuje system na żywo.
          </p>
        </div>
        <div v-else-if="snapshotQuery.isError.value" class="preview-note" role="alert">
          <CircleAlert :size="15" class="shrink-0 text-accent" />
          <p>
            <strong class="text-soft">Odświeżenie nie powiodło się.</strong> Pokazuję ostatnią
            poprawną migawkę i spróbuję ponownie.
          </p>
        </div>
        <div v-else-if="partialReports.length" class="preview-note" role="status">
          <CircleAlert :size="15" class="shrink-0 text-accent" />
          <div>
            <strong class="text-soft">Migawka jest częściowa.</strong>
            <p v-for="report in partialReports" :key="report.source" class="mt-1">
              <span class="font-mono">{{ report.source }}</span> ·
              {{ report.message || report.status }}
            </p>
          </div>
        </div>
        <div v-else class="h-7" />
        <div v-if="snapshotQuery.isError.value && !snapshot" class="error-state" role="alert">
          <CircleAlert :size="22" />
          <p>Nie udało się odczytać systemu.</p>
          <button class="secondary-button" @click="snapshotQuery.refetch()">
            Spróbuj ponownie
          </button>
        </div>
        <div v-else class="port-workspace" :class="{ 'has-inspector': selected }">
          <section class="port-list" aria-label="Lista portów">
            <div class="table-toolbar">
              <label class="search-field"
                ><Search :size="15" class="text-muted" /><input
                  ref="searchInput"
                  v-model="search"
                  data-testid="search"
                  aria-label="Szukaj portu, procesu lub PID"
                  placeholder="Szukaj, :PORT albo pid:PID…"
                  spellcheck="false"
                /><button
                  v-if="search"
                  class="icon-button"
                  aria-label="Wyczyść"
                  @click="search = ''"
                >
                  <X :size="13" /></button
                ><kbd v-else>/</kbd></label
              >
              <div class="protocol-tabs">
                <button
                  v-for="item in protocols"
                  :key="item.id"
                  :class="{ active: protocol === item.id }"
                  @click="protocol = item.id"
                >
                  {{ item.label }}
                </button>
              </div>
            </div>
            <p v-if="searchError" class="px-4 py-2 text-[11px] text-[#e6a9a9]" role="alert">
              {{ searchError }}
            </p>
            <div
              v-if="snapshotQuery.isPending.value && bridgeReady && !snapshot"
              class="empty-state"
            >
              <RefreshCw class="mb-4 animate-spin text-accent" />
              <p>Pobieram pierwszą migawkę…</p>
            </div>
            <div v-else-if="!ports.length" class="empty-state">
              <Server class="mb-4 text-muted" />
              <p>Nie znaleziono aktywnych portów.</p>
              <span class="mt-2 text-[11px] text-muted"
                >Źródła zostały odczytane, ale migawka jest pusta.</span
              >
            </div>
            <div v-else-if="!visible.length" class="empty-state">
              <Search class="mb-4 text-muted" />
              <p>Brak wyników dla tych filtrów.</p>
              <button class="secondary-button mt-4" @click="resetFilters">Wyczyść filtry</button>
            </div>
            <div v-else class="table-scroll">
              <table>
                <caption class="sr-only">
                  Porty i powiązane procesy
                </caption>
                <thead>
                  <tr v-for="group in table.getHeaderGroups()" :key="group.id">
                    <th v-for="header in group.headers" :key="header.id">
                      <button
                        v-if="header.column.getCanSort()"
                        @click="header.column.getToggleSortingHandler()?.($event)"
                      >
                        <FlexRender
                          :render="header.column.columnDef.header"
                          :props="header.getContext()"
                        /><ArrowUp
                          v-if="header.column.getIsSorted() === 'asc'"
                          :size="11"
                        /><ArrowDown
                          v-else-if="header.column.getIsSorted() === 'desc'"
                          :size="11"
                        /><ArrowUpDown v-else :size="11" /></button
                      ><FlexRender
                        v-else
                        :render="header.column.columnDef.header"
                        :props="header.getContext()"
                      />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in table.getRowModel().rows"
                    :key="row.id"
                    :data-port="row.original.port"
                    :class="{ selected: row.id === selectedId }"
                    @click="selectedId = row.id"
                  >
                    <td v-for="cell in row.getAllCells()" :key="cell.id">
                      <template v-if="cell.column.id === 'relations'"
                        ><span v-if="row.original.docker.length" class="connection"
                          ><Box :size="10" />{{ row.original.docker.length }}</span
                        ><span v-if="row.original.tunnels.length" class="connection tunnel"
                          ><Globe2 :size="10" />{{ row.original.tunnels.length }}</span
                        ><span v-if="row.original.tags.length" class="connection">{{
                          row.original.tags.map((t) => t.name).join(', ')
                        }}</span
                        ><span
                          v-if="
                            !row.original.docker.length &&
                            !row.original.tunnels.length &&
                            !row.original.tags.length
                          "
                          class="text-muted"
                          >—</span
                        ></template
                      ><button
                        v-else-if="cell.column.id === 'port'"
                        class="port-button"
                        @click.stop="selectedId = row.id"
                      >
                        <span class="font-mono text-sm">:{{ row.original.port }}</span></button
                      ><FlexRender
                        v-else
                        :render="cell.column.columnDef.cell"
                        :props="cell.getContext()"
                      />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="table-bottom">
              <span>{{ table.getRowModel().rows.length }} z {{ ports.length }} wpisów</span
              ><span v-if="snapshot"
                >Aktualizacja {{ new Date(snapshot.collected_at).toLocaleTimeString('pl-PL') }} · co
                2 s</span
              ><span v-else>Dane demonstracyjne</span>
            </div>
          </section>
          <Transition name="inspector"
            ><PortInspector
              v-if="selected"
              :port="selected"
              :desktop="!isPreview"
              :busy="operationBusy"
              @close="selectedId = null"
              @request-kill="requestKill(selected)"
            />
            <div v-else class="selection-hint">
              <PanelRight :size="15" />Wybierz port, aby zobaczyć szczegóły
            </div></Transition
          >
        </div>
      </main>
      <footer class="statusbar">
        <span
          >{{ appQuery.data.value?.name ?? 'PortManager' }} {{ appQuery.data.value?.version }}</span
        ><span>TCP / UDP · Docker · Compose · tunele</span>
      </footer>
    </div>
    <Transition name="toast"
      ><div v-if="notice" class="toast" role="status">
        <Check :size="15" class="text-accent" />{{ notice }}
      </div></Transition
    >
    <dialog ref="killDialog" class="help-dialog" @close="pendingKill = null">
      <template v-if="pendingKill"
        ><p class="eyebrow text-accent">Potwierdzenie operacji</p>
        <h2 class="mt-4 text-xl font-semibold">Zakończyć {{ pendingKill.target.name }}?</h2>
        <p class="mt-3 text-xs leading-6 text-muted">
          Zgoda dotyczy wyłącznie zweryfikowanego procesu PID {{ pendingKill.target.pid }}. Przed
          wysłaniem sygnału jego tożsamość zostanie sprawdzona ponownie.
        </p>
        <pre
          class="mt-5 max-h-32 overflow-auto whitespace-pre-wrap break-all border-l-2 border-line pl-3 font-mono text-xs leading-6 text-soft"
          >{{ pendingKill.target.cmdline.join(' ') }}</pre>
        <label class="mt-5 flex items-start gap-3 text-xs text-muted"
          ><input v-model="forceKill" data-testid="force" type="checkbox" class="mt-0.5" /><span
            >Jeśli łagodne zakończenie przekroczy 3 sekundy, zezwól na wymuszenie.</span
          ></label
        >
        <div class="mt-7 flex justify-end gap-2">
          <button
            class="secondary-button"
            data-testid="kill-cancel"
            :disabled="operationBusy"
            @click="killDialog?.close()"
          >
            Anuluj</button
          ><button
            class="primary-button"
            data-testid="kill-confirm"
            :disabled="operationBusy"
            @click="confirmKill"
          >
            {{ operationBusy ? 'Kończenie…' : 'Zakończ proces' }}
          </button>
        </div></template
      >
    </dialog>
    <dialog ref="helpDialog" class="help-dialog">
      <p class="eyebrow text-accent">PortManager GUI</p>
      <h2 class="mt-4 text-xl font-semibold">Lokalny obraz portów</h2>
      <p class="mt-4 text-sm leading-7 text-muted">
        Migawka łączy gniazda TCP i UDP z procesami, publikacjami Docker Compose, tunelami oraz
        tagami usług. Aplikacja nie pobiera automatycznie publicznego adresu IP i nie podnosi
        uprawnień.
      </p>
      <div class="mt-7 flex justify-end">
        <button class="secondary-button" @click="helpDialog?.close()">Zamknij</button>
      </div>
    </dialog>
  </div>
</template>
