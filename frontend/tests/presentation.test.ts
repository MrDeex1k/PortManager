import { expect, test } from 'bun:test'
import { dockerKey, formatArguments } from '../src/presentation'
import { previewPorts } from '../src/preview'

test('argument presentation distinguishes unavailable, empty and token boundaries', () => {
  expect(formatArguments(null)).toBe('Niedostępne')
  expect(formatArguments([])).toBe('Brak argumentów')
  expect(formatArguments(['a b', 'c'])).not.toBe(formatArguments(['a', 'b c']))
  expect(JSON.parse(formatArguments(['\n', '"', 'a b']))).toEqual(['\n', '"', 'a b'])
})

test('Docker mapping identity includes bind, both ports and protocol', () => {
  const item = previewPorts.find((row) => row.docker.length)!.docker[0]!
  const mappings = [
    item,
    { ...item, host_bind: '::' },
    { ...item, host_port: 9999 },
    { ...item, container_port: 9999 },
    { ...item, proto: 'udp' as const },
    { ...item, container_id: 'other' },
  ]
  expect(new Set(mappings.map(dockerKey)).size).toBe(mappings.length)
})
