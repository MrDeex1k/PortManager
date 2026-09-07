export interface AppInfo {
  name: string
  version: string
  mode: 'desktop' | 'browser'
  stage: 'preview'
}

declare global {
  interface Window {
    pywebview?: { api?: { get_app_info(): Promise<AppInfo> } }
  }
}

export async function getAppInfo(): Promise<AppInfo> {
  const api = window.pywebview?.api
  if (!api) return { name: 'PortManager', version: '0.1.0', mode: 'browser', stage: 'preview' }
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      api.get_app_info(),
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => reject(new Error('Aplikacja desktopowa nie odpowiada.')), 5000)
      }),
    ])
  } finally {
    clearTimeout(timer)
  }
}
