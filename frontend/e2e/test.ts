import { test as base } from '@playwright/test'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

export { expect } from '@playwright/test'

export const test = base.extend({
  launchOptions: async ({ browserName, launchOptions }, use) => {
    if (process.platform !== 'darwin' || browserName !== 'firefox') {
      await use(launchOptions)
      return
    }

    // Firefox 157 can fail while looking up the user's Firefox data on macOS 27.
    // https://github.com/microsoft/playwright/issues/42768
    const home = await mkdtemp(join(tmpdir(), 'portmanager-firefox-'))
    try {
      await use({
        ...launchOptions,
        env: { ...process.env, ...launchOptions.env, CFFIXED_USER_HOME: home },
      })
    } finally {
      try {
        await rm(home, { recursive: true, force: true })
      } catch (error) {
        // macOS may protect the Downloads folder it creates under this temporary home.
        const code = (error as NodeJS.ErrnoException).code
        if (code !== 'EACCES' && code !== 'EPERM' && code !== 'ENOTEMPTY') throw error
        console.warn(`Firefox: macOS prevented cleanup of ${home}`)
      }
    }
  },
})
