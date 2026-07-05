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

type View = 'work' | 'approvals' | 'repos' | 'processes' | 'systems' | 'integrations' | 'targets' | 'policies' | 'packs' | 'proposals' | 'coverage' | 'audits' | 'experiments' | 'invitations' | 'settings' | 'governance' | 'events' | 'metrics'
type Role = { name: string; rank: number }
const fail = (e: any) => toast.error(e.message ?? String(e))

// Grouped navigation: one group is shown at a time (progressive disclosure).
type NavTab = { value: View; label: string; gate?: 'admin' | 'invite' | 'platform' }
const NAV: { group: string; tabs: NavTab[] }[] = [
  { group: 'Work', tabs: [
    { value: 'work', label: 'Work' }, { value: 'approvals', label: 'Approvals' },
    { value: 'repos', label: 'Repos' }, { value: 'processes', label: 'Processes' } ] },
  { group: 'Governance', tabs: [
    { value: 'policies', label: 'Policies' }, { value: 'proposals', label: 'Proposals' },
    { value: 'packs', label: 'Packs' },
    { value: 'governance', label: 'Governance', gate: 'admin' } ] },
  { group: 'Platform', tabs: [
    { value: 'systems', label: 'Systems' },
    { value: 'integrations', label: 'Integrations' }, { value: 'targets', label: 'Targets' } ] },
  { group: 'Insights', tabs: [
    { value: 'metrics', label: 'Metrics' }, { value: 'audits', label: 'Audits' },
    { value: 'coverage', label: 'Coverage' }, { value: 'experiments', label: 'Experiments' },
    { value: 'events', label: 'Audit log' } ] },
  { group: 'Admin', tabs: [
    { value: 'invitations', label: 'Invitations', gate: 'invite' },
    { value: 'settings', label: 'Settings', gate: 'platform' } ] },
]

// Empty-state row for a list; render inside <TableBody> when there are no rows.
export function EmptyRow({ show, cols, children }: { show: boolean; cols: number; children: any }) {
  if (!show) return null
  return <TableRow><TableCell colSpan={cols} className="muted">{children}</TableCell></TableRow>
}

export default function App() {
  const [token, setTok] = useState(getToken())
  const [me, setMe] = useState<any>(null)
  const [roles, setRoles] = useState<Role[]>([])  // admin-configurable authority ladder
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
    api('/roles').then(setRoles).catch(() => {})
  }, [token])

  useEffect(() => {
    document.title = me ? `Open Refinery · ${view[0].toUpperCase()}${view.slice(1)}` : 'Open Refinery'
  }, [view, me])

  // Progressive disclosure: admins land on high-level Insights; everyone else on Work.
  useEffect(() => {
    if (!me) return
    const g = me.role === 'admin' ? 'Insights' : 'Work'
    setGroup(g)
    setView((NAV.find((n) => n.group === g)!.tabs[0].value))
  }, [me])

  const rank = (r: string) => roles.find((x) => x.name === r)?.rank ?? 0
  const minRank = roles.length ? Math.min(...roles.map((r) => r.rank)) : 0
  const canInvite = !!me && rank(me.role) > minRank  // has a lower role to invite
  // ponytail: Settings (org config) gated by name; backend enforces platform/admin.
  const isPlatform = !!me && ['platform', 'admin'].includes(me.role)
  const isAdmin = !!me && me.role === 'admin'
  const [group, setGroup] = useState('Work')

  const allow = (t: NavTab) =>
    t.gate === 'admin' ? isAdmin : t.gate === 'invite' ? canInvite
      : t.gate === 'platform' ? isPlatform : true
  const tabsFor = (g: string) => (NAV.find((n) => n.group === g)?.tabs ?? []).filter(allow)
  const groups = NAV.filter((n) => tabsFor(n.group).length > 0)
  const openGroup = (g: string) => { setGroup(g); const t = tabsFor(g)[0]; if (t) setView(t.value) }

  return (
    <>
      <Toaster richColors position="top-right" />
      {!token || !me
        ? <Entry onToken={(t) => { setToken(t); setTok(t) }} />
        : (
          <div className="app-shell">
            <Tabs value={view} onValueChange={(v) => setView(v as View)}>
              <header className="app-header">
                <span className="app-brand">Open Refinery</span>
                <nav className="nav-group">
                  {groups.map((n) => (
                    <Button key={n.group} size="sm"
                            variant={group === n.group ? 'default' : 'ghost'}
                            onClick={() => openGroup(n.group)}>{n.group}</Button>
                  ))}
                </nav>
                <span className="app-spacer" />
                <ThemeToggle />
                <span className="app-user">{me.email} · {me.role}</span>
                <Button variant="outline" size="sm"
                        onClick={() => { clearToken(); setTok(''); setMe(null) }}>
                  Sign out
                </Button>
              </header>
              <TabsList>
                {tabsFor(group).map((t) => (
                  <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
                ))}
              </TabsList>
              <TabsContent value="work"><Work /></TabsContent>
              <TabsContent value="approvals"><Approvals /></TabsContent>
              <TabsContent value="repos"><Repos /></TabsContent>
              <TabsContent value="processes"><Processes /></TabsContent>
              <TabsContent value="systems"><Systems /></TabsContent>
              <TabsContent value="integrations"><Integrations /></TabsContent>
              <TabsContent value="targets"><Targets /></TabsContent>
              <TabsContent value="policies"><Policies /></TabsContent>
              <TabsContent value="packs"><Packs me={me} roles={roles} /></TabsContent>
              <TabsContent value="proposals"><Proposals me={me} roles={roles} isAdmin={isAdmin} /></TabsContent>
              <TabsContent value="coverage"><Coverage /></TabsContent>
              <TabsContent value="audits"><Audits /></TabsContent>
              <TabsContent value="experiments"><Experiments /></TabsContent>
              {canInvite && <TabsContent value="invitations"><Invitations me={me} roles={roles} /></TabsContent>}
              {isPlatform && <TabsContent value="settings"><Settings /></TabsContent>}
              {isAdmin && <TabsContent value="governance"><Governance /></TabsContent>}
              <TabsContent value="events"><Events isAdmin={isAdmin} /></TabsContent>
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
  const invite = new URLSearchParams(window.location.hash.slice(1)).get('invite')
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null)
  useEffect(() => {
    applyTheme(getTheme())
    api('/setup/status').then((s) => setNeedsSetup(!!s.needs_setup)).catch(() => setNeedsSetup(false))
  }, [])
  if (invite) return <AcceptInvite token={invite} onToken={onToken} />
  if (needsSetup === null) return null
  return needsSetup ? <SetupWizard onToken={onToken} /> : <Login onToken={onToken} />
}

function AcceptInvite({ token, onToken }: { token: string; onToken: (t: string) => void }) {
  const [email, setEmail] = useState(''), [pw, setPw] = useState('')
  useEffect(() => {
    applyTheme(getTheme())
    api(`/invitations/lookup?token=${encodeURIComponent(token)}`)
      .then((r) => setEmail(r.email || '')).catch(() => {})
  }, [])
  async function go() {
    try {
      const r = await post('/invitations/accept', { token, password: pw })
      setToken(r.token); onToken(r.token); history.replaceState(null, '', '/')
      toast.success('Welcome to Open Refinery')
    } catch (e) { fail(e) }
  }
  return (
    <div className="login-screen">
      <div className="login-card">
        <h1 className="app-brand">Open Refinery</h1>
        <p className="login-tagline">
          {email ? `Set a password to join as ${email}.` : 'This invitation is invalid or expired.'}
        </p>
        {email && <>
          <Input placeholder="choose a password" type="password" value={pw}
                 onChange={(e) => setPw(e.target.value)}
                 onKeyDown={(e) => e.key === 'Enter' && go()} />
          <Button onClick={go}>Set password &amp; join</Button>
        </>}
      </div>
    </div>
  )
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
        <h1 className="app-brand">Welcome to Open Refinery</h1>
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
        <h1 className="app-brand">Open Refinery</h1>
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
  const { rows: integs } = useList('/integrations')
  const [name, setName] = useState(''), [url, setUrl] = useState('')
  const add = () => post('/repositories', { name, git_url: url })
    .then(() => { setName(''); setUrl(''); load() }).catch(fail)
  const linkIntegration = (repoId: string, choice: string) =>
    post(`/repositories/${repoId}/integration`, { integration_id: choice === 'auto' ? null : choice })
      .then(load).catch(fail)
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
          <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Git URL</TableHead><TableHead>Ingest source</TableHead></TableRow></TableHeader>
          <TableBody>
            <EmptyRow show={!rows.length} cols={9}>No repositories yet — add or import one.</EmptyRow>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.name}</TableCell>
                <TableCell className="mono">{r.git_url}</TableCell>
                <TableCell>
                  <Select value={r.integration_id ?? 'auto'} onValueChange={(v) => linkIntegration(r.id, v ?? 'auto')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="auto">auto (by host)</SelectItem>
                      {integs.map((i: any) => <SelectItem key={i.id} value={i.id}>{i.kind} · {i.account}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent></Card>
    </section>
  )
}

function Processes() {
  const { rows, load } = useList('/processes')
  const { rows: roleRows } = useList('/roles')
  const [name, setName] = useState(''), [arch, setArch] = useState('board')
  const [stages, setStages] = useState('todo, doing, done')
  const [oversight, setOversight] = useState('dark'), [gates, setGates] = useState('')
  const [minApprover, setMinApprover] = useState('platform')
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
          <SelectContent>{roleRows.map((r: any) =>
            <SelectItem key={r.name} value={r.name}>approver: {r.name}+</SelectItem>)}</SelectContent>
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
          <TableBody><EmptyRow show={!rows.length} cols={9}>Nothing here yet.</EmptyRow>{rows.map((p) => (
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
            <TableBody><EmptyRow show={!repos.length} cols={9}>No repositories yet — add or import one.</EmptyRow>{repos.map((r) => (
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
  const [kind, setKind] = useState('rule')
  const [effect, setEffect] = useState('deny'), [role, setRole] = useState('*')
  const [action, setAction] = useState('transition'), [resource, setResource] = useState('*')
  const [strict, setStrict] = useState(false), [content, setContent] = useState('')
  const [layer, setLayer] = useState('charter')
  const add = () => post('/policies', { kind, effect, role, action, resource, strict, content, layer })
    .then(load).catch(fail)
  const del = (id: string) => api(`/policies/${id}`, { method: 'DELETE' }).then(load).catch(fail)

  const [text, setText] = useState(''), [scan, setScan] = useState<any>(null)
  const runScan = () => post('/content/scan', { text }).then(setScan).catch(fail)

  return (
    <section className="page">
      <h2 className="page-title">Policies</h2>
      <Card>
        <CardHeader><CardTitle>Add a governed artifact (rule / skill / command / agent)</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Select value={kind} onValueChange={(v) => setKind(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['rule', 'skill', 'command', 'agent'].map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}</SelectContent>
            </Select>
            {kind === 'rule' ? (
              <>
                <Select value={effect} onValueChange={(v) => setEffect(v ?? '')}>
                  <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                  <SelectContent>{['deny', 'allow'].map((e) => <SelectItem key={e} value={e}>{e}</SelectItem>)}</SelectContent>
                </Select>
                <Input className="field" placeholder="role (* = any)" value={role} onChange={(e) => setRole(e.target.value)} />
                <Input className="field" placeholder="action (transition / *)" value={action} onChange={(e) => setAction(e.target.value)} />
                <Input className="field" placeholder="resource (step / *)" value={resource} onChange={(e) => setResource(e.target.value)} />
              </>
            ) : (
              <Input className="field" placeholder={`${kind} content`} value={content} onChange={(e) => setContent(e.target.value)} />
            )}
            <Select value={layer} onValueChange={(v) => setLayer(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['factory', 'harness', 'charter'].map((l) => <SelectItem key={l} value={l}>layer: {l}</SelectItem>)}</SelectContent>
            </Select>
            <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
              <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
              strict (no lower-layer override)
            </label>
            <Button onClick={add}>Add</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Kind</TableHead><TableHead>Layer</TableHead><TableHead>Effect</TableHead><TableHead>Role</TableHead><TableHead>Action</TableHead><TableHead>Resource</TableHead><TableHead>Strict</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody><EmptyRow show={!rows.length} cols={9}>Nothing here yet.</EmptyRow>{rows.map((p) => (
              <TableRow key={p.id}>
                <TableCell><Badge variant="outline">{p.kind}</Badge></TableCell>
                <TableCell className="mono">{p.layer}</TableCell>
                <TableCell>{p.kind === 'rule' ? <Badge variant={p.effect === 'deny' ? 'destructive' : 'secondary'}>{p.effect}</Badge> : <span className="mono">{p.content}</span>}</TableCell>
                <TableCell className="mono">{p.role}</TableCell>
                <TableCell className="mono">{p.action}</TableCell>
                <TableCell className="mono">{p.resource}</TableCell>
                <TableCell>{p.strict ? <Badge>strict</Badge> : ''}</TableCell>
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

const SETTING_HINTS = [
  'github.client_id', 'github.client_secret',
  'gitlab.client_id', 'gitlab.client_secret',
  'policy.enforcement',       // audit | strict (whitelist / default-deny)
  'policy.strict_default',    // true | false
]

function Settings() {
  const [keys, setKeys] = useState<string[]>([])
  const load = () => api('/settings').then((r) => setKeys(r.keys)).catch(fail)
  useEffect(() => { load() }, [])
  const [key, setKey] = useState(''), [value, setValue] = useState('')
  const save = () => api('/settings', { method: 'PUT', body: JSON.stringify({ key, value }) })
    .then(() => { setValue(''); load(); toast.success('saved') }).catch(fail)
  const del = (k: string) => api(`/settings/${encodeURIComponent(k)}`, { method: 'DELETE' })
    .then(load).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Settings</h2>
      <Card>
        <CardHeader><CardTitle>Configuration (stored encrypted; values never shown)</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Input className="field" placeholder="key (e.g. github.client_id)" value={key}
                   list="setting-hints" onChange={(e) => setKey(e.target.value)} />
            <datalist id="setting-hints">{SETTING_HINTS.map((h) => <option key={h} value={h} />)}</datalist>
            <Input className="field" placeholder="value" type="password" value={value}
                   onChange={(e) => setValue(e.target.value)} />
            <Button onClick={save}>Save</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Configured key</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{keys.map((k) => (
              <TableRow key={k}>
                <TableCell className="mono">{k}</TableCell>
                <TableCell><Button variant="outline" size="sm" onClick={() => del(k)}>Delete</Button></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>
      <Webhooks />
    </section>
  )
}

function Webhooks() {
  const { rows, load } = useList('/webhooks')
  const [url, setUrl] = useState(''), [events, setEvents] = useState('')
  const [secret, setSecret] = useState('')
  const add = () => post('/webhooks', {
    url, events: events.split(',').map((s) => s.trim()).filter(Boolean),
  }).then((r) => { setSecret(r.secret); setUrl(''); setEvents(''); load() }).catch(fail)
  const del = (id: string) => api(`/webhooks/${id}`, { method: 'DELETE' }).then(load).catch(fail)
  return (
    <Card>
      <CardHeader><CardTitle>Webhooks — fan audit events out (HMAC-signed)</CardTitle></CardHeader>
      <CardContent>
        <div className="toolbar">
          <Input className="field" placeholder="https://your-endpoint" value={url} onChange={(e) => setUrl(e.target.value)} />
          <Input className="field" placeholder="events filter (comma; blank = all)" value={events} onChange={(e) => setEvents(e.target.value)} />
          <Button onClick={add} disabled={!url}>Register</Button>
        </div>
        {secret && <p className="muted mono">signing secret (shown once): {secret}</p>}
        <Table>
          <TableHeader><TableRow><TableHead>URL</TableHead><TableHead>Events</TableHead><TableHead>Last</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody><EmptyRow show={!rows.length} cols={9}>No proposals yet.</EmptyRow>{rows.map((w: any) => (
            <TableRow key={w.id}>
              <TableCell className="mono">{w.url}</TableCell>
              <TableCell className="mono">{(w.events || []).join(', ') || 'all'}</TableCell>
              <TableCell>{w.last_status != null ? <Badge variant={w.last_status >= 200 && w.last_status < 300 ? 'default' : 'destructive'}>{w.last_status}</Badge> : '—'}</TableCell>
              <TableCell><Button variant="outline" size="sm" onClick={() => del(w.id)}>Delete</Button></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function Experiments() {
  const { rows, load } = useList('/experiments')
  const [name, setName] = useState(''), [hyp, setHyp] = useState('')
  const [change, setChange] = useState(''), [layer, setLayer] = useState('harness')
  const create = () => post('/experiments', { name, hypothesis: hyp, change, layer })
    .then(() => { setName(''); setHyp(''); setChange(''); load() }).catch(fail)

  const [sel, setSel] = useState('')
  const [phase, setPhase] = useState('before'), [metric, setMetric] = useState('score')
  const [samples, setSamples] = useState(''), [round, setRound] = useState('1')
  const [analysis, setAnalysis] = useState<any>(null)
  const nums = (s: string) => s.split(',').map((x) => Number(x.trim())).filter((x) => !Number.isNaN(x))
  const rec = () => post(`/experiments/${sel}/evals`, {
    phase, metric, samples: nums(samples), round: Number(round) || 1,
  }).then(() => { setSamples(''); analyze() }).catch(fail)
  const analyze = () => api(`/experiments/${sel}/analysis?metric=${encodeURIComponent(metric)}`)
    .then(setAnalysis).catch(fail)
  const conclude = (id: string) => post(`/experiments/${id}/conclude`, {}).then(load).catch(fail)

  const verdictBadge = (v: string) =>
    v === 'significant improvement' ? 'default' : v === 'significant regression' ? 'destructive' : 'secondary'

  return (
    <section className="page">
      <h2 className="page-title">Evals & experiments</h2>
      <Card>
        <CardHeader><CardTitle>New experiment (hypothesis → change → before/after evals)</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Input className="field" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
            <Select value={layer} onValueChange={(v) => setLayer(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['project', 'platform', 'harness', 'charter'].map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="field" placeholder="hypothesis" value={hyp} onChange={(e) => setHyp(e.target.value)} />
            <Input className="field" placeholder="change under test" value={change} onChange={(e) => setChange(e.target.value)} />
            <Button onClick={create} disabled={!name}>Create</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Layer</TableHead><TableHead>Hypothesis</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody><EmptyRow show={!rows.length} cols={9}>No pending invitations.</EmptyRow>{rows.map((e: any) => (
              <TableRow key={e.id} style={{ cursor: 'pointer', fontWeight: sel === e.id ? 600 : 400 }}
                        onClick={() => { setSel(e.id); setAnalysis(null) }}>
                <TableCell>{e.name}</TableCell>
                <TableCell><Badge variant="secondary">{e.layer}</Badge></TableCell>
                <TableCell className="muted">{e.hypothesis}</TableCell>
                <TableCell>{e.status}</TableCell>
                <TableCell>{e.status === 'running' && <Button size="sm" variant="outline" onClick={(ev) => { ev.stopPropagation(); conclude(e.id) }}>Conclude</Button>}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>

      {sel && (
        <Card>
          <CardHeader><CardTitle>Record eval + analyze</CardTitle></CardHeader>
          <CardContent>
            <div className="toolbar">
              <Select value={phase} onValueChange={(v) => setPhase(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{['before', 'after'].map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent>
              </Select>
              <Input className="field" placeholder="metric" value={metric} onChange={(e) => setMetric(e.target.value)} />
              <Input className="field" placeholder="samples (comma numbers)" value={samples} onChange={(e) => setSamples(e.target.value)} />
              <Input className="field" placeholder="round" value={round} onChange={(e) => setRound(e.target.value)} />
              <Button onClick={rec} disabled={!samples}>Record</Button>
              <Button variant="outline" onClick={analyze}>Analyze</Button>
            </div>
            {analysis && (analysis.verdict === 'insufficient data'
              ? <p className="muted">Insufficient data — record both a before and an after eval.</p>
              : (
                <div>
                  <div className="kv-row"><span>verdict</span><Badge variant={verdictBadge(analysis.verdict)}>{analysis.verdict}</Badge></div>
                  <div className="kv-row"><span className="muted">before → after</span><span className="mono">{analysis.before?.toFixed?.(2)} → {analysis.after?.toFixed?.(2)} (Δ {analysis.delta?.toFixed?.(2)})</span></div>
                  <div className="kv-row"><span className="muted">effect (Cohen's d)</span><span className="mono">{analysis.cohen_d?.toFixed?.(2)}</span></div>
                  <div className="kv-row"><span className="muted">p-value</span><span className="mono">{analysis.p_value?.toFixed?.(4)}</span></div>
                </div>
              ))}
          </CardContent>
        </Card>
      )}
    </section>
  )
}

function Audits() {
  const [h, setH] = useState<any>(null)
  const { rows: hist, load: loadHist } = useList('/audits')
  const loadHealth = () => api('/health/areas').then(setH).catch(fail)
  useEffect(() => { loadHealth() }, [])
  const run = () => post('/audits/run?area=all', {}).then(() => { loadHealth(); loadHist() }).catch(fail)
  const badge = (s: number) => s >= 80 ? 'default' : s >= 50 ? 'secondary' : 'destructive'
  const accent: any = { factory: 'accent-blue', harness: 'accent-purple', charter: 'accent-green' }
  return (
    <section className="page">
      <h2 className="page-title">Debt audits & health</h2>
      <div className="toolbar">
        <Button onClick={run}>Run audit</Button>
        <span className="muted">factory (this service) · harness (artifacts) · charter (repo claims)</span>
      </div>
      {h && (
        <div className="metric-grid">
          {['factory', 'harness', 'charter'].map((a) => (
            <Card key={a} className={accent[a]}>
              <CardHeader><CardTitle>{a} <Badge variant={badge(h[a].score)}>{h[a].score}</Badge></CardTitle></CardHeader>
              <CardContent>
                {h[a].insights.length === 0 && <div className="muted">healthy — no action needed</div>}
                {h[a].insights.map((i: string, k: number) => <div key={k} className="kv-row"><span>{i}</span></div>)}
                {h[a].findings.length > 0 && <div className="muted mono">{h[a].findings.length} finding(s)</div>}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      <Card>
        <CardHeader><CardTitle>Audit history</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>When</TableHead><TableHead>Area</TableHead><TableHead>Score</TableHead><TableHead>Findings</TableHead></TableRow></TableHeader>
            <TableBody>{hist.map((a: any) => (
              <TableRow key={a.id}>
                <TableCell className="mono">{a.created_at.slice(0, 19)}</TableCell>
                <TableCell>{a.area}</TableCell>
                <TableCell><Badge variant={badge(a.score)}>{a.score}</Badge></TableCell>
                <TableCell className="mono">{(a.findings || []).length}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
          {!hist.length && <div className="muted">no audits run yet</div>}
        </CardContent>
      </Card>
    </section>
  )
}

function Coverage() {
  const { rows: repos } = useList('/repositories')
  const [repoId, setRepoId] = useState('')
  const [rep, setRep] = useState<any>(null)
  const [claims, setClaims] = useState<any[]>([])
  useEffect(() => { if (!repoId && repos.length) setRepoId(repos[0].id) }, [repos, repoId])
  const load = (id: string) => {
    if (!id) return
    api(`/repositories/${id}/coverage`).then(setRep).catch(fail)
    api(`/repositories/${id}/claims`).then(setClaims).catch(fail)
  }
  useEffect(() => { load(repoId) }, [repoId])

  const [surface, setSurface] = useState('charter'), [text, setText] = useState('')
  const [hasI, setHasI] = useState(false), [hasG, setHasG] = useState(false)
  const add = () => post(`/repositories/${repoId}/claims`, {
    surface, text, has_instruction: hasI, has_gate: hasG,
  }).then(() => { setText(''); load(repoId) }).catch(fail)
  const del = (id: string) => api(`/claims/${id}`, { method: 'DELETE' }).then(() => load(repoId)).catch(fail)

  const cov = rep?.coverage
  return (
    <section className="page">
      <h2 className="page-title">Repo coverage & drift</h2>
      <div className="toolbar">
        <Select value={repoId} onValueChange={(v) => setRepoId(v ?? '')}>
          <SelectTrigger className="field"><SelectValue placeholder="repository…" /></SelectTrigger>
          <SelectContent>{repos.map((r: any) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
        </Select>
        {cov && <Badge variant={cov.score >= 80 ? 'default' : cov.score >= 50 ? 'secondary' : 'destructive'}>health {cov.score}</Badge>}
        {cov && <span className="muted">covered {cov.covered} · partial {cov.partial} · imitation {cov.imitation} / {cov.total}</span>}
        <Button variant="outline" size="sm" disabled={!repoId}
                onClick={() => post(`/repositories/${repoId}/ingest`, {})
                  .then((r) => { toast.success(`Ingested ${r.created} claim(s)`); load(repoId) }).catch(fail)}>
          Ingest from source
        </Button>
      </div>

      {cov && cov.imitation_surfaces.length > 0 && (
        <Card className="accent-orange">
          <CardHeader><CardTitle>Imitation surfaces — claimed, not enforced (act here)</CardTitle></CardHeader>
          <CardContent>{cov.imitation_surfaces.map((c: any) => (
            <div key={c.id} className="kv-row"><Badge variant="outline">{c.surface}</Badge><span>{c.text}</span></div>
          ))}</CardContent>
        </Card>
      )}

      {rep && rep.drift.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Drift across surfaces</CardTitle></CardHeader>
          <CardContent>{rep.drift.map((d: any) => (
            <div key={d.axis}>
              <div className="kv-row"><span className="muted mono">{d.axis}</span></div>
              {Object.entries(d.only_in).map(([s, list]: any) => list.length > 0 && (
                <div key={s} className="kv-row"><span className="mono">only in {s}</span><span>{list.join(' · ')}</span></div>
              ))}
            </div>
          ))}</CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Claims</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Select value={surface} onValueChange={(v) => setSurface(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['charter', 'harness', 'code'].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="field" placeholder="claimed behavior" value={text} onChange={(e) => setText(e.target.value)} />
            <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <input type="checkbox" checked={hasI} onChange={(e) => setHasI(e.target.checked)} /> instruction
            </label>
            <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
              <input type="checkbox" checked={hasG} onChange={(e) => setHasG(e.target.checked)} /> gate
            </label>
            <Button onClick={add} disabled={!repoId || !text}>Add claim</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Surface</TableHead><TableHead>Claim</TableHead><TableHead>Instruction</TableHead><TableHead>Gate</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>{claims.map((c: any) => (
              <TableRow key={c.id}>
                <TableCell><Badge variant="outline">{c.surface}</Badge></TableCell>
                <TableCell>{c.text}</TableCell>
                <TableCell>{c.has_instruction ? '✓' : '—'}</TableCell>
                <TableCell>{c.has_gate ? '✓' : '—'}</TableCell>
                <TableCell><Button variant="outline" size="sm" onClick={() => del(c.id)}>Delete</Button></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  )
}

function Proposals({ me, roles, isAdmin }: any) {
  const { rows, load } = useList('/proposals')
  const { rows: wfRows, load: loadWf } = useList('/approval-workflows')
  const rank = (r: string) => roles.find((x: Role) => x.name === r)?.rank ?? 0
  const roleNames = roles.map((r: Role) => r.name)

  // admin: configure a layer's approval chain
  const [wfLayer, setWfLayer] = useState(''), [wfChain, setWfChain] = useState('')
  useEffect(() => { if (!wfLayer && roleNames.length) setWfLayer(roleNames[0]) }, [roleNames, wfLayer])
  const saveWf = () => post('/approval-workflows', {
    layer: wfLayer, chain: wfChain.split(',').map((s) => s.trim()).filter(Boolean),
  }).then(() => { setWfChain(''); loadWf() }).catch(fail)

  // propose a change (policy rule) or a free-text suggestion that cascades up
  const [pkind, setPkind] = useState('policy')
  const [layer, setLayer] = useState(''), [effect, setEffect] = useState('deny')
  const [pAction, setPAction] = useState('invoke'), [resource, setResource] = useState('*')
  const [strict, setStrict] = useState(false), [idea, setIdea] = useState('')
  useEffect(() => { if (!layer && roleNames.length) setLayer(roleNames[0]) }, [roleNames, layer])
  const propose = () => post('/proposals', pkind === 'suggestion'
    ? { target_kind: 'suggestion', action: 'adopt', layer, payload: { text: idea } }
    : { target_kind: 'policy', action: 'create', layer,
        payload: { effect, action: pAction, resource, strict, kind: 'rule' } })
    .then(() => { setIdea(''); load() }).catch(fail)

  const act = (p: any, decision: string) =>
    post(`/proposals/${p.id}/review`, { decision, note: '' }).then(load).catch(fail)
  const resub = (p: any) => post(`/proposals/${p.id}/resubmit`, {}).then(load).catch(fail)
  const canReview = (p: any) => p.status === 'pending' && rank(me.role) >= rank(p.chain[p.current])

  return (
    <section className="page">
      <h2 className="page-title">Change proposals</h2>
      <p className="muted">Propose a governance change; it walks the layer's approval chain (accept / deny / feedback).</p>

      {isAdmin && (
        <Card>
          <CardHeader><CardTitle>Approval workflow per layer (admin)</CardTitle></CardHeader>
          <CardContent>
            <div className="toolbar">
              <Select value={wfLayer} onValueChange={(v) => setWfLayer(v ?? '')}>
                <SelectTrigger className="field"><SelectValue placeholder="layer…" /></SelectTrigger>
                <SelectContent>{roleNames.map((r: string) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
              </Select>
              <Input className="field" placeholder="chain: roles comma-sep (e.g. platform, admin)" value={wfChain} onChange={(e) => setWfChain(e.target.value)} />
              <Button onClick={saveWf}>Save workflow</Button>
            </div>
            <Table>
              <TableHeader><TableRow><TableHead>Layer</TableHead><TableHead>Chain</TableHead></TableRow></TableHeader>
              <TableBody>{wfRows.map((w: any) => (
                <TableRow key={w.layer}><TableCell>{w.layer}</TableCell><TableCell className="mono">{(w.chain || []).join(' → ')}</TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Propose — a policy rule, or an idea that cascades up</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Select value={pkind} onValueChange={(v) => setPkind(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="policy">policy rule</SelectItem><SelectItem value="suggestion">suggestion</SelectItem></SelectContent>
            </Select>
            <Select value={layer} onValueChange={(v) => setLayer(v ?? '')}>
              <SelectTrigger className="field"><SelectValue placeholder="layer…" /></SelectTrigger>
              <SelectContent>{roleNames.map((r: string) => <SelectItem key={r} value={r}>layer: {r}</SelectItem>)}</SelectContent>
            </Select>
            {pkind === 'policy' ? (
              <>
                <Select value={effect} onValueChange={(v) => setEffect(v ?? '')}>
                  <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                  <SelectContent>{['deny', 'allow'].map((e) => <SelectItem key={e} value={e}>{e}</SelectItem>)}</SelectContent>
                </Select>
                <Input className="field" placeholder="action" value={pAction} onChange={(e) => setPAction(e.target.value)} />
                <Input className="field" placeholder="resource" value={resource} onChange={(e) => setResource(e.target.value)} />
                <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                  <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} /> strict
                </label>
              </>
            ) : (
              <Input className="field" placeholder="your idea (escalates up the ladder)" value={idea} onChange={(e) => setIdea(e.target.value)} />
            )}
            <Button onClick={propose} disabled={pkind === 'suggestion' && !idea}>Propose</Button>
          </div>
          <p className="muted">No configured workflow? A proposal cascades up the role ladder from your level (accept / deny / feedback at each step).</p>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Change</TableHead><TableHead>Layer</TableHead><TableHead>Chain</TableHead>
              <TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody><EmptyRow show={!rows.length} cols={9}>No policies yet — add a rule or artifact above.</EmptyRow>{rows.map((p: any) => (
              <TableRow key={p.id}>
                <TableCell className="mono">{p.target_kind === 'suggestion'
                  ? `suggestion · ${p.payload?.text ?? ''}`
                  : `${p.target_kind}/${p.action} · ${p.payload?.effect} ${p.payload?.action}/${p.payload?.resource}${p.payload?.strict ? ' (strict)' : ''}`}</TableCell>
                <TableCell>{p.layer}</TableCell>
                <TableCell className="mono">{(p.chain || []).map((r: string, i: number) => i === p.current && p.status === 'pending' ? `[${r}]` : r).join(' → ')}</TableCell>
                <TableCell><Badge variant={p.status === 'denied' ? 'destructive' : p.status === 'accepted' ? 'default' : 'secondary'}>{p.status}</Badge></TableCell>
                <TableCell>
                  {canReview(p) && <span style={{ display: 'flex', gap: '0.3rem' }}>
                    <Button size="sm" onClick={() => act(p, 'accept')}>Accept</Button>
                    <Button size="sm" variant="outline" onClick={() => act(p, 'feedback')}>Feedback</Button>
                    <Button size="sm" variant="outline" onClick={() => act(p, 'deny')}>Deny</Button>
                  </span>}
                  {p.status === 'revising' && p.proposed_by === me.id &&
                    <Button size="sm" onClick={() => resub(p)}>Resubmit</Button>}
                </TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  )
}

function Governance() {
  const [g, setG] = useState<any>(null)
  useEffect(() => { api('/governance').then(setG).catch(fail) }, [])
  if (!g) return null
  return (
    <section className="page">
      <h2 className="page-title">Governance landscape</h2>
      <p className="muted">What is defined where, and what overrides what — across the role layers.</p>
      <div className="toolbar">
        <span className="muted">enforcement</span>
        <Badge variant={g.enforcement === 'strict' ? 'default' : 'outline'}>
          {g.enforcement === 'strict' ? 'strict (whitelist / default-deny)' : 'audit (default-allow)'}
        </Badge>
        <span className="muted">set `policy.enforcement` in Settings to change</span>
      </div>

      <Card>
        <CardHeader><CardTitle>Roles</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>Role</TableHead><TableHead>Rank</TableHead><TableHead>Users</TableHead></TableRow></TableHeader>
            <TableBody>{g.roles.map((r: any) => (
              <TableRow key={r.name}>
                <TableCell>{r.name}</TableCell><TableCell className="mono">{r.rank}</TableCell><TableCell className="mono">{r.users}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Rules by layer (highest authority first)</CardTitle></CardHeader>
        <CardContent>
          {g.layers.length === 0 && <p className="muted">No rules defined.</p>}
          {g.layers.map((layer: any) => (
            <div key={layer.rank}>
              <div className="kv-row"><span className="muted">rank {layer.rank}</span></div>
              <Table>
                <TableHeader><TableRow><TableHead>Effect</TableHead><TableHead>Role</TableHead><TableHead>Action</TableHead><TableHead>Resource</TableHead><TableHead>Author</TableHead><TableHead>Strict</TableHead></TableRow></TableHeader>
                <TableBody>{layer.rules.map((p: any) => (
                  <TableRow key={p.id}>
                    <TableCell><Badge variant={p.effect === 'deny' ? 'destructive' : 'secondary'}>{p.effect}</Badge></TableCell>
                    <TableCell className="mono">{p.role}</TableCell>
                    <TableCell className="mono">{p.action}</TableCell>
                    <TableCell className="mono">{p.resource}</TableCell>
                    <TableCell className="mono">{p.author_role}</TableCell>
                    <TableCell>{p.strict ? <Badge>strict</Badge> : ''}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Overrides — strict rules shadowing a lower layer</CardTitle></CardHeader>
        <CardContent>
          {g.overrides.length === 0
            ? <p className="muted">No overrides.</p>
            : (
              <Table>
                <TableHeader><TableRow><TableHead>Winner (strict)</TableHead><TableHead>Shadowed</TableHead><TableHead>On</TableHead></TableRow></TableHeader>
                <TableBody>{g.overrides.map((o: any, i: number) => (
                  <TableRow key={i}>
                    <TableCell><Badge>{o.winner.author_role}</Badge> {o.winner.effect}</TableCell>
                    <TableCell><Badge variant="outline">{o.shadowed.author_role}</Badge> {o.shadowed.effect}</TableCell>
                    <TableCell className="mono">{o.winner.action} / {o.winner.resource}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            )}
        </CardContent>
      </Card>
    </section>
  )
}

export function Packs({ me, roles }: any) {
  const { rows, load } = useList('/packs')
  const rank = (r: string) => roles.find((x: Role) => x.name === r)?.rank ?? 0
  const canManage = (packRole: string) => rank(me.role) >= rank(packRole)
  const toggle = (p: any) =>
    api(`/packs/${p.key}/${p.enabled ? 'disable' : 'enable'}`, { method: 'POST' })
      .then(load).catch(fail)

  const layers = Array.from(new Set(rows.map((p: any) => p.role)))
    .sort((a: any, b: any) => rank(a) - rank(b))
  const enabledCount = rows.filter((p: any) => p.enabled).length

  return (
    <section className="page">
      <h2 className="page-title">Pack marketplace</h2>
      <p className="muted">
        Browse starter bundles of standards & processes — the modern software / platform / team-workflow
        canon. Enable what fits your team ({enabledCount}/{rows.length} enabled).
      </p>
      {layers.map((layer: any) => (
        <div key={layer}>
          <h3 className="nav-group-label">{layer} packs</h3>
          <div className="market-grid">
            {rows.filter((p: any) => p.role === layer).map((p: any) => (
              <Card key={p.key} className={p.enabled ? 'accent-success market-card' : 'market-card'}>
                <CardHeader>
                  <CardTitle>{p.title} {p.enabled && <Badge>enabled</Badge>}</CardTitle>
                </CardHeader>
                <CardContent className="market-card">
                  <p className="muted">{p.description}</p>
                  <div className="work-actions">
                    <Badge variant="secondary">{p.role}</Badge>
                    <span className="app-spacer" />
                    <Button size="sm" variant={p.enabled ? 'outline' : 'default'}
                            disabled={!canManage(p.role)} onClick={() => toggle(p)}>
                      {p.enabled ? 'Disable' : 'Enable'}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}

function Invitations({ me, roles }: any) {
  const { rows, load } = useList('/invitations')
  const myRank = roles.find((r: Role) => r.name === me.role)?.rank ?? 0
  const options = roles.filter((r: Role) => r.rank < myRank).map((r: Role) => r.name)  // lower roles only
  const [email, setEmail] = useState(''), [role, setRole] = useState('')
  const [ttl, setTtl] = useState('7'), [link, setLink] = useState('')
  useEffect(() => { if (!role && options.length) setRole(options[0]) }, [options, role])
  const invite = () => post('/invitations', { email, role, ttl_days: Number(ttl) || 7 })
    .then((r) => { setLink(r.accept_url); setEmail(''); load(); toast.success('Invitation created') })
    .catch(fail)
  const revoke = (id: string) => api(`/invitations/${id}/revoke`, { method: 'POST' })
    .then(load).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Invitations</h2>
      <Card>
        <CardHeader><CardTitle>Invite a user (they set their own password)</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Input className="field" placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <Select value={role} onValueChange={(v) => setRole(v ?? '')}>
              <SelectTrigger className="field"><SelectValue placeholder="role…" /></SelectTrigger>
              <SelectContent>{options.map((r: string) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
            </Select>
            <Input className="field" placeholder="expires (days)" value={ttl} onChange={(e) => setTtl(e.target.value)} />
            <Button onClick={invite}>Send invite</Button>
          </div>
          {link && <div className="kv-row"><span className="muted">invite link</span><span className="mono">{link}</span></div>}
        </CardContent>
      </Card>
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow><TableHead>Email</TableHead><TableHead>Role</TableHead><TableHead>Expires</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody><EmptyRow show={!rows.length} cols={9}>No integrations connected.</EmptyRow>{rows.map((i) => (
            <TableRow key={i.id}>
              <TableCell>{i.email}</TableCell>
              <TableCell><Badge variant="secondary">{i.role}</Badge></TableCell>
              <TableCell className="mono">{i.expires_at.slice(0, 10)}</TableCell>
              <TableCell><Button variant="outline" size="sm" onClick={() => revoke(i.id)}>Revoke</Button></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      </CardContent></Card>
    </section>
  )
}

function Systems() {
  const { rows, load } = useList('/systems')
  const { rows: repos } = useList('/repositories')
  const [name, setName] = useState(''), [kind, setKind] = useState('service')
  const [picked, setPicked] = useState<string[]>([])
  const [cov, setCov] = useState<Record<string, any>>({})
  const toggle = (id: string) =>
    setPicked((p) => p.includes(id) ? p.filter((x) => x !== id) : [...p, id])
  const add = () => post('/systems', { name, kind, repo_ids: picked })
    .then(() => { setName(''); setPicked([]); load() }).catch(fail)
  const del = (id: string) => api(`/systems/${id}`, { method: 'DELETE' }).then(load).catch(fail)
  const loadCov = (id: string) => api(`/systems/${id}/coverage`).then((r) => setCov((c) => ({ ...c, [id]: r }))).catch(fail)
  const repoName = (id: string) => repos.find((r: any) => r.id === id)?.name ?? id.slice(0, 8)
  const badge = (s: number) => s >= 80 ? 'default' : s >= 50 ? 'secondary' : 'destructive'

  return (
    <section className="page">
      <h2 className="page-title">Systems</h2>
      <p className="muted">Compose repositories into a service / microservice group / server, and roll up their governance health.</p>
      <Card>
        <CardHeader><CardTitle>New system</CardTitle></CardHeader>
        <CardContent>
          <div className="toolbar">
            <Input className="field" placeholder="name" value={name} onChange={(e) => setName(e.target.value)} />
            <Select value={kind} onValueChange={(v) => setKind(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['service', 'microservices', 'server'].map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}</SelectContent>
            </Select>
            <Button onClick={add} disabled={!name}>Create</Button>
          </div>
          <div className="toolbar">
            {repos.map((r: any) => (
              <Button key={r.id} size="sm" variant={picked.includes(r.id) ? 'default' : 'outline'}
                      onClick={() => toggle(r.id)}>{r.name}</Button>
            ))}
            {!repos.length && <span className="muted">no repositories yet</span>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>System</TableHead><TableHead>Kind</TableHead><TableHead>Repos</TableHead><TableHead>Health</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!rows.length} cols={9}>No systems yet — compose repositories above.</EmptyRow>
              {rows.map((s: any) => (
                <TableRow key={s.id}>
                  <TableCell>{s.name}</TableCell>
                  <TableCell><Badge variant="secondary">{s.kind}</Badge></TableCell>
                  <TableCell className="mono">{(s.repo_ids || []).map(repoName).join(', ') || '—'}</TableCell>
                  <TableCell>{cov[s.id]
                    ? <Badge variant={badge(cov[s.id].score)}>{cov[s.id].score} · {cov[s.id].imitation} imitation</Badge>
                    : <Button size="sm" variant="outline" onClick={() => loadCov(s.id)}>Roll up</Button>}</TableCell>
                  <TableCell><Button variant="outline" size="sm" onClick={() => del(s.id)}>Delete</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
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
  const [oauthProviders, setOauthProviders] = useState<string[]>([])
  useEffect(() => {
    api('/processes').then(setProcs).catch(() => {})
    api('/auth/providers').then((p) => setOauthProviders(Object.keys(p).filter((k) => p[k]))).catch(() => {})
  }, [])
  const connectOauth = (targetId: string, provider: string) =>
    post(`/targets/${targetId}/oauth/${provider}/start`, {})
      .then((r) => { window.location.href = r.authorize_url }).catch(fail)

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
  const [qWindow, setQWindow] = useState('')
  const addQuota = () => post('/quotas', {
    target_id: qTarget, limit: Number(qLimit) || 0, window_seconds: Number(qWindow) || 0,
  }).then(() => { setQLimit(''); setQWindow(''); loadQ() }).catch(fail)

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
            <TableBody><EmptyRow show={!targets.length} cols={9}>No targets yet — add a model, MCP, or API target.</EmptyRow>{targets.map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.name}</TableCell>
                <TableCell><Badge variant="secondary">{t.kind}</Badge></TableCell>
                <TableCell className="mono">{t.endpoint}</TableCell>
                <TableCell>
                  <span style={{ display: 'flex', gap: '0.3rem' }}>
                    {oauthProviders.map((p) => (
                      <Button key={p} variant="outline" size="sm" onClick={() => connectOauth(t.id, p)}>OAuth: {p}</Button>
                    ))}
                    <Button variant="outline" size="sm" onClick={() => delTarget(t.id)}>Delete</Button>
                  </span>
                </TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
          <p className="muted">Connect a target by API key (token above) or OAuth (buttons per configured provider).</p>
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
            <TableBody><EmptyRow show={!routes.length} cols={9}>No routes yet.</EmptyRow>{routes.map((r) => (
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
            <Input className="field" placeholder="window secs (0 = lifetime)" value={qWindow} onChange={(e) => setQWindow(e.target.value)} />
            <Button onClick={addQuota}>Add quota</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Target</TableHead><TableHead>Used / Limit</TableHead></TableRow></TableHeader>
            <TableBody><EmptyRow show={!quotas.length} cols={9}>No quotas set.</EmptyRow>{quotas.map((q) => (
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
  const [pm, setPm] = useState<any>(null)
  const runPm = () => pm ? setPm(null)
    : api(`/work-items/${w.id}/postmortem`).then(setPm).catch(fail)
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
          <Button variant="outline" size="sm" onClick={runPm}>{pm ? 'Hide post-mortem' : 'Post-mortem'}</Button>
        </div>
        {pm && (
          <div style={{ marginTop: '0.6rem', borderTop: '1px solid var(--border)', paddingTop: '0.6rem' }}>
            <div className="kv-row"><span className="muted">root cause</span><span>{pm.root_cause}</span></div>
            <div className="kv-row"><span className="muted">duration</span><span className="mono">{pm.duration_seconds}s · {pm.timeline.length} events</span></div>
            {pm.findings.map((f: any, i: number) => (
              <div key={i} className="kv-row"><Badge variant={f.severity === 'high' ? 'destructive' : 'secondary'}>{f.type}</Badge><span>{f.detail}</span></div>
            ))}
            {pm.suggestions.length > 0 && <div className="muted" style={{ marginTop: '0.3rem' }}>Suggested next steps:</div>}
            {pm.suggestions.map((s: string, i: number) => <div key={i} className="kv-row"><span>• {s}</span></div>)}
            <div className="mono" style={{ marginTop: '0.3rem' }}>
              timeline: {pm.timeline.map((t: any) => t.recipe).join(' → ') || '—'}
            </div>
          </div>
        )}
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

function Events({ isAdmin }: any) {
  const { rows, load } = useList('/events?limit=100')
  const [days, setDays] = useState('90')
  const purge = () => post(`/audit/purge?days=${Number(days) || 90}`, {})
    .then((r) => { toast.success(`Purged ${r.purged} event(s)`); load() }).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Audit trail</h2>
      {isAdmin && (
        <div className="toolbar">
          <Input className="field" placeholder="retention days" value={days} onChange={(e) => setDays(e.target.value)} />
          <Button variant="outline" onClick={purge}>Purge older than {days || '90'}d</Button>
        </div>
      )}
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow>
            <TableHead>When</TableHead><TableHead>Event</TableHead><TableHead>Actor</TableHead>
            <TableHead>Owner</TableHead><TableHead>Subject</TableHead>
          </TableRow></TableHeader>
          <TableBody><EmptyRow show={!rows.length} cols={9}>No audit events yet.</EmptyRow>{rows.map((e) => (
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
  const [ga, setGa] = useState<any>(null)
  useEffect(() => {
    api('/metrics').then(setM).catch(fail)
    api('/governance/analysis').then(setGa).catch(() => {})
  }, [])
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

      {ga && (
        <Card>
          <CardHeader><CardTitle>Governance flags {ga.total ? `(${ga.total})` : ''}</CardTitle></CardHeader>
          <CardContent>
            <div className="toolbar">
              {Object.entries(ga.metrics).map(([k, v]) => (
                <Badge key={k} variant="outline">{k}: {String(v)}</Badge>
              ))}
              {!ga.total && <span className="muted">no poison detected at your layer</span>}
            </div>
            {ga.total > 0 && (
              <Table>
                <TableHeader><TableRow><TableHead>Type</TableHead><TableHead>Severity</TableHead><TableHead>Layer</TableHead><TableHead>Detail</TableHead><TableHead>Insight</TableHead></TableRow></TableHeader>
                <TableBody>{ga.findings.map((f: any, i: number) => (
                  <TableRow key={i}>
                    <TableCell><Badge variant={f.severity === 'high' ? 'destructive' : 'secondary'}>{f.type}</Badge></TableCell>
                    <TableCell className="mono">{f.severity}</TableCell>
                    <TableCell className="mono">{f.author_role}</TableCell>
                    <TableCell>{f.detail}</TableCell>
                    <TableCell className="muted">{f.insight}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </section>
  )
}
