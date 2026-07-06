import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

import { Drawer, EmptyRow, Overview, Packs, Pipeline, Toggle, ruleSentence } from './App'

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
    const sw = await screen.findByRole('switch', { name: /enable CI\/CD/i })
    expect(sw).toBeDisabled()
    expect(sw).toHaveAttribute('aria-checked', 'false')
  })
})

describe('Toggle switch', () => {
  it('reflects on/off via aria-checked and fires onChange with the toggled value', () => {
    const onChange = vi.fn()
    const { rerender } = render(<Toggle on={false} onChange={onChange} label="x" />)
    const sw = screen.getByRole('switch')
    expect(sw).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(sw)
    expect(onChange).toHaveBeenCalledWith(true)
    rerender(<Toggle on={true} onChange={onChange} label="x" />)
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
  })
})

describe('ruleSentence — policy reads as a qualified statement', () => {
  it('deny with role + action + resource + namespace', () => {
    expect(ruleSentence({ effect: 'deny', role: 'developer', action: 'transition', resource: 'done', namespace: 'payments' }))
      .toBe('The developer role may not transition on done in the payments namespace.')
  })
  it('allow with wildcards reads as anyone / any action / anywhere', () => {
    expect(ruleSentence({ effect: 'allow', role: '*', action: '*', resource: '*', namespace: '' }))
      .toBe('Anyone may perform any action anywhere.')
  })
  it('drops the "on" clause when resource is a wildcard', () => {
    expect(ruleSentence({ effect: 'allow', role: 'platform', action: 'invoke', resource: '*', namespace: '' }))
      .toBe('The platform role may invoke anywhere.')
  })
})

describe('Pipeline (process, drawn)', () => {
  it('renders stages, lights the current one, and notes feedback loops', () => {
    render(<Pipeline stages={['spec', 'build', 'verify', 'ship']} gates={['ship']}
      transitions={[['verify', 'build']]} current="build" />)
    expect(screen.getByText('spec')).toBeInTheDocument()
    expect(screen.getByText('ship')).toBeInTheDocument()
    // current stage carries the lit class
    expect(screen.getByText('build').className).toMatch(/current/)
    // backward transition is surfaced as a feedback loop
    expect(screen.getByText(/feedback:/)).toHaveTextContent('verify → build')
  })
})

describe('Drawer', () => {
  it('renders nothing when closed', () => {
    render(<Drawer open={false} title="X" onClose={() => {}}>body</Drawer>)
    expect(screen.queryByText('body')).not.toBeInTheDocument()
  })
  it('shows title + children and closes on the close button', () => {
    const onClose = vi.fn()
    render(<Drawer open title="Detail" onClose={onClose}>body</Drawer>)
    expect(screen.getByText('Detail')).toBeInTheDocument()
    expect(screen.getByText('body')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalled()
  })
})

describe('Overview (visibility-first home)', () => {
  beforeEach(() => { api.mockReset() })

  const byPath = (map: Record<string, any>) => (p: string) =>
    Promise.resolve(map[p.split('?')[0]] ?? (map[p] ?? []))

  it('highlights actionable counts and drills in on click', async () => {
    api.mockImplementation(byPath({
      '/work-items': [{ id: 'a', current_stage: 'doing' }, { id: 'b', current_stage: 'doing' }],
      '/approvals': [{ id: 'r1' }],
      '/events': [{ recipe: 'denied' }, { recipe: 'invoke-failed' }, { recipe: 'rollback' }],
    }))
    const goto = vi.fn()
    render(<Overview goto={goto} />)
    await waitFor(() => expect(screen.getByText('Approvals awaiting')).toBeInTheDocument())
    // 1 pending approval, 2 work items, 1 denial, 1 failure, 1 rollback-to-apply
    expect(screen.getByText('Approvals awaiting').previousSibling).toHaveTextContent('1')
    fireEvent.click(screen.getByText('Approvals awaiting'))
    expect(goto).toHaveBeenCalledWith('approvals')
  })

  it('empty state: zero counts, no work-by-stage rows', async () => {
    api.mockImplementation(byPath({ '/work-items': [], '/approvals': [], '/events': [] }))
    render(<Overview goto={() => {}} />)
    await waitFor(() => expect(screen.getByText(/No work items yet/)).toBeInTheDocument())
  })
})
