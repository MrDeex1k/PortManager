import { describe, expect, test } from 'bun:test'
import { filterPreview, previewPorts } from '../src/preview'

describe('fallback przeglądarkowy', () => {
  test('dokładnie filtruje port i PID', () => {
    expect(filterPreview(previewPorts, ':3000')).toEqual(['web'])
    expect(filterPreview(previewPorts, ':300')).toEqual([])
    expect(filterPreview(previewPorts, 'pid:8421')).toEqual(['web'])
    expect(filterPreview(previewPorts, 'pid:0')).toEqual([])
  })
  test('wyszukuje po danych procesu, kontenera i tunelu', () => {
    expect(filterPreview(previewPorts, 'WORKSPACE')).toEqual(['postgres', 'redis'])
    expect(filterPreview(previewPorts, 'example.com')).toEqual(['web'])
    expect(filterPreview(previewPorts, 'uvicorn')).toEqual(['api'])
  })
  test('nie mutuje danych wejściowych', () => {
    const original = JSON.stringify(previewPorts)
    expect(filterPreview(previewPorts, ':oops')).toEqual([])
    expect(filterPreview(previewPorts, '')).toHaveLength(previewPorts.length)
    expect(JSON.stringify(previewPorts)).toBe(original)
  })
})
