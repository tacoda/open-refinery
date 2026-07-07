const BASE = import.meta.env.VITE_API_BASE ?? ''

export const getToken = () => localStorage.getItem('or_token') || ''
export const setToken = (t: string) => localStorage.setItem('or_token', t)
export const clearToken = () => localStorage.removeItem('or_token')

export async function api(path: string, opts: RequestInit = {}): Promise<any> {
  const res = await fetch(BASE + path, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${getToken()}`,
      ...(opts.headers || {}),
    },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(body.detail || res.statusText)
  }
  return res.status === 204 ? null : res.json()
}

export const post = (path: string, body: unknown) =>
  api(path, { method: 'POST', body: JSON.stringify(body) })

export const oauthLoginUrl = (provider: string) => `${BASE}/auth/${provider}/login`

// Fetch an authed endpoint and save the response as a file (CSV / JSON export).
export async function download(path: string, filename: string): Promise<void> {
  const res = await fetch(BASE + path, { headers: { Authorization: `Bearer ${getToken()}` } })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}
