import type { ApplicationVersion, DockerPort, PortRow } from './types'

export function formatEndpoint(bind: string, port: number): string {
  const host = bind.includes(':') && !bind.startsWith('[') ? `[${bind}]` : bind
  return `${host}:${port}`
}

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

export function versionSource(source: ApplicationVersion['source']): string {
  return {
    package_json: 'package.json',
    macos_bundle: 'Info.plist (macOS)',
    oci_label: 'Etykieta OCI',
  }[source]
}

export function versionSummary(row: PortRow): string {
  const values: string[] = []
  if (row.process?.application_version) values.push(row.process.application_version.version)
  for (const item of row.docker) {
    if (item.application_version)
      values.push(`${item.container_name}: ${item.application_version.version}`)
  }
  return [...new Set(values)].join('; ') || '—'
}
