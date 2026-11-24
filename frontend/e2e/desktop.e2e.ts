import { expect, test } from './test'
import { previewPorts } from '../src/preview'
import { installDesktop } from './desktop-fixture'

const desktopRow = { ...previewPorts[0]!, id: 'desktop', bind: '::1', port: 9999 }

test('przechodzi z demo do migawki desktopowej i odzyskuje filtrowanie po błędzie', async ({
  page,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: ':3000', exact: true }).click()
  const inspector = page.getByRole('complementary', { name: 'Szczegóły portu' })
  await expect(inspector).toBeVisible()

  await page.evaluate(installDesktop, { ports: [desktopRow], delayed: true })
  await expect(page.getByText('Pobieram pierwszą migawkę…')).toBeVisible()
  await expect(page.getByRole('button', { name: ':3000', exact: true })).toHaveCount(0)
  await expect(inspector).toBeHidden()
  await expect(page.getByTestId('export')).toBeDisabled()
  await page.evaluate(() => window.testDesktop.releaseSnapshot())
  await page.getByTestId('refresh').click()
  await expect(page.getByRole('button', { name: ':9999', exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.testDesktop.refreshes)).toBeGreaterThan(0)

  const search = page.getByTestId('search')
  await search.fill('offline')
  await expect(page.getByRole('alert')).toContainText('Utracono połączenie')
  await search.fill('8000')
  await expect(page.getByText('Brak wyników dla tych filtrów.')).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await page.getByRole('button', { name: 'Wyczyść filtry' }).click()
  await expect(page.getByRole('button', { name: ':9999', exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Kubernetes', exact: true }).click()
  const kube = page.getByRole('switch', { name: 'Odczyt Kubernetes' })
  await expect(kube).not.toBeChecked()
  await kube.click()
  await expect(kube).toBeChecked()
  await expect(kube).toBeEnabled()
  await kube.click()
  await expect(kube).not.toBeChecked()
})

test('eksportuje posortowane wyniki filtra ze wszystkich stron', async ({ page }) => {
  const rows = Array.from({ length: 105 }, (_, index) => ({
    ...desktopRow,
    id: `row-${index}`,
    port: 10000 + index,
  }))
  await page.addInitScript(installDesktop, { ports: [desktopRow, ...rows] })
  await page.goto('/')
  await page.getByTestId('search').fill('10')
  await expect(page.getByText('105 z 106 wpisów')).toBeVisible()
  await page.getByRole('button', { name: 'Port', exact: true }).click()
  await expect(page.getByRole('columnheader', { name: 'Port', exact: true })).toHaveAttribute(
    'aria-sort',
    'descending',
  )
  await expect(page.locator('tbody tr')).toHaveCount(100)
  await page.getByRole('button', { name: 'Następna' }).click()
  await expect(page.getByText('Strona 2 z 2')).toBeVisible()
  await expect(page.locator('tbody tr')).toHaveCount(5)

  await page.getByTestId('export').click()
  await expect(page.getByText('Zapisano /test/export.json')).toBeVisible()
  expect(await page.evaluate(() => window.testDesktop.exported)).toEqual({
    generation: 1,
    ids: rows.map((row) => row.id).reverse(),
  })
})

test('anuluje zgodę, blokuje Escape w trakcie operacji i potwierdza eskalację', async ({
  page,
}) => {
  await page.addInitScript(installDesktop, { ports: [desktopRow] })
  await page.goto('/')
  await page.getByRole('button', { name: ':9999', exact: true }).click()
  const open = page.getByTestId('kill-open')
  const confirm = page.getByTestId('kill-confirm')
  const dialog = page.getByRole('dialog', { name: /bun/ })
  await open.click()
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect.poll(() => page.evaluate(() => window.testDesktop.cancelled)).toEqual(['initial'])

  await open.click()
  await confirm.click()
  await expect(confirm).toBeDisabled()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeVisible()
  await page.evaluate(() => window.testDesktop.continueTermination!())
  await expect(dialog).toHaveAccessibleName('Wymusić zakończenie bun?')
  await confirm.click()
  await expect(dialog).toBeHidden()
  await expect(page.getByText('Nie znaleziono aktywnych portów.')).toBeVisible()
  expect(await page.evaluate(() => window.testDesktop.terminated)).toEqual([
    { token: 'initial', force: false },
    { token: 'escalation', force: true },
  ])
})
