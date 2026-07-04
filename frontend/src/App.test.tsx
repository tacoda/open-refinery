import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

// Mock the API module so components render against controlled data (no network).
const api = vi.fn()
const post = vi.fn(() => Promise.resolve({}))
vi.mock('./api', () => ({
  api: (...a: any[]) => api(...a),
  post: (...a: any[]) => post(...a),
  getToken: () => '',
  setToken: () => {},
  clearToken: () => {},
  oauthLoginUrl: () => '',
}))

import { EmptyRow, Packs } from './App'

const ROLES = [
  { name: 'developer', rank: 1 },
  { name: 'platform', rank: 2 },
  { name: 'admin', rank: 3 },
]

function renderTable(node: any) {
  return render(<table><tbody>{node}</tbody></table>)
}

describe('EmptyRow', () => {
  it('renders its message when show is true', () => {
    renderTable(<EmptyRow show={true} cols={3}>nothing yet</EmptyRow>)
    expect(screen.getByText('nothing yet')).toBeInTheDocument()
  })
  it('renders nothing when show is false', () => {
    renderTable(<EmptyRow show={false} cols={3}>nothing yet</EmptyRow>)
    expect(screen.queryByText('nothing yet')).not.toBeInTheDocument()
  })
})

describe('Packs marketplace', () => {
  beforeEach(() => { api.mockReset(); post.mockReset() })

  it('empty state: shows 0/0 enabled and no pack cards', async () => {
    api.mockResolvedValue([])
    render(<Packs me={{ role: 'developer' }} roles={ROLES} />)
    await waitFor(() => expect(screen.getByText(/0\/0 enabled/)).toBeInTheDocument())
  })

  it('populated: lists packs and marks the enabled one', async () => {
    api.mockResolvedValue([
      { key: 'tdd', role: 'developer', title: 'TDD', description: 'test-first', enabled: true },
      { key: 'ci-cd', role: 'platform', title: 'CI/CD', description: 'delivery', enabled: false },
    ])
    render(<Packs me={{ role: 'admin' }} roles={ROLES} />)
    await waitFor(() => expect(screen.getByText('TDD')).toBeInTheDocument())
    expect(screen.getByText('CI/CD')).toBeInTheDocument()
    expect(screen.getByText(/1\/2 enabled/)).toBeInTheDocument()
    expect(screen.getByText('enabled')).toBeInTheDocument()
  })

  it('role-gated: a developer cannot manage a platform-layer pack', async () => {
    api.mockResolvedValue([
      { key: 'ci-cd', role: 'platform', title: 'CI/CD', description: 'delivery', enabled: false },
    ])
    render(<Packs me={{ role: 'developer' }} roles={ROLES} />)
    const btn = await screen.findByRole('button', { name: 'Enable' })
    expect(btn).toBeDisabled()
  })
})
