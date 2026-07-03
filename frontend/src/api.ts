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
