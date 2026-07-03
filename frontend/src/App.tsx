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

type View = 'work' | 'approvals' | 'repos' | 'processes' | 'integrations' | 'targets' | 'policies' | 'events' | 'metrics'
const fail = (e: any) => toast.error(e.message ?? String(e))

export default function App() {
  const [token, setTok] = useState(getToken())
  const [me, setMe] = useState<any>(null)
  const [view, setView] = useState<View>('work')

  // capture an OAuth result handed back in the URL fragment
  useEffect(() => {
    const h = new URLSearchParams(window.location.hash.slice(1))
    const t = h.get('token'), e = h.get('oauth_error')
    const connected = h.get('connected'), connErr = h.get('integration_error')
    if (t) { setToken(t); setTok(t); history.replaceState(null, '', '/') }
    else if (e) {
      toast.error(e === 'no-account' ? 'No account for that GitHub email — ask an admin.' : e)
      history.replaceState(null, '', '/')
    } else if (connected) {
      toast.success(`Connected ${connected}`); history.replaceState(null, '', '/')
    } else if (connErr) {
      toast.error('Connection failed'); history.replaceState(null, '', '/')
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
        ? <Entry onToken={(t) => { setToken(t); setTok(t) }} />
        : (
          <div className="app-shell">
            <Tabs value={view} onValueChange={(v) => setView(v as View)}>
              <header className="app-header">
                <span className="app-brand">open-refinery</span>
                <TabsList>
                  <TabsTrigger value="work">Work</TabsTrigger>
                  <TabsTrigger value="approvals">Approvals</TabsTrigger>
                  <TabsTrigger value="repos">Repos</TabsTrigger>
                  <TabsTrigger value="processes">Processes</TabsTrigger>
                  <TabsTrigger value="integrations">Integrations</TabsTrigger>
                  <TabsTrigger value="targets">Targets</TabsTrigger>
                  <TabsTrigger value="policies">Policies</TabsTrigger>
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
              <TabsContent value="approvals"><Approvals /></TabsContent>
              <TabsContent value="repos"><Repos /></TabsContent>
              <TabsContent value="processes"><Processes /></TabsContent>
              <TabsContent value="integrations"><Integrations /></TabsContent>
              <TabsContent value="targets"><Targets /></TabsContent>
              <TabsContent value="policies"><Policies /></TabsContent>
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

function Entry({ onToken }: { onToken: (t: string) => void }) {
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null)
  useEffect(() => {
    applyTheme(getTheme())
    api('/setup/status').then((s) => setNeedsSetup(!!s.needs_setup)).catch(() => setNeedsSetup(false))
  }, [])
  if (needsSetup === null) return null
  return needsSetup ? <SetupWizard onToken={onToken} /> : <Login onToken={onToken} />
}

function SetupWizard({ onToken }: { onToken: (t: string) => void }) {
  const [email, setEmail] = useState(''), [pw, setPw] = useState('')
  async function go() {
    try {
      const r = await post('/setup', { email, password: pw })
      setToken(r.token); onToken(r.token); toast.success('Admin account created')
    } catch (e) { fail(e) }
  }
  return (
    <div className="login-screen">
      <div className="login-card">
        <h1 className="app-brand">Welcome to open-refinery</h1>
        <p className="login-tagline">Create the first admin account to get started.</p>
        <Input placeholder="admin email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input placeholder="password" type="password" value={pw}
               onChange={(e) => setPw(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && go()} />
        <Button onClick={go}>Create admin</Button>
      </div>
    </div>
  )
}

function Login({ onToken }: { onToken: (t: string) => void }) {
  const [email, setEmail] = useState(''), [pw, setPw] = useState('')
  const [github, setGithub] = useState(false)
  useEffect(() => {
    api('/auth/providers').then((p) => setGithub(!!p.github)).catch(() => {})
  }, [])
  async function go() {
    try {
      const r = await post('/auth/login', { email, password: pw })
      setToken(r.token); onToken(r.token)
    } catch { toast.error('invalid email or password') }
  }
  return (
    <div className="login-screen">
      <div className="login-card">
        <h1 className="app-brand">open-refinery</h1>
        <p className="login-tagline">An open factory to shine light into the dark.</p>
        <Input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <Input placeholder="password" type="password" value={pw}
               onChange={(e) => setPw(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && go()} />
        <Button onClick={go}>Sign in</Button>
        {github && (
          <Button variant="outline" onClick={() => { window.location.href = oauthLoginUrl('github') }}>
            Sign in with GitHub
          </Button>
        )}
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
  const [minApprover, setMinApprover] = useState('senior')
  const [chain, setChain] = useState('')
  const add = () => post('/processes', {
    name, archetype: arch, oversight, min_approver_role: minApprover,
    stages: stages.split(',').map((s) => s.trim()).filter(Boolean),
    gates: gates.split(',').map((s) => s.trim()).filter(Boolean),
    approval_chain: chain.split(',').map((s) => s.trim()).filter(Boolean),
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
        <Select value={minApprover} onValueChange={(v) => setMinApprover(v ?? '')}>
          <SelectTrigger className="field"><SelectValue /></SelectTrigger>
          <SelectContent>{['developer', 'senior', 'platform', 'admin'].map((r) =>
            <SelectItem key={r} value={r}>approver: {r}+</SelectItem>)}</SelectContent>
        </Select>
        <Input className="field" placeholder="approval chain (roles, comma)" value={chain}
               onChange={(e) => setChain(e.target.value)} />
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

function Integrations() {
  const { rows, load } = useList('/integrations')
  const [kind, setKind] = useState('github')
  const [token, setToken] = useState(''), [site, setSite] = useState(''), [email, setEmail] = useState('')
  const [providers, setProviders] = useState<Record<string, boolean>>({})
  useEffect(() => { api('/auth/providers').then(setProviders).catch(() => {}) }, [])
  const isJira = kind === 'jira'
  const connectToken = () => {
    const credential = isJira ? { site, email, token } : { token }
    post('/integrations', { kind, credential })
      .then(() => { setToken(''); setSite(''); setEmail(''); load(); toast.success('Connected') })
      .catch(fail)
  }
  const connectOAuth = () => post(`/integrations/${kind}/oauth/start`, {})
    .then((r) => { window.location.href = r.authorize_url }).catch(fail)
  const KINDS = [['github', 'GitHub'], ['gitlab', 'GitLab'], ['linear', 'Linear'], ['jira', 'Jira']]
  return (
    <section className="page">
      <h2 className="page-title">Integrations</h2>
      <Card>
        <CardHeader><CardTitle>Connect a service</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Select value={kind} onValueChange={(v) => setKind(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{KINDS.map(([v, label]) =>
                <SelectItem key={v} value={v}>{label}</SelectItem>)}</SelectContent>
            </Select>
            {isJira && <Input className="field" placeholder="site (acme.atlassian.net)"
                              value={site} onChange={(e) => setSite(e.target.value)} />}
            {isJira && <Input className="field" placeholder="email"
                              value={email} onChange={(e) => setEmail(e.target.value)} />}
            <Input className="field" placeholder="access token" type="password" value={token}
                   onChange={(e) => setToken(e.target.value)} />
            <Button onClick={connectToken}>Connect with token</Button>
            {providers[kind] && (
              <Button variant="outline" onClick={connectOAuth}>Connect with OAuth</Button>
            )}
          </div>
        </CardContent>
      </Card>
      <div className="work-list">
        {rows.map((i) => <IntegrationCard key={i.id} integ={i} onChange={load} />)}
      </div>
    </section>
  )
}

const TRACKERS = ['jira', 'linear']

function IntegrationCard({ integ, onChange }: any) {
  const [repos, setRepos] = useState<any[] | null>(null)
  const tracker = TRACKERS.includes(integ.kind)
  const verify = () => api(`/integrations/${integ.id}/verify`, { method: 'POST' })
    .then((r) => toast.success(`Connected as ${r.account}`)).catch(fail)
  const browse = () => api(`/integrations/${integ.id}/repos`).then(setRepos).catch(fail)
  const remove = () => api(`/integrations/${integ.id}`, { method: 'DELETE' })
    .then(() => { toast.success('Disconnected'); onChange() }).catch(fail)
  const importRepo = (r: any) => post('/repositories/import', { name: r.name, git_url: r.ssh_url })
    .then(() => toast.success(`Imported ${r.name}`)).catch(fail)
  return (
    <Card>
      <CardContent>
        <div className="work-head">
          <span className="work-title">{integ.account}</span>
          <Badge variant="secondary">{integ.kind}</Badge>
        </div>
        <div className="work-actions">
          <Button variant="outline" size="sm" onClick={verify}>Verify</Button>
          {!tracker && <Button variant="secondary" size="sm" onClick={browse}>Browse repos</Button>}
          <Button variant="outline" size="sm" onClick={remove}>Disconnect</Button>
        </div>
        {tracker && <SyncPanel integ={integ} />}
        {repos && (
          <Table>
            <TableBody>{repos.map((r) => (
              <TableRow key={r.full_name}>
                <TableCell>{r.full_name}</TableCell>
                <TableCell><Badge variant="outline">{r.private ? 'private' : 'public'}</Badge></TableCell>
                <TableCell><Button size="sm" onClick={() => importRepo(r)}>Import</Button></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function SyncPanel({ integ }: any) {
  const [repos, setRepos] = useState<any[]>([]), [procs, setProcs] = useState<any[]>([])
  const [repo, setRepo] = useState(''), [proc, setProc] = useState('')
  useEffect(() => {
    api('/repositories').then(setRepos).catch(() => {})
    api('/processes').then(setProcs).catch(() => {})
  }, [])
  const sync = () => post(`/integrations/${integ.id}/sync`, { repo_id: repo, process_id: proc })
    .then((r) => toast.success(`Synced: ${r.created} new, ${r.skipped} skipped`)).catch(fail)
  return (
    <div className="work-actions">
      <Select value={repo} onValueChange={(v) => setRepo(v ?? '')}>
        <SelectTrigger className="field"><SelectValue placeholder="into repo…" /></SelectTrigger>
        <SelectContent>{repos.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
      </Select>
      <Select value={proc} onValueChange={(v) => setProc(v ?? '')}>
        <SelectTrigger className="field"><SelectValue placeholder="using process…" /></SelectTrigger>
        <SelectContent>{procs.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
      </Select>
      <Button size="sm" onClick={sync}>Sync issues</Button>
    </div>
  )
}

function Policies() {
  const { rows, load } = useList('/policies')
  const [effect, setEffect] = useState('deny'), [role, setRole] = useState('*')
  const [action, setAction] = useState('transition'), [resource, setResource] = useState('*')
  const add = () => post('/policies', { effect, role, action, resource })
    .then(load).catch(fail)
  const del = (id: string) => api(`/policies/${id}`, { method: 'DELETE' }).then(load).catch(fail)

  const [text, setText] = useState(''), [scan, setScan] = useState<any>(null)
  const runScan = () => post('/content/scan', { text }).then(setScan).catch(fail)

  return (
    <section className="page">
      <h2 className="page-title">Policies</h2>
      <Card>
        <CardHeader><CardTitle>Add a policy (deny-overrides; default allow)</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Select value={effect} onValueChange={(v) => setEffect(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['deny', 'allow'].map((e) => <SelectItem key={e} value={e}>{e}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="field" placeholder="role (* = any)" value={role} onChange={(e) => setRole(e.target.value)} />
            <Input className="field" placeholder="action (transition / *)" value={action} onChange={(e) => setAction(e.target.value)} />
            <Input className="field" placeholder="resource (step / *)" value={resource} onChange={(e) => setResource(e.target.value)} />
            <Button onClick={add}>Add policy</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Effect</TableHead><TableHead>Role</TableHead><TableHead>Action</TableHead><TableHead>Resource</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{rows.map((p) => (
              <TableRow key={p.id}>
                <TableCell><Badge variant={p.effect === 'deny' ? 'destructive' : 'secondary'}>{p.effect}</Badge></TableCell>
                <TableCell className="mono">{p.role}</TableCell>
                <TableCell className="mono">{p.action}</TableCell>
                <TableCell className="mono">{p.resource}</TableCell>
                <TableCell><Button variant="outline" size="sm" onClick={() => del(p.id)}>Delete</Button></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Content filter — test redaction</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Input className="field" placeholder="text with secrets/PII" value={text} onChange={(e) => setText(e.target.value)} />
            <Button onClick={runScan}>Scan</Button>
          </div>
          {scan && (
            <div>
              <div className="kv-row"><span className="muted">redacted</span><span className="mono">{scan.clean}</span></div>
              <div className="kv-row"><span className="muted">hits</span><span>{scan.hits.map((h: string) => <Badge key={h} variant="secondary">{h}</Badge>)}</span></div>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  )
}

function Targets() {
  const { rows: targets, load: loadT } = useList('/targets')
  const { rows: routes, load: loadR } = useList('/routes')
  const { rows: quotas, load: loadQ } = useList('/quotas')
  const [procs, setProcs] = useState<any[]>([])
  useEffect(() => { api('/processes').then(setProcs).catch(() => {}) }, [])

  const [name, setName] = useState(''), [kind, setKind] = useState('model')
  const [endpoint, setEndpoint] = useState(''), [token, setToken] = useState('')
  const addTarget = () => post('/targets', {
    name, kind, endpoint, credential: token ? { token } : null,
  }).then(() => { setName(''); setEndpoint(''); setToken(''); loadT() }).catch(fail)
  const delTarget = (id: string) => api(`/targets/${id}`, { method: 'DELETE' })
    .then(() => { loadT(); loadR(); loadQ() }).catch(fail)

  const [rProc, setRProc] = useState(''), [rTarget, setRTarget] = useState('')
  const [rStep, setRStep] = useState(''), [rPrio, setRPrio] = useState('0')
  const addRoute = () => post('/routes', {
    process_id: rProc, target_id: rTarget, step: rStep || null, priority: Number(rPrio) || 0,
  }).then(() => { setRStep(''); loadR() }).catch(fail)

  const [qTarget, setQTarget] = useState(''), [qLimit, setQLimit] = useState('')
  const addQuota = () => post('/quotas', { target_id: qTarget, limit: Number(qLimit) || 0 })
    .then(() => { setQLimit(''); loadQ() }).catch(fail)

  const targetName = (id: string) => targets.find((t) => t.id === id)?.name ?? id.slice(0, 8)
  const procName = (id: string) => procs.find((p) => p.id === id)?.name ?? id.slice(0, 8)

  return (
    <section className="page">
      <h2 className="page-title">Targets</h2>
      <Card>
        <CardHeader><CardTitle>Add a target</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Input className="field" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
            <Select value={kind} onValueChange={(v) => setKind(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['model', 'mcp', 'api'].map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="field" placeholder="endpoint / model id" value={endpoint} onChange={(e) => setEndpoint(e.target.value)} />
            <Input className="field" placeholder="token (optional)" type="password" value={token} onChange={(e) => setToken(e.target.value)} />
            <Button onClick={addTarget}>Add target</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Kind</TableHead><TableHead>Endpoint</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{targets.map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.name}</TableCell>
                <TableCell><Badge variant="secondary">{t.kind}</Badge></TableCell>
                <TableCell className="mono">{t.endpoint}</TableCell>
                <TableCell><Button variant="outline" size="sm" onClick={() => delTarget(t.id)}>Delete</Button></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Routes</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Select value={rProc} onValueChange={(v) => setRProc(v ?? '')}>
              <SelectTrigger className="field"><SelectValue placeholder="process…" /></SelectTrigger>
              <SelectContent>{procs.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
            </Select>
            <Select value={rTarget} onValueChange={(v) => setRTarget(v ?? '')}>
              <SelectTrigger className="field"><SelectValue placeholder="target…" /></SelectTrigger>
              <SelectContent>{targets.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="field" placeholder="step (optional)" value={rStep} onChange={(e) => setRStep(e.target.value)} />
            <Input className="field" placeholder="priority" value={rPrio} onChange={(e) => setRPrio(e.target.value)} />
            <Button onClick={addRoute}>Add route</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Process</TableHead><TableHead>Step</TableHead><TableHead>Target</TableHead><TableHead>Priority</TableHead></TableRow></TableHeader>
            <TableBody>{routes.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{procName(r.process_id)}</TableCell>
                <TableCell>{r.step || <span className="muted">any</span>}</TableCell>
                <TableCell>{targetName(r.target_id)}</TableCell>
                <TableCell>{r.priority}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Quotas</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Select value={qTarget} onValueChange={(v) => setQTarget(v ?? '')}>
              <SelectTrigger className="field"><SelectValue placeholder="target…" /></SelectTrigger>
              <SelectContent>{targets.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="field" placeholder="limit (units)" value={qLimit} onChange={(e) => setQLimit(e.target.value)} />
            <Button onClick={addQuota}>Add quota</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Target</TableHead><TableHead>Used / Limit</TableHead></TableRow></TableHeader>
            <TableBody>{quotas.map((q) => (
              <TableRow key={q.id}>
                <TableCell>{targetName(q.target_id)}</TableCell>
                <TableCell className="mono">{q.used} / {q.limit}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>
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
  const requestApproval = (id: string, to: string) =>
    post(`/work-items/${id}/request-approval`, { to })
      .then(() => toast.success('approval requested')).catch(fail)
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
        {rows.map((w) => <WorkRow key={w.id} w={w} onMove={move} onAttest={attest}
                                  onRequest={requestApproval} />)}
      </div>
    </section>
  )
}

function WorkRow({ w, onMove, onAttest, onRequest }: any) {
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
          <Button variant="outline" size="sm" onClick={() => onRequest(w.id, to)}>Request approval</Button>
          <Input className="field" placeholder="check" value={check} onChange={(e) => setCheck(e.target.value)} />
          <Button variant="outline" size="sm" onClick={() => onAttest(w.id, check, true)}>Attest ✓</Button>
          <Button variant="outline" size="sm" onClick={() => onAttest(w.id, check, false)}>Attest ✗</Button>
        </div>
      </CardContent>
    </Card>
  )
}

function Approvals() {
  const { rows, load } = useList('/approvals?status=pending')
  const act = (id: string, action: string) => api(`/approvals/${id}/${action}`, { method: 'POST' })
    .then(() => { toast.success(action === 'approve' ? 'approved' : 'rejected'); load() }).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Pending approvals</h2>
      <div className="work-list">
        {rows.map((r) => {
          const signed = r.approvals.length
          const next = r.required_roles[signed]
          return (
            <Card key={r.id}>
              <CardContent>
                <div className="work-head">
                  <span className="work-title">→ {r.to_step}</span>
                  <Badge variant="outline">{signed}/{r.required_roles.length} signed</Badge>
                  {next && <Badge>next: {next}</Badge>}
                </div>
                <div className="work-actions">
                  <span className="mono">chain: {r.required_roles.join(' → ')}</span>
                  <Button size="sm" onClick={() => act(r.id, 'approve')}>Approve</Button>
                  <Button variant="outline" size="sm" onClick={() => act(r.id, 'reject')}>Reject</Button>
                </div>
              </CardContent>
            </Card>
          )
        })}
        {!rows.length && <div className="muted">no pending approvals</div>}
      </div>
    </section>
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
