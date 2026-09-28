/**
 * The workflow canvas — design mode and live mode.
 *
 * The canvas IS the builder, not a picture of one: what you draw is what gets
 * saved, and saving writes a new pipeline version rather than editing in place,
 * so a change never reaches a run already going.
 *
 * Edges are typed and drawn differently on purpose. `rework` is reachable only
 * through an outcome edge, so a layout that draws `next` alone reports it
 * unreachable — which is the bug the edge types exist to prevent.
 *
 * **Live mode is the same canvas**, at the same node positions, with runs on
 * it. Deliberately not a second drawing: an operator watching work move should
 * be looking at the graph they designed, not a diagram that claims to be it.
 * Passing `runs` turns editing off — you cannot drag a stage while runs are
 * standing on it, because the layout you would save is the one they are using.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Background, Controls, MiniMap, ReactFlow,
  type Edge, type Node, type NodeChange, applyNodeChanges,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import dagre from 'dagre'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

export type Stage = Record<string, any>
export type Graph = {
  name: string
  first?: string
  terminal?: string[]
  model?: string
  stages: Record<string, Stage>
  layout?: Record<string, { x: number; y: number }>
}

// How each kind of edge reads. A refusal going backwards should not look like
// ordinary flow, or a revision loop is invisible until it costs you a turn.
const EDGE_STYLE: Record<string, any> = {
  next: { stroke: 'var(--fg-muted, #64748b)' },
  refusal: { stroke: '#d97706', strokeDasharray: '6 3' },
  merge: { stroke: '#16a34a' },
  close: { stroke: '#64748b', strokeDasharray: '2 3' },
  comment: { stroke: '#2563eb', strokeDasharray: '6 3' },
}

const TERMINALS = ['landed', 'closed', 'failed']

/** Lay the graph out left-to-right when we have no saved positions. */
function layout(stages: Record<string, Stage>, saved?: Record<string, { x: number; y: number }>) {
  const g = new dagre.graphlib.Graph()
  g.setDefaultEdgeLabel(() => ({}))
  g.setGraph({ rankdir: 'LR', nodesep: 40, ranksep: 90 })

  const names = [...Object.keys(stages), ...TERMINALS]
  names.forEach((n) => g.setNode(n, { width: 172, height: 56 }))
  Object.entries(stages).forEach(([name, s]) => {
    for (const to of edgesOf(s).map((e) => e.to)) {
      if (names.includes(to)) g.setEdge(name, to)
    }
  })
  dagre.layout(g)

  const out: Record<string, { x: number; y: number }> = {}
  names.forEach((n) => {
    const saved_ = saved?.[n]
    const p = g.node(n)
    out[n] = saved_ ?? { x: p.x - 86, y: p.y - 28 }
  })
  return out
}

/** Every edge leaving a stage, with its kind — the thing reachability needs. */
function edgesOf(s: Stage): { to: string; kind: string }[] {
  const out: { to: string; kind: string }[] = []
  if (s.next) out.push({ to: s.next, kind: 'next' })
  if (s.on_refusal?.goto) out.push({ to: s.on_refusal.goto, kind: 'refusal' })
  for (const k of ['merge', 'close', 'comment']) {
    if (s[`on_${k}`]) out.push({ to: s[`on_${k}`], kind: k })
  }
  return out
}

/** One run, as the live channel reports it. */
export type LiveRun = {
  id: string
  stage: string
  from?: string
  held?: boolean
  outcome?: string
  reason?: string
  revisions?: number
  at?: string
}

export function Canvas({ graph, onChange, onSelect, selected, runs, onApprove }: {
  graph: Graph
  onChange?: (g: Graph) => void
  onSelect: (name: string | null) => void
  selected: string | null
  runs?: LiveRun[]                       // present = live mode
  onApprove?: (runId: string) => void
}) {
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }>>({})
  const isLive = runs !== undefined

  // Where each run is standing. A run that finished is on its terminal node,
  // which is why `landed` and `closed` are drawn at all.
  const atStage = useMemo(() => {
    const out: Record<string, LiveRun[]> = {}
    for (const r of runs ?? []) (out[r.outcome || r.stage] ||= []).push(r)
    return out
  }, [runs])

  // An edge a run has just crossed, so the move is visible rather than a
  // number quietly changing.
  const crossed = useMemo(() => {
    const out = new Set<string>()
    for (const r of runs ?? []) if (r.from && r.from !== r.stage) out.add(`${r.from}->${r.stage}`)
    return out
  }, [runs])

  useEffect(() => {
    setPositions(layout(graph.stages, graph.layout))
  }, [Object.keys(graph.stages).join(','), graph.layout])

  const nodes: Node[] = useMemo(() => {
    const stageNodes = Object.entries(graph.stages).map(([name, s]) => ({
      id: name,
      position: positions[name] ?? { x: 0, y: 0 },
      data: {
        label: <StageNode name={name} stage={s} model={s.model || graph.model}
                 runs={isLive ? (atStage[name] ?? []) : undefined} onApprove={onApprove} />,
      },
      draggable: !isLive,
      className: [
        'canvas-node',
        name === graph.first ? 'is-first' : '',
        name === selected ? 'is-selected' : '',
        s.approve ? 'is-gated' : '',
        isLive && atStage[name]?.length ? 'is-busy' : '',
        isLive && atStage[name]?.some((r) => r.held) ? 'is-held' : '',
      ].filter(Boolean).join(' '),
    }))
    const terminals = TERMINALS.filter((t) =>
      Object.values(graph.stages).some((s) => edgesOf(s).some((e) => e.to === t)))
      .map((t) => ({
        id: t,
        position: positions[t] ?? { x: 0, y: 0 },
        data: {
          label: (
            <span className="canvas-terminal">
              {t}{isLive && atStage[t]?.length ? ` · ${atStage[t].length}` : ''}
            </span>
          ),
        },
        draggable: !isLive,
        className: ['canvas-node is-terminal',
                    isLive && atStage[t]?.length ? 'is-busy' : ''].filter(Boolean).join(' '),
      }))
    return [...stageNodes, ...terminals] as Node[]
  }, [graph, positions, selected, atStage, isLive, onApprove])

  const edges: Edge[] = useMemo(() =>
    Object.entries(graph.stages).flatMap(([from, s]) =>
      edgesOf(s).map((e) => ({
        id: `${from}-${e.kind}-${e.to}`,
        source: from,
        target: e.to,
        label: e.kind === 'next' ? undefined : e.kind,
        animated: crossed.has(`${from}->${e.to}`) || (!isLive && e.kind === 'refusal'),
        style: EDGE_STYLE[e.kind],
      }))), [graph, crossed, isLive])

  const onNodesChange = useCallback((changes: NodeChange[]) => {
    if (isLive || !onChange) return   // live mode watches; it does not edit
    // Positions are persisted with the pipeline, so a graph opens how it was
    // left rather than being re-laid-out every time.
    const moved = applyNodeChanges(changes, nodes)
    const next: Record<string, { x: number; y: number }> = {}
    moved.forEach((n) => { next[n.id] = n.position })
    setPositions(next)
    if (changes.some((c: any) => c.type === 'position' && c.dragging === false)) {
      onChange({ ...graph, layout: next })
    }
  }, [nodes, graph, onChange, isLive])

  return (
    <div className="canvas">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onNodeClick={(_, n) => onSelect(TERMINALS.includes(n.id) ? null : n.id)}
        onPaneClick={() => onSelect(null)}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  )
}

function StageNode({ name, stage, model, runs, onApprove }: {
  name: string; stage: Stage; model?: string
  runs?: LiveRun[]; onApprove?: (id: string) => void
}) {
  const kind = stage.phase ? `phase · ${stage.phase}` : `action · ${stage.action}`
  const held = (runs ?? []).filter((r) => r.held)
  return (
    <div className="canvas-node-body">
      <span className="canvas-node-name">
        {name}
        {runs?.length ? <span className="canvas-node-count">{runs.length}</span> : null}
      </span>
      <span className="canvas-node-kind">{kind}</span>
      <div className="canvas-node-tags">
        {/* Design mode explains the stage; live mode says what is happening on
            it. Both at once is noise on a node this size. */}
        {runs === undefined ? (<>
          {model && stage.phase && <Badge variant="outline">{model}</Badge>}
          {stage.approve && <Badge>gate</Badge>}
          {stage.contract && <Badge variant="secondary">{stage.contract}</Badge>}
          {stage.optional && <Badge variant="outline">optional</Badge>}
          {stage.opt_in && <Badge variant="outline">opt-in</Badge>}
        </>) : (<>
          {held.length > 0 && <Badge>waiting on you</Badge>}
          {/* A hold is cleared where you notice it. Walking to another screen
              to approve is how a run sits overnight. */}
          {onApprove && held.map((r) => (
            <Button key={r.id} size="sm" variant="outline" className="canvas-approve"
              onClick={(e) => { e.stopPropagation(); onApprove(r.id) }}>
              approve {r.id.slice(0, 6)}
            </Button>
          ))}
        </>)}
      </div>
    </div>
  )
}

/** The inspector — a stage's config is clicking its node. */
export function Inspector({ graph, name, actions, phases, onChange, onDelete }: {
  graph: Graph
  name: string
  actions: { action: string; does: string }[]
  phases: string[]
  onChange: (g: Graph) => void
  onDelete: () => void
}) {
  const stage = graph.stages[name]
  if (!stage) return null

  const set = (patch: Stage) =>
    onChange({ ...graph, stages: { ...graph.stages, [name]: { ...stage, ...patch } } })
  const clear = (key: string) => {
    const { [key]: _drop, ...rest } = stage
    onChange({ ...graph, stages: { ...graph.stages, [name]: rest } })
  }
  const destinations = [...Object.keys(graph.stages).filter((s) => s !== name), ...TERMINALS]

  return (
    <aside className="inspector">
      <header>
        <h3>{name}</h3>
        <Button size="sm" variant="ghost" onClick={onDelete}>Remove</Button>
      </header>

      <label>Does what
        <Select value={stage.phase ? `phase:${stage.phase}` : `action:${stage.action}`}
          onValueChange={(v) => {
            const [kind, value] = (v ?? '').split(':')
            // A stage is a phase or an action, never both — the backend refuses
            // the other shape, so the editor cannot produce it.
            set(kind === 'phase' ? { phase: value, action: undefined }
                                 : { action: value, phase: undefined })
          }}>
          <SelectTrigger className="field"><SelectValue /></SelectTrigger>
          <SelectContent>
            {phases.map((p) => <SelectItem key={p} value={`phase:${p}`}>phase · {p}</SelectItem>)}
            {actions.map((a) => (
              <SelectItem key={a.action} value={`action:${a.action}`}>action · {a.action}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </label>

      {stage.phase && (
        <label>Model
          <Input className="field" value={stage.model ?? ''}
            placeholder={graph.model || 'the workflow default'}
            onChange={(e) => e.target.value ? set({ model: e.target.value }) : clear('model')} />
        </label>
      )}

      <label>Then go to
        <Select value={stage.next ?? ''} onValueChange={(v) => set({ next: v ?? '' })}>
          <SelectTrigger className="field"><SelectValue placeholder="nowhere" /></SelectTrigger>
          <SelectContent>
            {destinations.map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}
          </SelectContent>
        </Select>
      </label>

      {stage.phase && (
        <>
          <label>Contract
            <Select value={stage.contract ?? 'none'}
              onValueChange={(v) => v === 'none' ? clear('contract') : set({ contract: v })}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">none</SelectItem>
                <SelectItem value="proven">proven — needs a command under it</SelectItem>
                <SelectItem value="verdict">verdict — an objection must name a place</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <p className="muted">
            A contract downgrades a claim its own output does not support.
          </p>
        </>
      )}

      <label className="check">
        <input type="checkbox" checked={!!stage.approve}
          onChange={(e) => e.target.checked ? set({ approve: true }) : clear('approve')} />
        Hold for a person before this runs
      </label>
      <p className="muted">
        Cheaper than gating the diff — a wrong approach is caught before the next
        phase spends its turn cap.
      </p>

      <label>On refusal, go back to
        <Select value={stage.on_refusal?.goto ?? 'none'}
          onValueChange={(v) => v === 'none' ? clear('on_refusal')
            : set({ on_refusal: { ...(stage.on_refusal ?? {}), goto: v, max: stage.on_refusal?.max ?? 2, stop_when_identical: true } })}>
          <SelectTrigger className="field"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="none">nowhere — a refusal fails the run</SelectItem>
            {Object.keys(graph.stages).map((d) => <SelectItem key={d} value={d}>{d}</SelectItem>)}
          </SelectContent>
        </Select>
      </label>
      {stage.on_refusal?.goto && (
        <label>Give up after
          <Input className="field" type="number" value={stage.on_refusal.max ?? 2}
            onChange={(e) => set({ on_refusal: { ...stage.on_refusal, max: Number(e.target.value) || 1 } })} />
        </label>
      )}

      <label className="check">
        <input type="checkbox" checked={!!stage.optional}
          onChange={(e) => e.target.checked ? set({ optional: true, opt_in: undefined }) : clear('optional')} />
        Optional — runs unless a run turns it off
      </label>
      <label className="check">
        <input type="checkbox" checked={!!stage.opt_in}
          onChange={(e) => e.target.checked ? set({ opt_in: true, optional: undefined }) : clear('opt_in')} />
        Opt-in — runs only when a run asks
      </label>
      <p className="muted">
        Not the same thing, and conflating them makes every optional stage
        default-on.
      </p>

      <label>Needs (comma separated)
        <Input className="field" value={(stage.requires ?? []).join(', ')}
          placeholder="spec, work"
          onChange={(e) => set({ requires: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} />
      </label>
      <label>Produces
        <Input className="field" value={(stage.produces ?? []).join(', ')}
          placeholder="plan"
          onChange={(e) => set({ produces: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} />
      </label>
      <p className="muted">Sections of the run document, which is also the pull request body.</p>
    </aside>
  )
}
