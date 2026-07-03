import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, post, getToken, setToken, clearToken, oauthLoginUrl } from './api'
import { getTheme, applyTheme, watchSystem, type Theme } from './theme'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Toaster } from '@/components/ui/sonner'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

type View = 'work' | 'repos' | 'processes' | 'events' | 'metrics'
const fail = (e: any) => toast.error(e.message ?? String(e))

export default function App() {
  const [token, setTok] = useState(getToken())
  const [me, setMe] = useState<any>(null)
  const [view, setView] = useState<View>('work')

  // capture an OAuth result handed back in the URL fragment
  useEffect(() => {
    const h = new URLSearchParams(window.location.hash.slice(1))
    const t = h.get('token'), e = h.get('oauth_error')
    if (t) { setToken(t); setTok(t); history.replaceState(null, '', '/') }
    else if (e) {
      toast.error(e === 'no-account' ? 'No account for that GitHub email — ask an admin.' : e)
      history.replaceState(null, '', '/')
    }
  }, [])

  useEffect(() => {
    if (!token) return
    api('/me').then(setMe).catch(() => { clearToken(); setTok(''); setMe(null) })
  }, [token])

  return (
    <>
      <Toaster richColors position="top-right" />
      {!token || !me
        ? <Login onToken={(t) => { setToken(t); setTok(t) }} />
        : (
          <div className="app-shell">
            <Tabs value={view} onValueChange={(v) => setView(v as View)}>
              <header className="app-header">
                <span className="app-brand">open-refinery</span>
                <TabsList>
                  <TabsTrigger value="work">Work</TabsTrigger>
                  <TabsTrigger value="repos">Repos</TabsTrigger>
                  <TabsTrigger value="processes">Processes</TabsTrigger>
                  <TabsTrigger value="events">Audit</TabsTrigger>
                  <TabsTrigger value="metrics">Metrics</TabsTrigger>
                </TabsList>
                <span className="app-spacer" />
                <ThemeToggle />
                <span className="app-user">{me.email} · {me.role}</span>
                <Button variant="outline" size="sm"
                        onClick={() => { clearToken(); setTok(''); setMe(null) }}>
                  Sign out
                </Button>
              </header>
              <TabsContent value="work"><Work /></TabsContent>
              <TabsContent value="repos"><Repos /></TabsContent>
              <TabsContent value="processes"><Processes /></TabsContent>
              <TabsContent value="events"><Events /></TabsContent>
              <TabsContent value="metrics"><Metrics /></TabsContent>
            </Tabs>
          </div>
        )}
    </>
  )
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getTheme())
  useEffect(() => { applyTheme(theme) }, [theme])
  useEffect(() => watchSystem(() => theme), [theme])
  return (
    <Select value={theme} onValueChange={(v) => v && setTheme(v as Theme)}>
      <SelectTrigger size="sm" className="field"><SelectValue /></SelectTrigger>
      <SelectContent>
        <SelectItem value="auto">Auto</SelectItem>
        <SelectItem value="light">Light</SelectItem>
        <SelectItem value="dark">Dark</SelectItem>
      </SelectContent>
    </Select>
  )
}

function Login({ onToken }: { onToken: (t: string) => void }) {
  const [val, setVal] = useState('')
  const [github, setGithub] = useState(false)
  useEffect(() => {
    applyTheme(getTheme())
    api('/auth/providers').then((p) => setGithub(!!p.github)).catch(() => {})
  }, [])
  async function go() {
    setToken(val)
    try { await api('/me'); onToken(val) }
    catch { clearToken(); toast.error('invalid token') }
  }
  return (
    <div className="login-screen">
      <div className="login-card">
        <h1 className="app-brand">open-refinery</h1>
        <p className="login-tagline">An open factory to shine light into the dark.</p>
        {github && (
          <Button onClick={() => { window.location.href = oauthLoginUrl('github') }}>
            Sign in with GitHub
          </Button>
        )}
        <Input placeholder="API token" value={val} type="password"
               onChange={(e) => setVal(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && go()} />
        <Button variant={github ? 'outline' : 'default'} onClick={go}>Sign in with token</Button>
      </div>
    </div>
  )
}

function useList(path: string) {
  const [rows, setRows] = useState<any[]>([])
  const load = () => api(path).then(setRows).catch(fail)
  useEffect(() => { load() }, [])
  return { rows, load }
}

function Repos() {
  const { rows, load } = useList('/repositories')
  const [name, setName] = useState(''), [url, setUrl] = useState('')
  const add = () => post('/repositories', { name, git_url: url })
    .then(() => { setName(''); setUrl(''); load() }).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Repositories</h2>
      <div className="toolbar">
        <Input className="field" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <Input className="field" placeholder="git url" value={url} onChange={(e) => setUrl(e.target.value)} />
        <Button onClick={add}>Add repo</Button>
      </div>
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Git URL</TableHead></TableRow></TableHeader>
          <TableBody>{rows.map((r) => (
            <TableRow key={r.id}><TableCell>{r.name}</TableCell><TableCell className="mono">{r.git_url}</TableCell></TableRow>
          ))}</TableBody>
        </Table>
      </CardContent></Card>
    </section>
  )
}

function Processes() {
  const { rows, load } = useList('/processes')
  const [name, setName] = useState(''), [arch, setArch] = useState('board')
  const [stages, setStages] = useState('todo, doing, done')
  const [oversight, setOversight] = useState('dark'), [gates, setGates] = useState('')
  const add = () => post('/processes', {
    name, archetype: arch, oversight,
    stages: stages.split(',').map((s) => s.trim()).filter(Boolean),
    gates: gates.split(',').map((s) => s.trim()).filter(Boolean),
  }).then(() => { setName(''); load() }).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Processes</h2>
      <div className="toolbar">
        <Input className="field" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
        <Select value={arch} onValueChange={(v) => setArch(v ?? '')}>
          <SelectTrigger className="field"><SelectValue /></SelectTrigger>
          <SelectContent><SelectItem value="board">board</SelectItem><SelectItem value="doctrine">doctrine</SelectItem></SelectContent>
        </Select>
        <Input className="field" placeholder="steps (comma)" value={stages} onChange={(e) => setStages(e.target.value)} />
        <Select value={oversight} onValueChange={(v) => setOversight(v ?? '')}>
          <SelectTrigger className="field"><SelectValue /></SelectTrigger>
          <SelectContent>{['dark', 'autonomous', 'supervised', 'assisted', 'manual'].map((o) =>
            <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
        </Select>
        <Input className="field" placeholder="gated steps (comma)" value={gates} onChange={(e) => setGates(e.target.value)} />
        <Button onClick={add}>Add process</Button>
      </div>
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Name</TableHead><TableHead>Type</TableHead><TableHead>Oversight</TableHead><TableHead>Steps</TableHead>
          </TableRow></TableHeader>
          <TableBody>{rows.map((p) => (
            <TableRow key={p.id}>
              <TableCell>{p.name}</TableCell>
              <TableCell><Badge variant="secondary">{p.archetype}</Badge></TableCell>
              <TableCell><Badge variant="outline">{p.oversight}</Badge></TableCell>
              <TableCell className="mono">{p.stages.join(' → ')}</TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      </CardContent></Card>
    </section>
  )
}

function Work() {
  const { rows, load } = useList('/work-items')
  const [repos, setRepos] = useState<any[]>([])
  const [procs, setProcs] = useState<any[]>([])
  const [title, setTitle] = useState(''), [repo, setRepo] = useState(''), [proc, setProc] = useState('')
  useEffect(() => {
    api('/repositories').then(setRepos).catch(fail)
    api('/processes').then(setProcs).catch(fail)
  }, [])
  const add = () => post('/work-items', { repo_id: repo, process_id: proc, title })
    .then(() => { setTitle(''); load() }).catch(fail)
  const move = (id: string, to: string, approve: boolean) =>
    post(`/work-items/${id}/transition`, { to, approve }).then(load).catch(fail)
  const attest = (id: string, check: string, passed: boolean) =>
    post(`/work-items/${id}/attest`, { check, passed })
      .then(() => toast.success(`attested ${check}`)).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Work items</h2>
      <div className="toolbar">
        <Input className="field" placeholder="title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <Select value={repo} onValueChange={(v) => setRepo(v ?? '')}>
          <SelectTrigger className="field"><SelectValue placeholder="repo…" /></SelectTrigger>
          <SelectContent>{repos.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
        </Select>
        <Select value={proc} onValueChange={(v) => setProc(v ?? '')}>
          <SelectTrigger className="field"><SelectValue placeholder="process…" /></SelectTrigger>
          <SelectContent>{procs.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
        </Select>
        <Button onClick={add}>Ship work</Button>
      </div>
      <div className="work-list">
        {rows.map((w) => <WorkRow key={w.id} w={w} onMove={move} onAttest={attest} />)}
      </div>
    </section>
  )
}

function WorkRow({ w, onMove, onAttest }: any) {
  const [to, setTo] = useState(''), [check, setCheck] = useState('')
  return (
    <Card>
      <CardContent>
        <div className="work-head">
          <span className="work-title">{w.title}</span>
          <Badge>{w.current_stage}</Badge>
        </div>
        <div className="work-actions">
          <Input className="field" placeholder="→ step" value={to} onChange={(e) => setTo(e.target.value)} />
          <Button variant="secondary" size="sm" onClick={() => onMove(w.id, to, false)}>Move</Button>
          <Button size="sm" onClick={() => onMove(w.id, to, true)}>Move + approve</Button>
          <Input className="field" placeholder="check" value={check} onChange={(e) => setCheck(e.target.value)} />
          <Button variant="outline" size="sm" onClick={() => onAttest(w.id, check, true)}>Attest ✓</Button>
          <Button variant="outline" size="sm" onClick={() => onAttest(w.id, check, false)}>Attest ✗</Button>
        </div>
      </CardContent>
    </Card>
  )
}

function Events() {
  const { rows } = useList('/events?limit=100')
  return (
    <section className="page">
      <h2 className="page-title">Audit trail</h2>
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow>
            <TableHead>When</TableHead><TableHead>Event</TableHead><TableHead>Actor</TableHead>
            <TableHead>Owner</TableHead><TableHead>Subject</TableHead>
          </TableRow></TableHeader>
          <TableBody>{rows.map((e) => (
            <TableRow key={e.artifact_id}>
              <TableCell className="mono">{e.created_at.slice(0, 19)}</TableCell>
              <TableCell><Badge variant="secondary">{e.recipe}</Badge></TableCell>
              <TableCell className="mono">{e.actor.slice(0, 8)}</TableCell>
              <TableCell className="mono">{e.owner.slice(0, 8)}</TableCell>
              <TableCell className="mono">{e.subject?.slice(0, 8) ?? '—'}</TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      </CardContent></Card>
    </section>
  )
}

function Metrics() {
  const [m, setM] = useState<any>(null)
  useEffect(() => { api('/metrics').then(setM).catch(fail) }, [])
  if (!m) return null
  const panels = [
    { title: 'WIP by step', data: m.wip_by_stage, accent: 'accent-blue' },
    { title: 'Events', data: m.event_counts, accent: 'accent-green' },
    { title: 'Activity by actor', data: m.activity_by_actor, accent: 'accent-purple' },
    { title: 'Lead times', data: m.lead_times, accent: 'accent-orange' },
  ]
  return (
    <section className="page">
      <h2 className="page-title">Metrics</h2>
      <div className="metric-grid">
        {panels.map((p) => (
          <Card key={p.title} className={p.accent}>
            <CardHeader><CardTitle>{p.title}</CardTitle></CardHeader>
            <CardContent>
              {Object.entries(p.data).map(([k, v]) => (
                <div key={k} className="kv-row"><span className="mono">{k.slice(0, 14)}</span><b>{String(v)}</b></div>
              ))}
              {!Object.keys(p.data).length && <div className="muted">none yet</div>}
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  )
}
