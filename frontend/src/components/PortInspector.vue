<script setup lang="ts">
import { ArrowRight, Box, Copy, Globe2, LockKeyhole, Terminal, X } from 'lucide-vue-next'
import { ref, watch, onBeforeUnmount } from 'vue'
import type { PreviewPort } from '../preview'

const props = defineProps<{ port: PreviewPort }>()
defineEmits<{ close: [] }>()
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
      <span class="eyebrow">Szczegóły portu</span>
      <button class="icon-button" aria-label="Zamknij szczegóły" @click="$emit('close')">
        <X :size="16" />
      </button>
    </div>
    <div :key="port.id" class="inspector-content p-6">
      <div class="flex items-center gap-2 text-xs text-muted">
        <span class="status-dot" />Dane przykładowe<span class="ml-auto font-mono">{{
          port.protocol
        }}</span>
      </div>
      <div class="mt-5 flex items-baseline gap-2">
        <span class="font-mono text-3xl text-muted">:</span>
        <h2 class="font-mono text-[48px] leading-none tracking-[-3px]">{{ port.port }}</h2>
      </div>
      <p class="mt-3 text-sm text-muted">{{ port.service }}</p>

      <dl class="mt-8 grid grid-cols-[1fr_auto] gap-y-4 text-xs">
        <dt class="text-muted">Adres bind</dt>
        <dd class="font-mono">{{ port.bind }}</dd>
        <dt class="text-muted">Protokół</dt>
        <dd>{{ port.protocol === 'TCP' ? 'TCP · LISTEN' : 'UDP · związane gniazdo' }}</dd>
        <dt class="text-muted">Źródło wpisu</dt>
        <dd>{{ port.container ? 'Publikacja Docker' : 'Gniazdo lokalne' }}</dd>
      </dl>
      <button class="secondary-button mt-5 w-full justify-center" @click="copyAddress">
        <Copy :size="13" />Kopiuj adres
      </button>
      <p class="mt-2 min-h-4 text-center text-[11px] text-accent" role="status">{{ copyStatus }}</p>

      <section class="inspector-section">
        <h3 class="eyebrow flex items-center gap-2"><Terminal :size="13" />Proces</h3>
        <div class="mt-4 flex items-center justify-between">
          <span class="font-mono text-sm">{{ port.process }}</span
          ><span class="font-mono text-xs text-muted">{{
            port.pid === null ? 'PID hosta —' : `PID ${port.pid}`
          }}</span>
        </div>
        <p v-if="port.container" class="mt-2 text-xs leading-relaxed text-muted">
          Przykładowy proces w kontenerze. Publikacja nie potwierdza gniazda hosta.
        </p>
        <p class="mt-4 text-[10px] uppercase tracking-widest text-muted">Polecenie przykładowe</p>
        <pre
          class="mt-2 whitespace-pre-wrap break-all border-l-2 border-line pl-3 font-mono text-xs leading-6 text-soft"
          >{{ port.command }}</pre>
      </section>

      <section v-if="port.container" class="inspector-section">
        <h3 class="eyebrow flex items-center gap-2"><Box :size="13" />Kontener Docker</h3>
        <p class="mt-4 text-sm">{{ port.container.name }}</p>
        <p class="mt-2 text-xs text-muted">Compose / {{ port.container.project }}</p>
        <div class="mt-4 flex items-center gap-3 font-mono text-sm">
          <span>{{ port.port }}</span
          ><ArrowRight :size="14" class="text-accent" /><span>{{ port.container.port }}</span
          ><span class="text-xs text-muted">host → kontener</span>
        </div>
      </section>
      <section v-if="port.tunnel" class="inspector-section">
        <h3 class="eyebrow flex items-center gap-2"><Globe2 :size="13" />Cloudflare Tunnel</h3>
        <p class="mt-4 break-all font-mono text-xs text-accent">{{ port.tunnel }}</p>
        <p class="mt-2 text-xs leading-relaxed text-muted">
          Przykładowa reguła. Nie potwierdza dostępności z internetu.
        </p>
      </section>
      <div
        class="mt-7 flex gap-2.5 border-t border-line pt-5 text-[11px] leading-relaxed text-muted"
      >
        <LockKeyhole :size="14" class="mt-0.5 shrink-0" />
        <p>Tryb podglądu. Żaden proces ani usługa na komputerze nie są modyfikowane.</p>
      </div>
    </div>
  </aside>
</template>
