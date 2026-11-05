import { plugin } from 'bun'
import { compileScript, parse } from 'vue/compiler-sfc'
import { createRenderer } from 'vue'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import type { SetupContext } from 'vue'

// Compile the real SFC setup and mount its lifecycle with Vue. No browser or
// native bridge is needed; queries and reactivity use the production libraries.
plugin({
  name: 'vue-component-tests',
  setup(build) {
    build.onLoad({ filter: /\.vue$/ }, async ({ path }) => {
      const source = await Bun.file(path).text()
      const { descriptor, errors } = parse(source, { filename: path })
      if (errors.length) throw new AggregateError(errors, `Invalid Vue component: ${path}`)
      return { contents: compileScript(descriptor, { id: path }).content, loader: 'ts' }
    })
  },
})

// SFC setup bindings are deliberately not public production exports. Reflection
// stays in this helper so tests can exercise the compiled component unchanged.
export type Bindings = Record<string, any>
type ScriptComponent = {
  setup: (props: Record<string, unknown>, context: SetupContext) => Bindings
}
const renderer = createRenderer({
  patchProp() {},
  insert() {},
  remove() {},
  createElement: () => ({}),
  createText: () => ({}),
  createComment: () => ({}),
  setText() {},
  setElementText() {},
  parentNode: () => null,
  nextSibling: () => null,
})

export function mountScript(component: unknown, props: Record<string, unknown> = {}) {
  const script = component as ScriptComponent
  let state!: Bindings
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: Infinity, gcTime: 0 },
    },
  })
  const app = renderer.createApp(
    {
      ...script,
      setup(p, context) {
        state = script.setup(p, context)
        return () => null
      },
    },
    props,
  )
  app.use(VueQueryPlugin, { queryClient: client })
  app.mount({})
  let mounted = true
  return {
    state,
    unmount() {
      if (!mounted) return
      mounted = false
      app.unmount()
      client.clear()
    },
  }
}

export function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

export const settle = (ms = 0) => new Promise<void>((resolve) => setTimeout(resolve, ms))
