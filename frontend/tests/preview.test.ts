import { describe, expect, test } from 'bun:test'
import { filterPreview, previewPorts } from '../src/preview'

describe('interakcje przykładowej migawki', () => {
  test('numer portu jest dokładny, a PID nie pasuje do brakującego właściciela', () => {
    expect(filterPreview(previewPorts, ':3000', 'all', 'all').map((p) => p.id)).toEqual(['web'])
    expect(filterPreview(previewPorts, ':300', 'all', 'all')).toEqual([])
    expect(filterPreview(previewPorts, 'pid:0', 'all', 'all')).toEqual([])
    expect(filterPreview(previewPorts, 'pid:8421', 'all', 'all').map((p) => p.id)).toEqual(['web'])
  })
  test('łączy wyszukiwanie, źródło i protokół', () => {
    expect(filterPreview(previewPorts, 'WORKSPACE', 'docker', 'TCP')).toHaveLength(3)
    expect(filterPreview(previewPorts, '', 'docker', 'UDP')).toHaveLength(0)
    expect(filterPreview(previewPorts, 'example.com', 'tunnels', 'TCP')).toHaveLength(2)
  })
  test('błędny filtr i puste wyniki nie zmieniają fixture', () => {
    const original = JSON.stringify(previewPorts)
    expect(filterPreview(previewPorts, ':oops', 'all', 'all')).toEqual([])
    expect(filterPreview(previewPorts, 'pid:', 'all', 'all')).toEqual([])
    expect(filterPreview(previewPorts, '', 'all', 'all')).toHaveLength(8)
    expect(JSON.stringify(previewPorts)).toBe(original)
  })
})
