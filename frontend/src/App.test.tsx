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

import { Drawer, EmptyRow, Ladder, Overview, Packs, Pipeline, Toggle, human, ruleSentence } from './App'

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

  // Everything on this page is about runs now. It used to count `invoke-failed`
  // and `rollback` — recipes that no longer exist anywhere in the product.
  const METRICS = {
    delivery: {
      runs: 3, in_flight: 1, held: 0, landed: 1, closed: 0, failed: 1,
      finished: 2, landed_pct: 50, reached_a_pull_request: 1,
      avg_seconds_to_pull_request: 600, avg_seconds_to_outcome: 400,
    },
    wip_by_stage: { running: 1, landed: 1, failed: 1 },
    stage_health: [{ stage: 'run', attempts: 2, refused: 1, error: 1, retries: 1, trouble_pct: 100, units: 160 }],
    event_counts: {}, activity_by_actor: {},
  }

  it('counts what is waiting, in flight and failed, and drills in on click', async () => {
    api.mockImplementation(byPath({
      '/metrics': METRICS,
      '/approvals': [{ run_id: 'r1' }],
      '/runs': [{ id: 'run-abcdef12', stage: 'run', held: false, outcome: '' }],
      '/improve': { findings: [] },
    }))
    const goto = vi.fn()
    render(<Overview goto={goto} />)
    await waitFor(() => expect(screen.getByText('Waiting on a person')).toBeInTheDocument())
    expect(screen.getByText('Waiting on a person').previousSibling).toHaveTextContent('1')
    expect(screen.getByText('Runs in flight').previousSibling).toHaveTextContent('1')
    expect(screen.getByText('Runs failed').previousSibling).toHaveTextContent('1')
    fireEvent.click(screen.getByText('Waiting on a person'))
    expect(goto).toHaveBeenCalledWith('approvals')
  })

  it('shows delivery and the stages that keep going wrong', async () => {
    api.mockImplementation(byPath({
      '/metrics': METRICS, '/approvals': [], '/runs': [], '/improve': { findings: [] },
    }))
    render(<Overview goto={() => {}} />)
    await waitFor(() => expect(screen.getByText('Delivery')).toBeInTheDocument())
    expect(screen.getByText(/50%/)).toBeInTheDocument()          // landed, of finished
    expect(screen.getByText('Stages that keep going wrong')).toBeInTheDocument()
    expect(screen.getByText('run')).toBeInTheDocument()
  })

  it('empty state: nothing has run yet', async () => {
    api.mockImplementation(byPath({
      '/metrics': { delivery: { runs: 0 }, wip_by_stage: {}, stage_health: [] },
      '/approvals': [], '/runs': [], '/improve': { findings: [] },
    }))
    render(<Overview goto={() => {}} />)
    await waitFor(() => expect(screen.getByText(/Nothing has run yet/)).toBeInTheDocument())
    expect(screen.getByText(/No runs yet/)).toBeInTheDocument()
  })
})

describe('human (a duration a person can read)', () => {
  it('reads seconds, minutes, hours and days', () => {
    expect(human(0)).toBe('—')
    expect(human(45)).toBe('45s')
    expect(human(600)).toBe('10m')
    expect(human(7200)).toBe('2h')
    expect(human(432000)).toBe('5d')
  })
})

describe('Ladder (where a rule is carried)', () => {
  beforeEach(() => { api.mockReset() })

  const VIEW = {
    rungs: [
      { rung: 0, sees: 'prose in the charter — sees nothing, and asks', ours: true },
      { rung: 1, sees: 'the tool grant — function ids, before any call', ours: true },
      { rung: 2, sees: 'a hook on the call — the arguments, before the write lands', ours: false },
      { rung: 3, sees: 'a callback in the turn', ours: true },
      { rung: 4, sees: 'the delivery gate — the finished diff', ours: true },
      { rung: 5, sees: 'CI — the merged tree, after everybody left', ours: false },
    ],
    constraints: [
      { id: 'r1', text: 'money is Decimal', layer: 'code', rung: 0, enabled: true, mechanical: false, withholds: [] },
      { id: 'r2', text: 'no secrets in a diff', layer: 'code', rung: 4, enabled: true, mechanical: true, predicate: 'no-secrets-in-diff', withholds: [] },
    ],
    capabilities: [],
    withheld: ['execute'],
    predicates: [{ name: 'no-secrets-in-diff', about: 'refuses a diff carrying a credential', sees: 'diff' }],
  }
  const me = { role: 'developer', permissions: ['approve:code'] }

  it('shows every rung, what it sees, and which are not ours', async () => {
    api.mockResolvedValue(VIEW)
    render(<Ladder me={me} />)
    await waitFor(() => expect(screen.getByText(/rung 0 ·/)).toBeInTheDocument())
    expect(screen.getByText(/rung 5 ·/)).toBeInTheDocument()
    // rung 2 is the target repo's commit hook, rung 5 is its CI
    expect(screen.getAllByText('not ours')).toHaveLength(2)
  })

  it('separates a rule that asks from one that is enforced', async () => {
    api.mockResolvedValue(VIEW)
    render(<Ladder me={me} />)
    await waitFor(() => expect(screen.getByText('money is Decimal')).toBeInTheDocument())
    expect(screen.getByText('asks')).toBeInTheDocument()          // rung 0, prose
    expect(screen.getByText('enforced')).toBeInTheDocument()      // rung 4, predicate
  })

  it('shows the net tool grant, which is what rung 1 produces', async () => {
    api.mockResolvedValue(VIEW)
    render(<Ladder me={me} />)
    await waitFor(() => expect(screen.getByText('The net tool grant')).toBeInTheDocument())
    expect(screen.getByText('execute')).toBeInTheDocument()
  })

  it('offers Move only for a layer you may approve', async () => {
    api.mockResolvedValue({
      ...VIEW,
      constraints: [
        { id: 'r1', text: 'mine', layer: 'code', rung: 0, enabled: true, mechanical: false, withholds: [] },
        { id: 'r3', text: 'not mine', layer: 'charter', rung: 0, enabled: true, mechanical: false, withholds: [] },
      ],
    })
    render(<Ladder me={me} />)                                    // holds approve:code only
    await waitFor(() => expect(screen.getByText('mine')).toBeInTheDocument())
    expect(screen.getAllByRole('button', { name: 'Move' })).toHaveLength(1)
  })
})
