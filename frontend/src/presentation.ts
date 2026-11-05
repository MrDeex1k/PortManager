import type { DockerPort } from './types'

export function formatArguments(args: readonly string[] | null | undefined): string {
  if (args == null) return 'Niedostępne'
  return args.length ? JSON.stringify(args) : 'Brak argumentów'
}

export function dockerKey(item: DockerPort): string {
  return JSON.stringify([
    item.container_id,
    item.host_bind,
    item.host_port,
    item.container_port,
    item.proto,
  ])
}
