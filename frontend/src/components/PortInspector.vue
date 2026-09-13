<script setup lang="ts">
import { ArrowRight, Box, Copy, Globe2, LockKeyhole, OctagonX, Terminal, X } from 'lucide-vue-next'
import { onBeforeUnmount, ref, watch } from 'vue'
import type { PortRow } from '../types'

const props = defineProps<{ port: PortRow; desktop: boolean; busy: boolean }>()
defineEmits<{ close: []; requestKill: [] }>()
const copyStatus = ref('')
let resetTimer: ReturnType<typeof setTimeout> | undefined
watch(
  () => props.port.id,
  () => {
    copyStatus.value = ''
    clearTimeout(resetTimer)
  },
)
onBeforeUnmount(() => clearTimeout(resetTimer))
async function copyAddress() {
  try {
    await navigator.clipboard.writeText(`${props.port.bind}:${props.port.port}`)
    copyStatus.value = 'Skopiowano adres'
  } catch {
    copyStatus.value = 'Nie można skopiować adresu'
  }
  resetTimer = setTimeout(() => {
    copyStatus.value = ''
  }, 2400)
}
</script>

<template>
  <aside class="inspector" aria-label="Szczegóły portu">
    <div class="flex items-center justify-between border-b border-line px-6 py-5">
      <span class="eyebrow">Szczegóły portu</span
      ><button class="icon-button" aria-label="Zamknij szczegóły" @click="$emit('close')">
        <X :size="16" />
      </button>
    </div>
    <div :key="port.id" class="inspector-content p-6">
      <div class="flex items-center gap-2 text-xs text-muted">
        <span class="status-dot" />{{ desktop ? 'Bieżąca migawka' : 'Dane demonstracyjne'
        }}<span class="ml-auto font-mono uppercase">{{ port.proto }}</span>
      </div>
      <div class="mt-5 flex items-baseline gap-2">
        <span class="font-mono text-3xl text-muted">:</span>
        <h2 class="font-mono text-[48px] leading-none tracking-[-3px]">{{ port.port }}</h2>
      </div>
      <p class="mt-3 text-sm text-muted">
        {{ port.process?.name ?? port.docker[0]?.container_name ?? 'Nieznana usługa' }}
      </p>
      <dl class="mt-8 grid grid-cols-[1fr_auto] gap-y-4 text-xs">
        <dt class="text-muted">Adres bind</dt>
        <dd class="font-mono">{{ port.bind }}</dd>
        <dt class="text-muted">Protokół</dt>
        <dd class="uppercase">{{ port.proto }}</dd>
        <dt class="text-muted">Źródło wpisu</dt>
        <dd>{{ port.origin === 'docker' ? 'Publikacja Docker' : 'Gniazdo lokalne' }}</dd>
        <dt class="text-muted">PID hosta</dt>
        <dd class="font-mono">{{ port.pid ?? '—' }}</dd>
      </dl>
      <button class="secondary-button mt-5 w-full justify-center" @click="copyAddress">
        <Copy :size="13" />Kopiuj adres
      </button>
      <p class="mt-2 min-h-4 text-center text-[11px] text-accent" role="status">{{ copyStatus }}</p>

      <section class="inspector-section">
        <h3 class="eyebrow flex items-center gap-2"><Terminal :size="13" />Proces</h3>
        <div class="mt-4 flex items-center justify-between">
          <span class="font-mono text-sm">{{ port.process?.name ?? 'Brak danych' }}</span
          ><span class="font-mono text-xs text-muted">{{ port.process?.status ?? 'unknown' }}</span>
        </div>
        <p class="mt-4 text-[10px] uppercase tracking-widest text-muted">Argumenty</p>
        <pre
          class="mt-2 whitespace-pre-wrap break-all border-l-2 border-line pl-3 font-mono text-xs leading-6 text-soft"
          >{{ port.process?.cmdline?.join(' ') || 'Niedostępne' }}</pre>
        <button
          v-if="desktop && port.pid !== null"
          class="danger-button mt-5 w-full justify-center"
          data-testid="kill-open"
          :disabled="busy"
          @click="$emit('requestKill')"
        >
          <OctagonX :size="13" />Zakończ proces…
        </button>
        <p v-else-if="port.origin === 'docker'" class="mt-4 text-xs leading-relaxed text-muted">
          Brak PID hosta. Kontener zatrzymaj świadomie poleceniem
          <span class="font-mono">docker stop</span>.
        </p>
      </section>

      <section v-if="port.docker.length" class="inspector-section">
        <h3 class="eyebrow flex items-center gap-2"><Box :size="13" />Docker / Compose</h3>
        <div
          v-for="item in port.docker"
          :key="`${item.container_id}-${item.container_port}`"
          class="mt-4 border-l border-line pl-3"
        >
          <p class="text-sm">{{ item.container_name }}</p>
          <p class="mt-1 text-xs text-muted">
            {{ item.compose_project || 'bez projektu' }} /
            {{ item.compose_service || 'bez usługi' }}
          </p>
          <div class="mt-3 flex items-center gap-2 font-mono text-xs">
            <span>{{ item.host_bind }}:{{ item.host_port }}</span
            ><ArrowRight :size="12" class="text-accent" /><span
              >{{ item.container_port }}/{{ item.proto }}</span
            >
          </div>
        </div>
        <p class="mt-4 text-[11px] leading-relaxed text-muted">
          Publikacja portu nie potwierdza aktywnego gniazda wewnątrz kontenera.
        </p>
      </section>
      <section v-if="port.tunnels.length" class="inspector-section">
        <h3 class="eyebrow flex items-center gap-2"><Globe2 :size="13" />Tunele</h3>
        <div
          v-for="route in port.tunnels"
          :key="`${route.pid}-${route.hostname}-${route.path}`"
          class="mt-4"
        >
          <p class="break-all font-mono text-xs text-accent">
            {{ route.hostname || '(bez hostname)' }}{{ route.path || '' }}
          </p>
          <p class="mt-1 font-mono text-[11px] text-muted">
            {{ route.host }}:{{ route.port }} · PID {{ route.pid }}
          </p>
        </div>
        <p class="mt-4 text-[11px] leading-relaxed text-muted">
          Reguła konfiguracji nie potwierdza publicznej dostępności adresu.
        </p>
      </section>
      <section v-if="port.tags.length" class="inspector-section">
        <h3 class="eyebrow">Tagi usług</h3>
        <p class="mt-3 text-xs text-muted">
          <span v-for="tag in port.tags" :key="tag.name" class="connection mr-2"
            >{{ tag.name }} · {{ tag.evidence }}</span
          >
        </p>
      </section>
      <div
        class="mt-7 flex gap-2.5 border-t border-line pt-5 text-[11px] leading-relaxed text-muted"
      >
        <LockKeyhole :size="14" class="mt-0.5 shrink-0" />
        <p>
          Dane procesu mogą być częściowe z powodu uprawnień lub zakończenia procesu między
          odczytami.
        </p>
      </div>
    </div>
  </aside>
</template>
