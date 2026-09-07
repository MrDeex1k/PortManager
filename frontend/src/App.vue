<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
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
  ArrowRight,
  ArrowUp,
  ArrowUpDown,
  Box,
  Check,
  ChevronRight,
  CircleHelp,
  Command,
  Globe2,
  Layers,
  Monitor,
  PanelRight,
  Search,
  SlidersHorizontal,
  Terminal,
  X,
} from 'lucide-vue-next'
import { getAppInfo } from './desktop'
import { filterPreview, previewPorts } from './preview'
import type { PreviewPort, ProtocolFilter, SourceFilter } from './preview'
import PortInspector from './components/PortInspector.vue'
import AppIcon from './components/AppIcon.vue'

const source = ref<SourceFilter>('all')
const protocol = ref<ProtocolFilter>('all')
const search = ref('')
const selectedId = ref<string | null>('web')
const searchInput = ref<HTMLInputElement | null>(null)
const helpDialog = ref<HTMLDialogElement | null>(null)
const notice = ref('')
let noticeTimer: ReturnType<typeof setTimeout> | undefined
const bridgeReady = ref(Boolean(window.pywebview?.api))
const appQuery = useQuery({ queryKey: ['desktop-info', bridgeReady], queryFn: getAppInfo })
const data = computed(() => filterPreview(previewPorts, search.value, source.value, protocol.value))
const features = tableFeatures({ rowSortingFeature, sortedRowModel: createSortedRowModel() })
const helper = createColumnHelper<typeof features, PreviewPort>()
const columns = helper.columns([
  helper.accessor('port', { header: 'Port', sortFn: sortFn_basic, sortDescFirst: false }),
  helper.accessor('process', { header: 'Proces', sortFn: sortFn_text }),
  helper.accessor('bind', { header: 'Bind', sortFn: sortFn_text }),
  helper.accessor('pid', {
    header: 'PID',
    sortFn: sortFn_basic,
    cell: (info) => info.getValue() ?? '—',
  }),
  helper.display({ id: 'connections', header: 'Powiązania' }),
])
const table = useTable({
  features,
  columns,
  data,
  getRowId: (row: PreviewPort) => row.id,
  initialState: { sorting: [{ id: 'port', desc: false }] },
})
const selected = computed(() => data.value.find((row) => row.id === selectedId.value))
const filtersActive = computed(() =>
  Boolean(search.value || protocol.value !== 'all' || source.value !== 'all'),
)
const sourceItems = [
  { id: 'all' as const, label: 'Wszystkie porty', icon: Layers, count: previewPorts.length },
  {
    id: 'docker' as const,
    label: 'Docker',
    icon: Box,
    count: previewPorts.filter((p) => p.container).length,
  },
  {
    id: 'tunnels' as const,
    label: 'Tunele',
    icon: Globe2,
    count: previewPorts.filter((p) => p.tunnel).length,
  },
]
const protocols: { id: ProtocolFilter; label: string }[] = [
  { id: 'all', label: 'Wszystkie' },
  { id: 'TCP', label: 'TCP' },
  { id: 'UDP', label: 'UDP' },
]
watch(data, (rows) => {
  if (!rows.some((row) => row.id === selectedId.value)) selectedId.value = null
})

function resetFilters() {
  search.value = ''
  source.value = 'all'
  protocol.value = 'all'
}
function showNotice(message: string) {
  clearTimeout(noticeTimer)
  notice.value = message
  noticeTimer = setTimeout(() => {
    notice.value = ''
  }, 3000)
}
function exportPreview() {
  const payload = {
    kind: 'portmanager-ui-preview',
    description: 'Dane przykładowe, nie odczyt systemu. Format prototypu; nie kontrakt JSON core.',
    ports: table.getRowModel().rows.map((r) => r.original),
  }
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }),
  )
  const link = document.createElement('a')
  link.href = url
  link.download = 'portmanager-preview.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  showNotice('Przekazano przykładowy JSON do pobrania.')
}
function onBridgeReady() {
  bridgeReady.value = true
}
function keyboard(event: KeyboardEvent) {
  if (helpDialog.value?.open) return
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
  if (window.pywebview?.api) onBridgeReady()
})
onBeforeUnmount(() => {
  window.removeEventListener('pywebviewready', onBridgeReady)
  window.removeEventListener('keydown', keyboard)
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
          :aria-current="source === item.id ? 'page' : undefined"
          @click="source = item.id"
        >
          <component :is="item.icon" :size="16" /><span>{{ item.label }}</span
          ><span class="ml-auto font-mono text-[11px] opacity-60">{{ item.count }}</span>
        </button>
      </nav>
      <div class="mt-9 px-3">
        <p class="eyebrow mb-4">Środowisko przykładowe</p>
        <div class="space-y-4 text-xs text-muted">
          <p class="flex items-center gap-2.5">
            <span class="h-1 w-1 rounded-full bg-muted" />Gniazda TCP / UDP
          </p>
          <p class="flex items-center gap-2.5">
            <span class="h-1 w-1 rounded-full bg-muted" />Docker Compose
          </p>
          <p class="flex items-center gap-2.5">
            <span class="h-1 w-1 rounded-full bg-muted" />Cloudflare Tunnel
          </p>
        </div>
      </div>
      <div class="mt-auto px-3 pb-5 pt-12">
        <div class="mb-5 border-t border-line pt-5">
          <p class="flex items-center gap-2 text-xs text-soft">
            <Terminal :size="14" />Jeden komputer. Pełny kontekst.
          </p>
          <p class="mt-2 text-[11px] leading-relaxed text-muted">
            Porty, procesy i usługi<br />w jednym miejscu.
          </p>
        </div>
        <button
          class="flex items-center gap-2 text-xs text-muted transition-colors hover:text-white"
          @click="helpDialog?.showModal()"
        >
          <CircleHelp :size="14" />O tym podglądzie<ChevronRight :size="12" />
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
        <span class="preview-label"><span class="h-1 w-1 rounded-full bg-accent" />PODGLĄD</span>
      </header>
      <main class="main-content">
        <div class="page-heading">
          <div>
            <p class="eyebrow mb-3 text-accent">Sieć lokalna</p>
            <h1>
              Porty i procesy<span
                class="ml-3 align-middle font-mono text-base font-normal text-muted"
                >{{ previewPorts.length.toString().padStart(2, '0') }}</span
              >
            </h1>
            <p class="mt-3 text-[13px] text-muted">
              Sprawdź, co zajmuje port. Zobacz, z czym jest powiązane.
            </p>
          </div>
          <button
            class="secondary-button export-button disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="bridgeReady"
            :title="
              bridgeReady
                ? 'Eksport przykładu jest dostępny w przeglądarce. Zapis desktopowy powstanie w kolejnym etapie.'
                : undefined
            "
            @click="exportPreview"
          >
            <ArrowDownToLine :size="14" />Eksport przykładu
          </button>
        </div>

        <div class="preview-note">
          <Activity :size="15" class="shrink-0 text-accent" />
          <p>
            <strong class="font-medium text-soft">Przykładowa migawka.</strong> Możesz filtrować,
            sortować i otwierać szczegóły. Odczyt komputera nie jest podłączony.
          </p>
        </div>
        <div
          v-if="appQuery.isError.value"
          class="my-3 flex items-center justify-between text-xs text-soft"
          role="alert"
        >
          <span>Nie udało się połączyć z oknem desktopowym.</span
          ><button class="secondary-button" @click="appQuery.refetch()">Ponów połączenie</button>
        </div>

        <div class="port-workspace" :class="{ 'has-inspector': selected }">
          <section class="port-list" aria-label="Lista portów">
            <div class="table-toolbar">
              <label class="search-field"
                ><Search :size="15" class="shrink-0 text-muted" /><input
                  ref="searchInput"
                  v-model="search"
                  aria-label="Szukaj portu, procesu lub PID"
                  placeholder="Szukaj portu, procesu, PID…"
                  spellcheck="false"
                /><button
                  v-if="search"
                  class="icon-button"
                  aria-label="Wyczyść wyszukiwanie"
                  @click="search = ''"
                >
                  <X :size="13" /></button
                ><kbd v-else>/</kbd></label
              >
              <div class="protocol-tabs" aria-label="Protokół">
                <button
                  v-for="item in protocols"
                  :key="item.id"
                  :class="{ active: protocol === item.id }"
                  :aria-pressed="protocol === item.id"
                  @click="protocol = item.id"
                >
                  {{ item.label }}
                </button>
              </div>
            </div>
            <div class="table-scroll">
              <table>
                <caption class="sr-only">
                  Przykładowe porty. Kliknij numer portu, aby zobaczyć szczegóły. Nagłówki sortują
                  kolumny.
                </caption>
                <thead>
                  <tr v-for="group in table.getHeaderGroups()" :key="group.id">
                    <th
                      v-for="header in group.headers"
                      :key="header.id"
                      :aria-sort="
                        header.column.getIsSorted() === 'asc'
                          ? 'ascending'
                          : header.column.getIsSorted() === 'desc'
                            ? 'descending'
                            : undefined
                      "
                    >
                      <button
                        v-if="header.column.getCanSort()"
                        @click="header.column.getToggleSortingHandler()?.($event)"
                      >
                        <FlexRender :header="header" /><ArrowUp
                          v-if="header.column.getIsSorted() === 'asc'"
                          :size="11"
                          class="text-accent"
                        /><ArrowDown
                          v-else-if="header.column.getIsSorted() === 'desc'"
                          :size="11"
                          class="text-accent"
                        /><ArrowUpDown v-else :size="10" class="opacity-40" /></button
                      ><FlexRender v-else :header="header" />
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="row in table.getRowModel().rows"
                    :key="row.id"
                    :class="{ selected: selectedId === row.id }"
                    @click="selectedId = row.id"
                  >
                    <td v-for="cell in row.getAllCells()" :key="cell.id" :class="cell.column.id">
                      <button
                        v-if="cell.column.id === 'port'"
                        class="port-button"
                        :aria-label="`Pokaż szczegóły portu ${row.original.port}`"
                        :aria-pressed="selectedId === row.id"
                        @click.stop="selectedId = row.id"
                      >
                        <span class="font-mono text-sm font-medium">{{ row.original.port }}</span
                        ><span class="mt-1 font-mono text-[9px] tracking-wider text-muted">{{
                          row.original.protocol
                        }}</span>
                      </button>
                      <template v-else-if="cell.column.id === 'process'"
                        ><span class="block font-mono text-xs text-soft">{{
                          row.original.process
                        }}</span
                        ><span class="mt-1.5 block text-[10px] text-muted">{{
                          row.original.service
                        }}</span></template
                      >
                      <template v-else-if="cell.column.id === 'connections'"
                        ><div class="flex items-center gap-1.5">
                          <span
                            v-if="row.original.container"
                            class="connection"
                            title="Mapowanie kontenera"
                            ><Box :size="12" />Docker</span
                          ><span
                            v-if="row.original.tunnel"
                            class="connection tunnel"
                            title="Reguła tunelu"
                            ><Globe2 :size="12" />Tunel</span
                          ><span
                            v-if="!row.original.container && !row.original.tunnel"
                            class="text-muted"
                            >—</span
                          >
                        </div></template
                      >
                      <span v-else class="font-mono text-[11px] text-muted"
                        ><FlexRender :cell="cell"
                      /></span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-if="!data.length" class="empty-state">
                <Search :size="26" :stroke-width="1.2" class="mb-4 text-muted" />
                <h2 class="text-sm font-medium">Brak pasujących portów</h2>
                <p class="mt-2 max-w-64 text-center text-xs leading-relaxed text-muted">
                  Zmień wyszukiwanie lub wyczyść filtry, aby wrócić do przykładowej migawki.
                </p>
                <button class="secondary-button mt-5" @click="resetFilters">
                  Wyczyść filtry<ArrowRight :size="13" />
                </button>
              </div>
            </div>
            <div class="table-bottom">
              <span>{{ data.length }} z {{ previewPorts.length }} wpisów</span
              ><button
                v-if="filtersActive"
                class="text-accent hover:underline"
                @click="resetFilters"
              >
                Wyczyść filtry</button
              ><span v-else class="flex items-center gap-1.5"
                ><SlidersHorizontal :size="11" />Kliknij nagłówek, by sortować</span
              >
            </div>
            <div v-if="!selected && data.length" class="selection-hint">
              <PanelRight :size="18" :stroke-width="1.4" /><span
                >Wybierz port, aby zobaczyć proces i powiązania.</span
              >
            </div>
          </section>
          <Transition name="inspector"
            ><PortInspector v-if="selected" :port="selected" @close="selectedId = null"
          /></Transition>
        </div>
        <div class="workspace-note">
          <span class="flex items-center gap-2"
            ><span class="h-1 w-1 rounded-full bg-muted" />TCP: LISTEN<span class="mx-1 opacity-30"
              >/</span
            >UDP: bez weryfikacji handshake</span
          ><span class="flex items-center gap-1.5"
            ><Command :size="11" />K<span class="ml-1">wyszukiwanie</span></span
          >
        </div>
      </main>
      <footer class="statusbar">
        <span class="flex items-center gap-2"
          ><span class="status-dot" />Tryb podglądu<span class="ml-2 hidden text-muted sm:inline"
            >Bez odczytu systemu</span
          ></span
        ><span
          >{{
            appQuery.data.value?.mode === 'desktop' ? 'Okno desktopowe' : 'Podgląd w przeglądarce'
          }}<span class="mx-3 opacity-30">/</span
          ><span class="font-mono">v{{ appQuery.data.value?.version ?? '0.1.0' }}</span></span
        >
      </footer>
    </div>
    <Transition name="toast"
      ><div v-if="notice" class="toast" role="status">
        <Check :size="15" class="text-accent" />{{ notice }}
      </div></Transition
    >
    <dialog
      ref="helpDialog"
      class="help-dialog"
      aria-labelledby="about-title"
      @click="
        (event) => {
          if (event.target === helpDialog) helpDialog?.close()
        }
      "
    >
      <div class="flex items-center justify-between">
        <AppIcon /><button
          class="icon-button"
          aria-label="Zamknij podgląd informacji"
          @click="helpDialog?.close()"
        >
          <X :size="18" />
        </button>
      </div>
      <h2 id="about-title" class="mt-5 text-2xl font-semibold tracking-tight">PortManager</h2>
      <p class="mt-2 text-sm text-muted">Prototyp interfejsu desktopowego</p>
      <p class="mt-6 text-sm leading-7 text-soft">
        Wszystkie porty, PID-y, polecenia i powiązania w tym widoku są przykładowe. Wyszukiwanie,
        sortowanie oraz panel szczegółów pozwalają sprawdzić sposób pracy z aplikacją.
      </p>
      <p class="mt-4 text-sm leading-7 text-muted">
        Podłączenie danych komputera i bezpieczne operacje na procesach to kolejne etapy. Eksport
        zawiera wyłącznie przykład, w formacie prototypu.
      </p>
      <button class="primary-button mt-7 w-full justify-center" @click="helpDialog?.close()">
        Wróć do portów<ArrowRight :size="15" />
      </button>
    </dialog>
  </div>
</template>
