import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { api, post, download, getToken, setToken, clearToken } from './api'
import { Canvas, Inspector, type Graph, type LiveRun } from './Canvas'
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
import { LogoMark } from './Brand'
import {
  LayoutDashboard, ListChecks, CheckSquare, GitBranch, Workflow, Shield, GitPullRequest,
  Package, Boxes, Plug, Users as UsersIcon, BarChart3, Activity, Coins,
  FlaskConical, ScrollText, Settings as SettingsIcon, PanelLeftClose,
  PanelLeft, LogOut, Eye, Bot, Lock, ClipboardCheck,
} from 'lucide-react'

// One icon per view — used by the sidebar and (later) overview cards.
const VIEW_ICON: Record<string, any> = {
  // Set up
  connections: Plug, repos: GitBranch, users: UsersIcon, settings: SettingsIcon,
  // Build
  pipelines: Workflow, rules: Shield,
  // Run
  work: ListChecks, runs: Activity, approvals: CheckSquare,
  proposals: GitPullRequest, harnesses: Bot,
  // Watch
  overview: LayoutDashboard, events: ScrollText, evidence: ClipboardCheck,
  usage: Coins, experiments: FlaskConical, teams: Boxes,
  metrics: BarChart3, myrules: Eye,
}
const GROUP_ICON: Record<string, any> = {
  'Set up': Plug, Build: Workflow, Run: Activity, Watch: BarChart3,
}

type View = 'overview' | 'connections' | 'repos' | 'users'
  | 'pipelines' | 'rules'
  | 'work' | 'runs' | 'approvals' | 'proposals' | 'harnesses'
  | 'events' | 'metrics' | 'evidence' | 'experiments' | 'usage'
  | 'teams' | 'settings' | 'myrules'
type Role = { name: string; rank: number }
const fail = (e: any) => toast.error(e.message ?? String(e))

// Navigation is gated by the PERMISSIONS the signed-in person holds — the same
// set the backend checks (see authority.py). A tab lists what it needs; holding
// none of them hides it.
//
// Four groups, in the order somebody meets them: set the place up, build how
// work should ship, run work through it, then watch what happened.
type NavTab = { value: View; label: string; needs?: string[]; always?: boolean }
const NAV: { group: string; tabs: NavTab[] }[] = [
  { group: 'Set up', tabs: [
    { value: 'connections', label: 'Connections', always: true },   // your own keys
    { value: 'repos', label: 'Repos', always: true },
    { value: 'users', label: 'Users', needs: ['manage:users'] },
    { value: 'settings', label: 'Settings', needs: ['see:operations'] } ] },
  { group: 'Build', tabs: [
    { value: 'pipelines', label: 'Workflows', always: true },       // read open; edit gated
    { value: 'rules', label: 'Rules', always: true } ] },
  { group: 'Run', tabs: [
    { value: 'work', label: 'Work', always: true },
    { value: 'runs', label: 'Runs', always: true },
    { value: 'approvals', label: 'Approvals', always: true },
    { value: 'proposals', label: 'Proposals', always: true },
    { value: 'harnesses', label: 'Agents', needs: ['run:factory'] } ] },
  { group: 'Watch', tabs: [
    { value: 'overview', label: 'Overview', always: true },
    { value: 'events', label: 'Audit log', needs: ['read:audit'] },
    { value: 'evidence', label: 'Evidence', needs: ['read:audit'] },
    { value: 'usage', label: 'Spend', always: true },
    { value: 'experiments', label: 'Experiments', needs: ['see:operations'] },
    { value: 'teams', label: 'Teams', needs: ['see:operations'] },
    { value: 'metrics', label: 'Metrics', always: true } ] },
]

// Holding ANY of a tab's permissions opens it. The backend enforces the same
// thing per route with a 403 — this only decides what is worth showing.
const holds = (me: any, needs?: string[]) =>
  !needs || needs.some((p) => (me?.permissions ?? []).includes(p))

// Empty-state row for a list; render inside <TableBody> when there are no rows.
export function EmptyRow({ show, cols, children }: { show: boolean; cols: number; children: any }) {
  if (!show) return null
  return <TableRow><TableCell colSpan={cols} className="muted">{children}</TableCell></TableRow>
}

// A stage graph, drawn: stages as nodes, flow left→right, gated stages locked,
// the current stage lit, feedback loops noted.
export function Pipeline({ stages, gates = [], transitions = [], current }:
    { stages: string[]; gates?: string[]; transitions?: any[]; current?: string }) {
  const idx = (s: string) => stages.indexOf(s)
  const loops = (transitions || []).filter((t: any[]) => idx(t[1]) >= 0 && idx(t[1]) < idx(t[0]))
  return (
    <div>
      <div className="pipeline">
        {stages.map((s, i) => (
          <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: '.375rem' }}>
            <span className={`pl-node${current === s ? ' current' : ''}${gates.includes(s) ? ' gate' : ''}`}>
              {gates.includes(s) && <Lock size={12} />}{s}
            </span>
            {i < stages.length - 1 && <span className="pl-arrow">→</span>}
          </span>
        ))}
      </div>
      {loops.length > 0 && (
        <div className="pl-loop">↩ feedback: {loops.map((t: any[]) => `${t[0]} → ${t[1]}`).join(', ')}</div>
      )}
    </div>
  )
}

// Modern on/off switch. aria-checked drives both a11y and the CSS knob position.
export function Toggle({ on, disabled, onChange, label }: { on: boolean; disabled?: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label ?? 'toggle'}
            className="switch" disabled={disabled} onClick={() => onChange(!on)}>
      <span className="switch-knob" />
    </button>
  )
}

// Right-hand slide-over: select an item → its detail + actions appear here.
export function Drawer({ open, title, onClose, children }: { open: boolean; title: string; onClose: () => void; children: any }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
  if (!open) return null
  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={title}>
        <div className="drawer-head">
          <span className="drawer-title">{title}</span>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">✕</Button>
        </div>
        {children}
      </aside>
    </>
  )
}

export default function App() {
  const [token, setTok] = useState(getToken())
  const [me, setMe] = useState<any>(null)
  const [roles, setRoles] = useState<Role[]>([])  // admin-configurable authority ladder
  const [view, setView] = useState<View>('overview')

  // A session token handed back in the URL fragment (the invite-free path).
  useEffect(() => {
    const h = new URLSearchParams(window.location.hash.slice(1))
    const t = h.get('token')
    if (t) { setToken(t); setTok(t); history.replaceState(null, '', '/') }
  }, [])

  const [live, setLive] = useState(false)
  useEffect(() => {
    if (!token) return
    api('/me').then(setMe).catch(() => { clearToken(); setTok(''); setMe(null) })
    api('/roles').then(setRoles).catch(() => {})
  }, [token])

  // live channel: real-time job + audit updates (no polling)
  useEffect(() => {
    if (!token) return
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    let ws: WebSocket | null = null
    try {
      ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(token)}`)
      ws.onopen = () => setLive(true)
      ws.onclose = () => setLive(false)
      ws.onerror = () => setLive(false)
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data)
        if (m.type === 'job' && m.status !== 'running') {
          toast(m.status === 'done' ? `Job ${m.kind} finished` : `Job ${m.kind} ${m.status}`)
        }
        if (m.type === 'log') window.dispatchEvent(new CustomEvent('oref-log', { detail: m }))
        // A run moved. Broadcast rather than lift into state: the live canvas
        // is the only thing that wants every move, and re-rendering the whole
        // app on each one is how a busy factory makes the UI unusable.
        if (m.type === 'run') window.dispatchEvent(new CustomEvent('oref-run', { detail: m }))
      }
    } catch { setLive(false) }
    return () => ws?.close()
  }, [token])

  useEffect(() => {
    document.title = me ? `Open Refinery · ${view[0].toUpperCase()}${view.slice(1)}` : 'Open Refinery'
  }, [view, me])

  // Never sit on a view this person's permissions do not open (defence in
  // depth — the backend refuses it too).
  useEffect(() => {
    const tab = NAV.flatMap((n) => n.tabs).find((t) => t.value === view)
    if (me && !(tab?.always || holds(me, tab?.needs))) {
      setGroup('Watch'); setView('overview')
    }
  }, [view, me])

  // Everyone lands on the Overview — what needs attention now.
  useEffect(() => {
    if (!me) return
    setGroup('Watch')
    setView('overview')
  }, [me])

  // First-run: whoever runs the place sees the setup wizard until it is done.
  useEffect(() => {
    if (!me) return
    if (holds(me, ['see:operations', 'manage:users'])) {
      api('/onboarding').then((r) => setOnboarded(!!r.onboarded)).catch(() => setOnboarded(true))
    } else setOnboarded(true)  // everyone else inherits the configured org
  }, [me])

  const canAudit = holds(me, ['read:audit'])
  const [group, setGroup] = useState('Watch')
  const [collapsed, setCollapsed] = useState(false)
  const [onboarded, setOnboarded] = useState<boolean | null>(null)

  const allow = (t: NavTab) => !!me && (t.always || holds(me, t.needs))
  // is `view` open to this person? (mirrors the backend, which enforces it)
  const can = (v: View) => {
    const tab = NAV.flatMap((n) => n.tabs).find((t) => t.value === v)
    return !!me && !!(tab?.always || holds(me, tab?.needs))
  }
  const tabsFor = (g: string) => (NAV.find((n) => n.group === g)?.tabs ?? []).filter(allow)
  const groups = NAV.filter((n) => tabsFor(n.group).length > 0)
  // jump straight to a view from anywhere (Overview drill-in), opening its group
  const goto = (v: View) => {
    const g = NAV.find((n) => n.tabs.some((t) => t.value === v))
    if (g) setGroup(g.group)
    setView(v)
  }

  return (
    <>
      <Toaster richColors position="top-right" />
      {!token || !me
        ? <Entry onToken={(t) => { setToken(t); setTok(t) }} />
        : onboarded === false
        ? <Wizard onDone={() => setOnboarded(true)} me={me} roles={roles} />
        : (
          <div className={`app-shell${collapsed ? ' collapsed' : ''}`}>
            <aside className="sidebar">
              <button className="sidebar-brand" onClick={() => goto('overview')} title="Open Refinery">
                <LogoMark size={24} /><span className="brand-word">Open Refinery</span>
              </button>
              <nav className="sidebar-nav">
                {groups.map((n) => (
                  <div key={n.group} className="sidebar-section">
                    <div className="sidebar-section-label">{n.group}</div>
                    {tabsFor(n.group).map((t) => {
                      const Icon = VIEW_ICON[t.value] ?? GROUP_ICON[n.group] ?? LayoutDashboard
                      return (
                        <button key={t.value} title={t.label}
                                className={`sidebar-item${view === t.value ? ' active' : ''}`}
                                onClick={() => { setGroup(n.group); setView(t.value) }}>
                          <Icon size={16} className="sidebar-icon" />
                          <span className="sidebar-label">{t.label}</span>
                        </button>
                      )
                    })}
                  </div>
                ))}
              </nav>
              <div className="sidebar-foot">
                <button className="sidebar-item" onClick={() => setCollapsed((c) => !c)}
                        title={collapsed ? 'Expand' : 'Collapse'}>
                  {collapsed ? <PanelLeft size={16} className="sidebar-icon" /> : <PanelLeftClose size={16} className="sidebar-icon" />}
                  <span className="sidebar-label">Collapse</span>
                </button>
              </div>
            </aside>
            <main className="app-main">
              <header className="app-topbar">
                <span className="app-spacer" />
                <ThemeToggle />
                {live && <Badge variant="outline" title="live updates connected">● live</Badge>}
                <span className="app-user">{me.email} · {me.role}</span>
                <Button variant="outline" size="sm"
                        onClick={() => { clearToken(); setTok(''); setMe(null) }}>
                  <LogOut size={14} /> Sign out
                </Button>
              </header>
              <Tabs value={view} onValueChange={(v) => setView(v as View)}>
                <TabsList className="sr-only">
                  {tabsFor(group).map((t) => (
                    <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>
                  ))}
                </TabsList>
              {/* content order mirrors the nav (entity-dependency) standard */}
              {/* Set up */}
              <TabsContent value="connections"><Integrations /></TabsContent>
              <TabsContent value="repos"><Repos /></TabsContent>
              {can('users') && <TabsContent value="users"><Users me={me} /></TabsContent>}
              {can('settings') && <TabsContent value="settings"><Settings /></TabsContent>}
              {/* Build */}
              <TabsContent value="pipelines"><Pipelines me={me} /></TabsContent>
              <TabsContent value="rules"><Rules me={me} roles={roles} /></TabsContent>
              {/* Run */}
              <TabsContent value="work"><Work /></TabsContent>
              <TabsContent value="runs"><Runs me={me} /></TabsContent>
              <TabsContent value="approvals"><Approvals /></TabsContent>
              <TabsContent value="proposals"><Proposals me={me} roles={roles} isAdmin={canAudit} /></TabsContent>
              {can('harnesses') && <TabsContent value="harnesses"><Harnesses me={me} roles={roles} /></TabsContent>}
              {/* Watch */}
              <TabsContent value="overview"><Overview goto={goto} can={can} /></TabsContent>
              {can('events') && <TabsContent value="events"><Events isAdmin={canAudit} /></TabsContent>}
              {can('evidence') && <TabsContent value="evidence"><Evidence me={me} /></TabsContent>}
              <TabsContent value="usage"><Usage me={me} /></TabsContent>
              {can('experiments') && <TabsContent value="experiments"><Experiments /></TabsContent>}
              {can('teams') && <TabsContent value="teams"><Teams /></TabsContent>}
              <TabsContent value="metrics"><Metrics /></TabsContent>
              </Tabs>
            </main>
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

function LoginBrand({ tagline }: { tagline: string }) {
  return (
    <div className="login-brand">
      <div className="login-mark"><LogoMark size={44} /></div>
      <h1 className="login-title">Open Refinery</h1>
      <p className="login-tagline">{tagline}</p>
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
        <LoginBrand tagline="Create the first admin account to light up the factory." />
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
  const [auditor, setAuditor] = useState(false), [code, setCode] = useState('')
  const [mfa, setMfa] = useState(false), [mfaCode, setMfaCode] = useState('')
  useEffect(() => {
  }, [])
  async function go() {
    try {
      const r = await post('/auth/login', { email, password: pw, code: mfa ? mfaCode : undefined })
      setToken(r.token); onToken(r.token)
    } catch (e: any) {
      if (String(e?.message || e).includes('mfa_required')) { setMfa(true); toast.info('Enter your authenticator code') }
      else toast.error('invalid email or password')
    }
  }
  async function goAuditor() {
    // an auditor access code IS the bearer token; verify it resolves via /me
    setToken(code)
    try { await api('/me'); onToken(code) }
    catch { setToken(''); toast.error('invalid or expired auditor code') }
  }
  return (
    <div className="login-screen">
      <div className="login-card">
        <LoginBrand tagline="A dark factory with the lights on." />
        {auditor ? (
          <>
            <Input placeholder="auditor access code" value={code} onChange={(e) => setCode(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && goAuditor()} />
            <Button onClick={goAuditor} disabled={!code}>Enter as auditor</Button>
            <Button variant="link" size="sm" onClick={() => setAuditor(false)}>Back to sign in</Button>
          </>
        ) : (
          <>
            <Input placeholder="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            <Input placeholder="password" type="password" value={pw}
                   onChange={(e) => setPw(e.target.value)}
                   onKeyDown={(e) => e.key === 'Enter' && go()} />
            {mfa && (
              <Input placeholder="authenticator code" value={mfaCode} inputMode="numeric"
                     onChange={(e) => setMfaCode(e.target.value)}
                     onKeyDown={(e) => e.key === 'Enter' && go()} />
            )}
            <Button onClick={go}>Sign in</Button>
            <Button variant="link" size="sm" onClick={() => setAuditor(true)}>I have an auditor access code</Button>
          </>
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

// First-run setup wizard — the first admin goes from signed-up to a running
// factory: connect a service, import a repo, enable a pack, shape the first
// adopt standards, then put the first ticket through the factory.
// Onboarding follows the entity dependency direction: services → repos →
// standards → first work. Admins also invite the team who'll run the factory.
const WIZ_BASE = ['Welcome', 'Connect', 'Repository', 'Standards', 'First work']
export function Wizard({ onDone, me, roles }: { onDone: () => void; me: any; roles: Role[] }) {
  const isAdmin = me?.role === 'admin'
  const steps = isAdmin
    ? [...WIZ_BASE.slice(0, 4), 'Invite', 'First work']  // invite before shipping
    : WIZ_BASE
  const [step, setStep] = useState(0)
  const [catalog, setCatalog] = useState<any[]>([])
  const [integs, setIntegs] = useState<any[]>([])
  const reloadInteg = () => api('/integrations').then(setIntegs).catch(() => {})
  useEffect(() => { api('/connectors').then(setCatalog).catch(() => {}); reloadInteg() }, [])

  // step 1 — connect (shared OAuth-first flow)
  const trackers = integs.filter((i) => {
    const c = catalog.find((x) => x.kind === i.kind); return c?.caps.includes('tracker')
  })
  const sources = integs.filter((i) => {
    const c = catalog.find((x) => x.kind === i.kind); return c?.caps.includes('source')
  })

  // step 2 — repo
  const { rows: repos, load: reloadRepos } = useList('/repositories')
  const [rname, setRname] = useState(''), [rurl, setRurl] = useState('')
  const [remoteRepos, setRemoteRepos] = useState<any[]>([])
  const browse = (id: string) => api(`/integrations/${id}/repos`).then(setRemoteRepos).catch(fail)
  const importRepo = (r: any) => post('/repositories/import', { name: r.name, git_url: r.ssh_url })
    .then(() => { toast.success(`Imported ${r.name}`); reloadRepos() }).catch(fail)
  const addRepo = () => post('/repositories', { name: rname, git_url: rurl })
    .then(() => { setRname(''); setRurl(''); reloadRepos() }).catch(fail)

  // step 3 — pack
  const { rows: packs, load: reloadPacks } = useList('/packs')
  const enablePack = (key: string) => api(`/packs/${key}/enable`, { method: 'POST' })
    .then(reloadPacks).catch(fail)

  // add-people step — an admin creates the account and picks a starting preset
  const presetNames = roles.map((r) => r.name)
  const [iemail, setIemail] = useState(''), [irole, setIrole] = useState('developer')
  const [ipw, setIpw] = useState('')
  const [invited, setInvited] = useState<string[]>([])
  const invite = () => post('/users', { email: iemail, password: ipw, role: irole })
    .then(() => { setInvited((v) => [...v, `${iemail} (${irole})`]); setIemail(''); setIpw(''); toast.success('Added') })
    .catch(fail)

  // first work item
  const [wtitle, setWtitle] = useState(''), [wrepo, setWrepo] = useState('')
  // Creating the ticket is not shipping it. The point of this step is to see a
  // run go, so it starts one — the wizard should end at the factory working.
  const ship = () => post('/work-items', { repo_id: wrepo, title: wtitle })
    .then((w) => post('/runs', { work_item_id: w.id }))
    .then(() => toast.success('Run started — watch it on Runs'))
    .catch(fail)

  const finish = () => api('/onboarding/complete', { method: 'POST' }).then(onDone).catch(fail)
  const next = () => setStep((s) => Math.min(s + 1, steps.length - 1))
  const back = () => setStep((s) => Math.max(s - 1, 0))
  const cur = steps[step]
  const last = step === steps.length - 1

  return (
    <div className="wizard-screen">
      <div className="wizard-card">
        <div className="wizard-head">
          <div className="login-mark" style={{ width: 44, height: 44 }}><LogoMark size={26} /></div>
          <div>
            <h1 className="login-title">Set up your factory</h1>
            <p className="login-tagline">Step {step + 1} of {steps.length} · {cur}</p>
          </div>
          <span className="app-spacer" />
          <div className="wizard-steps">
            {steps.map((_, i) => <span key={i} className={`wizard-dot${i === step ? ' active' : i < step ? ' done' : ''}`} />)}
          </div>
        </div>

        <div className="wizard-body">
          {cur === 'Welcome' && (
            <div className="space-y-2">
              <p>Welcome. In a few steps you'll connect your tools, import a repository and adopt a set of standards — then put the first ticket through the factory and watch it run.</p>
              <p className="muted">You're the first user, so what you set up here becomes the org default. Later teammates inherit it.</p>
            </div>
          )}

          {cur === 'Connect' && (
            <div className="space-y-3">
              <p className="muted">Connect the services you need — a code host and/or an issue tracker. OAuth is the one-click path; a token works too. (Or skip and add later.)</p>
              <ConnectService onConnected={reloadInteg} />
              <div className="toolbar">{integs.map((i) => <Badge key={i.id} variant="secondary">{i.kind} · {i.account}</Badge>)}</div>
            </div>
          )}

          {cur === 'Repository' && (
            <div className="space-y-3">
              <p className="muted">Import a repository from a connected code host, or add one by URL.</p>
              {sources.length > 0 && (
                <div className="field-form">
                  <Field label="Browse from">
                    <Select value="" onValueChange={(v) => { if (v) browse(v) }}>
                      <SelectTrigger className="field"><SelectValue placeholder="code host…" /></SelectTrigger>
                      <SelectContent>{sources.map((i) => <SelectItem key={i.id} value={i.id}>{i.kind} · {i.account}</SelectItem>)}</SelectContent>
                    </Select>
                  </Field>
                </div>
              )}
              {remoteRepos.length > 0 && (
                <div className="toolbar">{remoteRepos.slice(0, 12).map((r) => (
                  <Button key={r.full_name} size="sm" variant="outline" onClick={() => importRepo(r)}>+ {r.name}</Button>
                ))}</div>
              )}
              <div className="field-form">
                <Field label="Name"><Input className="field" placeholder="checkout-api" value={rname} onChange={(e) => setRname(e.target.value)} /></Field>
                <Field label="Git URL"><Input className="field" placeholder="git@github.com:org/repo.git" value={rurl} onChange={(e) => setRurl(e.target.value)} /></Field>
                <Button onClick={addRepo} disabled={!rname || !rurl}>Add repo</Button>
              </div>
              <div className="toolbar">{repos.map((r: any) => <Badge key={r.id} variant="secondary">{r.name}</Badge>)}</div>
            </div>
          )}

          {cur === 'Standards' && (
            <div className="space-y-3">
              <p className="muted">Adopt a starter set of standards. Enable what fits (you can add more later).</p>
              <div className="board">{packs.slice(0, 9).map((p: any) => (
                <button key={p.key} className={`wizard-pill${p.enabled ? ' picked' : ''}`}
                        onClick={() => !p.enabled && enablePack(p.key)}>
                  <Package size={15} /> {p.title}{p.enabled && <Badge>on</Badge>}
                </button>
              ))}</div>
            </div>
          )}

          {cur === 'Invite' && (
            <div className="space-y-3">
              <p className="muted">Bring in the team who'll run the factory. Invite users at platform or developer level — they inherit everything you set up here.</p>
              <div className="field-form">
                <Field label="Email"><Input className="field" placeholder="teammate@acme.com" value={iemail} onChange={(e) => setIemail(e.target.value)} /></Field>
                <Field label="Password"><Input className="field" type="password" value={ipw}
                  onChange={(e) => setIpw(e.target.value)} /></Field>
                <Field label="Start from">
                  <Select value={irole} onValueChange={(v) => setIrole(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>{presetNames.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Button onClick={invite} disabled={!iemail || !ipw}>Add</Button>
              </div>
              <div className="toolbar">{invited.map((v: string, i: number) => <Badge key={i} variant="secondary">{v}</Badge>)}</div>
            </div>
          )}

          {cur === 'First work' && (
            <div className="space-y-3">
              <p className="muted">Name the first ticket. Shipping it starts a run — watch it on Runs.</p>
              <div className="field-form">
                <Field label="Title"><Input className="field" placeholder="first task" value={wtitle} onChange={(e) => setWtitle(e.target.value)} /></Field>
                <Field label="Repository">
                  <Select value={wrepo} onValueChange={(v) => setWrepo(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue placeholder="repo…" /></SelectTrigger>
                    <SelectContent>{repos.map((r: any) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Button onClick={ship} disabled={!wtitle || !wrepo}>Ship it</Button>
              </div>
            </div>
          )}
        </div>

        <div className="wizard-foot">
          <Button variant="ghost" size="sm" onClick={finish}>Skip setup</Button>
          <span className="app-spacer" />
          {step > 0 && <Button variant="outline" size="sm" onClick={back}>Back</Button>}
          {last ? <Button onClick={finish}>Finish</Button> : <Button onClick={next}>Next</Button>}
        </div>
      </div>
    </div>
  )
}

function Repos() {
  const { rows, load } = useList('/repositories')
  const [name, setName] = useState(''), [url, setUrl] = useState('')
  const [open, setOpen] = useState<any>(null)
  const add = () => post('/repositories', { name, git_url: url })
    .then(() => { setName(''); setUrl(''); load() }).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Repositories</h2>
      <p className="muted">A repository is a project you ship work into. Each one can say where
        its agent configuration lives — the rules a run is handed before it touches anything.</p>
      <div className="field-form">
        <Field label="Name"><Input className="field" placeholder="e.g. checkout-api" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Git URL"><Input className="field" placeholder="git@github.com:org/repo.git" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Button onClick={add} disabled={!name || !url}>Add repo</Button>
      </div>
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Name</TableHead><TableHead>Git URL</TableHead>
            <TableHead>Charter</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            <EmptyRow show={!rows.length} cols={4}>No repositories yet — add or import one.</EmptyRow>
            {rows.map((r: any) => (
              <TableRow key={r.id}>
                <TableCell>{r.name}</TableCell>
                <TableCell className="mono">{r.git_url}</TableCell>
                <TableCell className="muted">
                  {(r.charter_paths?.length ? r.charter_paths : ['.agents/', 'AGENTS.md']).join(' · ')}
                </TableCell>
                <TableCell>
                  <Button size="sm" variant="outline" onClick={() => setOpen(r)}>Settings</Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent></Card>
      <RepoSettingsDrawer repo={open} onClose={() => setOpen(null)} onSaved={load} />
    </section>
  )
}

function RepoSettingsDrawer({ repo, onClose, onSaved }: any) {
  const [presets, setPresets] = useState<any>({ presets: {}, default: [] })
  const [paths, setPaths] = useState('')
  const [hours, setHours] = useState('0')
  const [oversight, setOversight] = useState('supervised')
  const [maxUnits, setMaxUnits] = useState('0')
  useEffect(() => { api('/repositories/charter-presets').then(setPresets).catch(() => {}) }, [])
  useEffect(() => {
    if (!repo) return
    setPaths((repo.charter_paths ?? []).join('\n'))
    setHours(String(repo.ingest_interval_hours ?? 0))
    setOversight(repo.oversight ?? 'supervised')
    setMaxUnits(String(repo.max_run_units ?? 0))
  }, [repo])
  if (!repo) return null

  const save = () =>
    api(`/repositories/${repo.id}`, { method: 'PUT', body: JSON.stringify({
      charter_paths: paths.split('\n').map((s) => s.trim()).filter(Boolean),
      ingest_interval_hours: Number(hours) || 0,
      oversight,
      max_run_units: Number(maxUnits) || 0,
    }) }).then(() => { toast.success('Saved'); onSaved?.(); onClose() }).catch(fail)

  return (
    <Drawer open={!!repo} title={repo.name} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Agent configuration">
          <textarea className="field" rows={4} value={paths}
            placeholder={(presets.default ?? []).join('\n')}
            onChange={(e) => setPaths(e.target.value)} />
        </Field>
        <p className="muted">
          One path per line. Leave it empty for the default — <span className="mono">.agents/</span> and{' '}
          <span className="mono">AGENTS.md</span>. An override <strong>replaces</strong> the default
          rather than adding to it, so a team that says where their rules live means there.
        </p>
        <div className="toolbar">
          {Object.entries(presets.presets ?? {}).map(([agent, list]: any) => (
            <Button key={agent} size="sm" variant="outline"
              onClick={() => setPaths((list as string[]).join('\n'))}>{agent}</Button>
          ))}
        </div>
        <Field label="Re-read every (hours)">
          <Input className="field" type="number" value={hours} title="0 = only when asked"
            onChange={(e) => setHours(e.target.value)} />
        </Field>
        <Field label="Oversight">
          <Select value={oversight} onValueChange={(v) => setOversight(v ?? 'supervised')}>
            <SelectTrigger className="field"><SelectValue /></SelectTrigger>
            <SelectContent>
              {OVERSIGHT_LEVELS.map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}
            </SelectContent>
          </Select>
        </Field>
        <p className="muted">
          How much of a run waits for a person. <strong>supervised</strong> holds what a
          rule marks <span className="mono">ask</span>; <strong>dark</strong> holds nothing.
          At <strong>autonomous</strong> and <strong>dark</strong>, <span className="mono">ask</span>{' '}
          degrades to <em>refuse</em> rather than to yes — an unattended factory reading{' '}
          <span className="mono">ask</span> as yes has answered a question nobody put.
        </p>
        <Field label="Ceiling for one run (units)">
          <Input className="field" type="number" value={maxUnits} title="0 = unlimited"
            onChange={(e) => setMaxUnits(e.target.value)} />
        </Field>
        <p className="muted">
          What a single run may spend before it is stopped. 0 is unlimited. Checked
          between stages, so a stage already under way runs to its end — bound that
          with the phase's turn cap.
        </p>
        <Button onClick={save}>Save</Button>
      </div>
    </Drawer>
  )
}

// Credential field metadata — label + placeholder + whether it's a secret.

// Harness identities — register a coding agent (Claude Code, …) so its CLI is
// authenticated to the platform and governed by its role.
function Harnesses({ me, roles }: any) {
  const { rows, load } = useList('/harnesses')
  const [catalog, setCatalog] = useState<any[]>([])
  useEffect(() => { api('/harnesses/catalog').then(setCatalog).catch(() => {}) }, [])
  const [hkind, setHkind] = useState('claude-code'), [hname, setHname] = useState('')
  const [role, setRole] = useState(me.role)
  const [issued, setIssued] = useState<any>(null)  // {harness, token, setup} — shown once
  const kindLabel = (k: string) => catalog.find((c) => c.kind === k)?.label ?? k
  const register = () => post('/harnesses', { harness_kind: hkind, name: hname, role })
    .then((r) => { setIssued(r); setHname(''); load() }).catch(fail)
  const rotate = (id: string) => api(`/harnesses/${id}/rotate`, { method: 'POST' })
    .then((r) => { setIssued({ harness: rows.find((x: any) => x.id === id), token: r.token,
      setup: { OPEN_REFINERY_TOKEN: r.token } }); toast.success('token rotated') }).catch(fail)
  const revoke = (id: string) => api(`/harnesses/${id}`, { method: 'DELETE' }).then(load).catch(fail)

  // device flow: a human approves an agent that started a device request
  const [ucode, setUcode] = useState(''), [drole, setDrole] = useState(me.role)
  const approve = () => post('/agent/device/approve', { user_code: ucode, role: drole })
    .then((r) => { toast.success(`Authorized ${r.harness.name}`); setUcode(''); load() }).catch(fail)

  return (
    <section className="page">
      <h2 className="page-title">Harnesses</h2>
      <p className="muted">Give a coding agent (Claude Code, and more soon) an identity. Its token authenticates the CLI to the platform — and every action it takes is governed by its role under the current enforcement mode, just like a person.</p>
      <Card>
        <CardHeader><CardTitle>Authorize an agent (device flow)</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">The preferred path: the agent runs <span className="mono">open-refinery login</span>, shows a code, and you approve it here — no token to copy. Enter the code the agent displays:</p>
          <div className="field-form">
            <Field label="Code"><Input className="field" placeholder="XXXX-XXXX" value={ucode} onChange={(e) => setUcode(e.target.value)} /></Field>
            <Field label="Runs as role">
              <Select value={drole} onValueChange={(v) => setDrole(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{roles.map((r: Role) => <SelectItem key={r.name} value={r.name}>{r.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Button onClick={approve} disabled={!ucode}>Authorize</Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Register an agent (token)</CardTitle></CardHeader>
        <CardContent>
          <div className="field-form">
            <Field label="Agent">
              <Select value={hkind} onValueChange={(v) => setHkind(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{catalog.map((c) => <SelectItem key={c.kind} value={c.kind}>{c.label}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Name"><Input className="field" placeholder="e.g. my-claude" value={hname} onChange={(e) => setHname(e.target.value)} /></Field>
            <Field label="Runs as role">
              <Select value={role} onValueChange={(v) => setRole(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{roles.map((r: Role) => <SelectItem key={r.name} value={r.name}>{r.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Button onClick={register} disabled={!hname}>Register</Button>
          </div>
          {issued && (
            <div className="policy-preview" style={{ borderLeftColor: 'var(--primary)' }}>
              <div><strong>{issued.harness?.name}</strong> registered as <Badge variant="secondary">{issued.harness?.role ?? role}</Badge> — copy this token now, it won't be shown again:</div>
              <pre className="mono" style={{ whiteSpace: 'pre-wrap', marginTop: '.4rem' }}>{Object.entries(issued.setup).map(([k, v]) => `export ${k}=${v}`).join('\n')}</pre>
              <p className="muted">Set these where the agent runs (e.g. Claude Code's environment); its calls are now authenticated and governed.</p>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Agent</TableHead><TableHead>Role</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!rows.length} cols={4}>No agents registered yet.</EmptyRow>
              {rows.map((h: any) => (
                <TableRow key={h.id}>
                  <TableCell>{h.name}</TableCell>
                  <TableCell><Badge variant="secondary">{kindLabel(h.harness_kind)}</Badge></TableCell>
                  <TableCell><Badge variant="outline">{h.role}</Badge></TableCell>
                  <TableCell><span style={{ display: 'flex', gap: '.3rem' }}>
                    <Button variant="outline" size="sm" onClick={() => rotate(h.id)}>Rotate token</Button>
                    <Button variant="outline" size="sm" onClick={() => revoke(h.id)}>Revoke</Button>
                  </span></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  )
}

// Shared connect flow (Integrations + onboarding). OAuth is the preferred path
// when configured; a token is the always-available fallback.
export function ConnectService({ onConnected }: { onConnected?: () => void }) {
  // Driven entirely by /credentials/catalog: the fields to ask for, where to
  // mint the key, and exactly what permissions it needs. One catalog, so adding
  // a provider is a backend entry rather than a frontend change.
  const [catalog, setCatalog] = useState<any[]>([])
  const [key, setKey] = useState('github')
  const [creds, setCreds] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  useEffect(() => { api('/credentials/catalog').then(setCatalog).catch(fail) }, [])

  const provider = catalog.find((c) => c.key === key)
  const fields: any[] = provider?.fields ?? []
  const missing = fields.some((f) => f.required && !creds[f.name])
  const pick = (v: string) => { setKey(v); setCreds({}) }

  const connect = () => {
    setBusy(true)
    post('/credentials', { provider: key, credential: creds })
      .then((row) => {
        setCreds({})
        // The account it resolved to — proof the key works, not just that it saved.
        toast.success(`Connected as ${row.account}`)
        onConnected?.()
      })
      .catch(fail)
      .finally(() => setBusy(false))
  }

  return (
    <div className="space-y-3">
      <div className="field-form">
        <Field label="Service">
          <Select value={key} onValueChange={(v) => pick(v ?? '')}>
            <SelectTrigger className="field"><SelectValue /></SelectTrigger>
            <SelectContent>
              {catalog.map((c) => (
                <SelectItem key={c.key} value={c.key}>{c.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {fields.map((f) => (
          <Field key={f.name} label={f.label}>
            <Input className="field" placeholder={f.placeholder}
              type={f.secret ? 'password' : 'text'} value={creds[f.name] ?? ''}
              onChange={(e) => setCreds((c) => ({ ...c, [f.name]: e.target.value }))} />
          </Field>
        ))}
        <Button onClick={connect} disabled={missing || busy}>
          {busy ? 'Verifying…' : fields.length ? 'Connect' : `Use ${provider?.label}`}
        </Button>
      </div>
      {provider && (
        <div className="space-y-1">
          {/* What to paste, without leaving to go and find out */}
          <p className="muted">Needs: {provider.needs}</p>
          {provider.mint_url && (
            <p className="muted">
              <a href={provider.mint_url} target="_blank" rel="noreferrer">
                Create one on {provider.label} →
              </a>
            </p>
          )}
          <p className="muted">
            The key is verified before it is stored, and is never shown again.
          </p>
        </div>
      )}
    </div>
  )
}

function Integrations() {
  const { rows, load } = useList('/credentials')
  const family = (f: string) => rows.filter((r: any) => r.family === f)
  const verify = (id: string) =>
    post(`/credentials/${id}/verify`, {})
      .then((r) => { r.status === 'ok' ? toast.success(`OK — ${r.account}`) : toast.error(r.status_detail); load() })
      .catch(fail)
  const revoke = (id: string) =>
    api(`/credentials/${id}`, { method: 'DELETE' }).then(load).catch(fail)

  return (
    <section className="page">
      <header><h2>Connections</h2>
        <p className="muted">Your own keys. Every run uses the credentials of whoever started it,
          so a pull request is authored by the person accountable for it.</p></header>
      <Card><CardHeader><CardTitle>Connect a service</CardTitle></CardHeader>
        <CardContent><ConnectService onConnected={load} /></CardContent></Card>
      {['model', 'forge', 'tracker'].map((f) => (
        <Card key={f}><CardHeader><CardTitle>{FAMILY_LABEL[f]}</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader><TableRow>
                <TableHead>Service</TableHead><TableHead>Account</TableHead>
                <TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                <EmptyRow show={family(f).length === 0} cols={4}>Nothing connected yet.</EmptyRow>
                {family(f).map((r: any) => (
                  <TableRow key={r.id}>
                    <TableCell>{r.label}{r.shared && <Badge variant="outline">org-wide</Badge>}</TableCell>
                    <TableCell>{r.account}</TableCell>
                    <TableCell>
                      {r.status === 'ok'
                        ? <Badge variant="outline">ok</Badge>
                        : <span title={r.status_detail}><Badge variant="destructive">failing</Badge></span>}
                    </TableCell>
                    <TableCell className="toolbar">
                      <Button size="sm" variant="outline" onClick={() => verify(r.id)}>Verify</Button>
                      <Button size="sm" variant="ghost" onClick={() => revoke(r.id)}>Revoke</Button>
                    </TableCell>
                  </TableRow>
                ))}
                {f === 'tracker' && family(f).map((r: any) => (
                  <TableRow key={`${r.id}-sync`}>
                    {/* Pulling tickets in is the front door of the factory */}
                    <TableCell colSpan={4}><SyncPanel integ={r} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent></Card>
      ))}
    </section>
  )
}

const FAMILY_LABEL: Record<string, string> = {
  model: 'Models', forge: 'Code hosts', tracker: 'Trackers',
}

/**
 * Intake — where this tracker's tickets land, and whether they run by
 * themselves.
 *
 * Three doors, one destination: pull them in now (Sync), let the tracker push
 * them the moment they are filed (the webhook URL), or type one by hand on the
 * Work screen. Autostart applies to all of them, so a ticket behaves the same
 * way however it arrived.
 */
function SyncPanel({ integ }: any) {
  const [repos, setRepos] = useState<any[]>([])
  const [repo, setRepo] = useState('')
  const [cfg, setCfg] = useState<any>(null)
  const [secret, setSecret] = useState('')

  useEffect(() => {
    api('/repositories').then(setRepos).catch(() => {})
    api(`/integrations/${integ.id}/intake`).then((c) => {
      setCfg(c); setRepo(c.repo_id ?? '')
    }).catch(() => {})
  }, [integ.id])

  const put = (body: any) =>
    api(`/integrations/${integ.id}/intake`, { method: 'PUT', body: JSON.stringify(body) })
      .then((c) => { setCfg(c); if (c.secret) setSecret(c.secret); return c })

  const save = () => put({ repo_id: repo })
    .then(() => toast.success('Intake saved')).catch(fail)
  const toggleAuto = () => put({ repo_id: repo, autostart: !cfg?.autostart })
    .then((c) => toast.success(c.autostart ? 'Tickets will start a run' : 'Tickets will wait for a person'))
    .catch(fail)
  const rotate = () => put({ rotate_secret: true })
    .then(() => toast.success('New secret — copy it now, it is not shown again')).catch(fail)
  const sync = () => post(`/integrations/${integ.id}/sync`, { repo_id: repo })
    .then((r) => toast.success(
      `Synced: ${r.created} new, ${r.skipped} skipped${r.runs?.length ? `, ${r.runs.length} started` : ''}`))
    .catch(fail)

  return (
    <div className="intake-panel">
      <div className="work-actions">
        <Select value={repo} onValueChange={(v) => setRepo(v ?? '')}>
          <SelectTrigger className="field"><SelectValue placeholder="into repo…" /></SelectTrigger>
          <SelectContent>{repos.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
        </Select>
        <Button size="sm" onClick={sync} disabled={!repo}>Sync issues</Button>
        <Button size="sm" variant="outline" onClick={save} disabled={!repo}>Save intake</Button>
        <Button size="sm" variant={cfg?.autostart ? 'default' : 'outline'} onClick={toggleAuto}
          disabled={!repo}>
          {cfg?.autostart ? 'Autostart on' : 'Autostart off'}
        </Button>
      </div>
      {cfg && (
        <p className="muted">
          Webhook: <code className="mono">{cfg.url}</code>{' '}
          <Button size="sm" variant="ghost" onClick={rotate}>
            {cfg.has_secret ? 'Rotate secret' : 'Create secret'}
          </Button>
          {!cfg.has_secret && ' — a delivery without a secret is refused.'}
        </p>
      )}
      {secret && (
        <p className="muted">
          Signing secret (shown once): <code className="mono">{secret}</code>
        </p>
      )}
    </div>
  )
}

// A labeled field: a small uppercase label above its control, so the policy
// form reads left-to-right in the same order a person would state the rule.
export function Field({ label, children }: { label: string; children: any }) {
  return <div className="field-group"><span className="field-label">{label}</span>{children}</div>
}

// Read a rule policy back as a plain, well-qualified sentence.
export function ruleSentence(p: any): string {
  const who = !p.role || p.role === '*' ? 'Anyone' : `The ${p.role} role`
  const verb = p.effect === 'deny' ? 'may not' : 'may'
  const act = !p.action || p.action === '*' ? 'perform any action' : p.action
  const on = p.resource && p.resource !== '*' ? ` on ${p.resource}` : ''
  const where = p.namespace ? ` in the ${p.namespace} namespace` : ' anywhere'
  return `${who} ${verb} ${act}${on}${where}.`
}

const POLICY_ACTIONS = ['transition', 'tool', 'command', 'egress', '*']
const LAYER_HINT: Record<string, string> = {
  factory: 'factory · org-wide service', harness: 'harness · agent tooling', charter: 'charter · repo/project',
}

// Read-only governance view for developers: the rules that actually apply to
// them, in plain language. No authoring — legibility, not control.
// The ladder. Six rungs, and a rung is a PLACE rather than a strictness: rung 3
// sees a call and never a diff, rung 4 sees a diff and never the call. Which is
// why a rule that matters names both, and why this screen leads with what each
// rung can see rather than with a list of rules.
const LAYERS = ['code', 'harness', 'factory', 'charter']

// One place for "the rules". There were three — Standards (packs), Policies,
// and My rules — none of which mentioned the ladder, which is the idea the
// other three are instances of. The ladder leads; the rest are tabs behind it.
export function Rules({ me, roles }: any) {
  const [tab, setTab] = useState('ladder')
  const canPolicies = (me?.permissions ?? []).some(
    (p: string) => p === 'approve:charter' || p === 'see:operations')
  return (
    <section className="page">
      <h2 className="page-title">Rules</h2>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="ladder">The ladder</TabsTrigger>
          <TabsTrigger value="mine">What applies to me</TabsTrigger>
          <TabsTrigger value="standards">Standards</TabsTrigger>
          {canPolicies && <TabsTrigger value="policies">Policies</TabsTrigger>}
        </TabsList>
        <TabsContent value="ladder"><Ladder me={me} /></TabsContent>
        <TabsContent value="mine"><MyRules me={me} /></TabsContent>
        <TabsContent value="standards"><Packs me={me} roles={roles} /></TabsContent>
        {canPolicies && <TabsContent value="policies"><Policies /></TabsContent>}
      </Tabs>
    </section>
  )
}

export function Ladder({ me }: { me: any }) {
  const [v, setV] = useState<any>(null)
  const load = () => api('/ladder').then(setV).catch(fail)
  useEffect(() => { load() }, [])

  const [text, setText] = useState(''), [layer, setLayer] = useState('code')
  const [rung, setRung] = useState('0'), [side, setSide] = useState('constraint')
  const [predicate, setPredicate] = useState(''), [scope, setScope] = useState('*')
  const [withholds, setWithholds] = useState('')

  const mayApprove = (l: string) => (me?.permissions ?? []).includes(`approve:${l}`)
  const add = () => post('/ladder', {
    text, layer, rung: Number(rung) || 0, side, predicate, scope,
    withholds: withholds.split(',').map((w) => w.trim()).filter(Boolean),
  }).then(() => { setText(''); setWithholds(''); load(); toast.success('On the ladder') }).catch(fail)

  // moving a rule — the preview is pure, so asking what it would take is free
  const [moving, setMoving] = useState<any>(null)
  const [to, setTo] = useState('0'), [plan, setPlan] = useState<any>(null)
  const [movePred, setMovePred] = useState(''), [signer, setSigner] = useState('')
  const openMove = (r: any) => { setMoving(r); setTo(String(r.rung)); setPlan(null); setMovePred(r.predicate ?? ''); setSigner('') }
  const preview = (rungTo: string) => {
    setTo(rungTo)
    api(`/ladder/${moving.id}/move?to=${Number(rungTo) || 0}`).then(setPlan).catch(fail)
  }
  const doMove = () => post(`/ladder/${moving.id}/move`, {
    to: Number(to) || 0, predicate: movePred, second_signer: signer,
  }).then(() => { setMoving(null); load(); toast.success('Moved') }).catch(fail)

  if (!v) return null
  const rules = [...(v.constraints ?? []), ...(v.capabilities ?? [])]
  const onRung = (n: number) => rules.filter((r: any) => r.rung === n && r.enabled)

  return (
    <div className="space-y-3">
      <p className="muted">
        Where a rule is <em>carried</em>. “Money is Decimal” in a markdown file is
        rung&nbsp;0, and prose is a request; the same sentence as a predicate that
        refuses the write is a guarantee. <strong>A rung is a place, not a
        strictness</strong> — rung&nbsp;3 sees a call and never a diff, rung&nbsp;4
        sees a diff and never the call, so a rule that matters names both.
      </p>

      {(v.rungs ?? []).map((r: any) => {
        const here = onRung(r.rung)
        return (
          <Card key={r.rung} className={r.ours ? '' : 'muted-card'}>
            <CardHeader>
              <CardTitle>
                rung {r.rung} · {r.sees}
                {!r.ours && <> <Badge variant="outline">not ours</Badge></>}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {!r.ours && (
                <p className="muted">
                  {r.rung === 2
                    ? 'The target repository’s own commit hook carries this one.'
                    : 'CI carries this one — after everybody has left, which is the wrong place for anything catchable earlier.'}
                </p>
              )}
              {here.length === 0
                ? <span className="muted">nothing here</span>
                : here.map((rule: any) => (
                    <div key={rule.id} className="work-head">
                      <Badge variant={rule.mechanical ? 'default' : 'secondary'}>
                        {rule.mechanical ? 'enforced' : 'asks'}
                      </Badge>
                      <Badge variant="outline">{rule.layer}</Badge>
                      <span>{rule.text}</span>
                      {rule.predicate && <span className="mono muted">{rule.predicate}</span>}
                      {rule.withholds?.length > 0 && <span className="mono muted">−{rule.withholds.join(' −')}</span>}
                      {mayApprove(rule.layer) && (
                        <Button variant="outline" size="sm" onClick={() => openMove(rule)}>Move</Button>
                      )}
                    </div>
                  ))}
            </CardContent>
          </Card>
        )
      })}

      <Card>
        <CardHeader><CardTitle>The net tool grant</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">
            Rung 1 is subtraction: what a phase is never given, it cannot misuse.
            This is what every rule at rung 1 withholds, together.
          </p>
          <div className="toolbar">
            {(v.withheld ?? []).length
              ? v.withheld.map((w: string) => <Badge key={w} variant="destructive">{w}</Badge>)
              : <span className="muted">nothing is withheld</span>}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Predicates a rule can be made mechanical with</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">
            Rungs 2, 3 and 4 need code. A rule outside this set stays at rung 0
            until somebody writes one — which is the honest answer, because
            storing it at a rung nothing enforces would make it <em>look</em> protected.
          </p>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Name</TableHead><TableHead>Sees</TableHead><TableHead>About</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!(v.predicates ?? []).length} cols={3}>none registered</EmptyRow>
              {(v.predicates ?? []).map((pr: any) => (
                <TableRow key={pr.name}>
                  <TableCell className="mono">{pr.name}</TableCell>
                  <TableCell><Badge variant="outline">{pr.sees}</Badge></TableCell>
                  <TableCell className="muted">{pr.about}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Put a rule on the ladder</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">Adding one needs <span className="mono">approve:</span>the layer it is about.</p>
          <div className="field-form">
            <Field label="Rule"><Input className="field" style={{ width: '22rem' }} placeholder="money is Decimal"
              value={text} onChange={(e) => setText(e.target.value)} /></Field>
            <Field label="Side">
              <Select value={side} onValueChange={(x) => setSide(x ?? 'constraint')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="constraint">constraint (withholds)</SelectItem>
                  <SelectItem value="capability">capability (grants)</SelectItem>
                </SelectContent>
              </Select>
            </Field>
            <Field label="Layer">
              <Select value={layer} onValueChange={(x) => setLayer(x ?? 'code')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{LAYERS.map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Rung">
              <Select value={rung} onValueChange={(x) => setRung(x ?? '0')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(v.rungs ?? []).filter((r: any) => r.ours).map((r: any) =>
                    <SelectItem key={r.rung} value={String(r.rung)}>{r.rung}</SelectItem>)}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Predicate">
              <Select value={predicate} onValueChange={(x) => setPredicate(x ?? '')}>
                <SelectTrigger className="field"><SelectValue placeholder="none" /></SelectTrigger>
                <SelectContent>{(v.predicates ?? []).map((pr: any) =>
                  <SelectItem key={pr.name} value={pr.name}>{pr.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Withholds"><Input className="field" placeholder="execute, write_file"
              value={withholds} onChange={(e) => setWithholds(e.target.value)} /></Field>
            <Field label="Scope"><Input className="field" value={scope}
              onChange={(e) => setScope(e.target.value)} /></Field>
            <Button onClick={add} disabled={!text || !mayApprove(layer)}>Add</Button>
          </div>
        </CardContent>
      </Card>

      <Drawer open={!!moving} title={moving?.text ?? ''} onClose={() => setMoving(null)}>
        <div className="space-y-3">
          <p className="muted">
            Promotion and demotion are not symmetric, and that asymmetry is the
            safety property. A promotion adds enforcement. A <strong>demotion
            removes</strong> it, so it needs a second signer and the factory never
            performs one itself.
          </p>
          <Field label="Carry it at">
            <Select value={to} onValueChange={(x) => preview(x ?? '0')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>
                {(v.rungs ?? []).filter((r: any) => r.ours).map((r: any) =>
                  <SelectItem key={r.rung} value={String(r.rung)}>rung {r.rung} — {r.sees}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          {plan && (
            <Card>
              <CardContent>
                <div className="kv-row"><span>Direction</span>
                  <b><Badge variant={plan.direction === 'demotion' ? 'destructive' : 'secondary'}>{plan.direction}</Badge></b></div>
                <div className="kv-row"><span>It would see</span><b>{plan.sees}</b></div>
                {plan.needs_predicate && (
                  <Field label="Predicate (required at this rung)">
                    <Select value={movePred} onValueChange={(x) => setMovePred(x ?? '')}>
                      <SelectTrigger className="field"><SelectValue placeholder="pick one" /></SelectTrigger>
                      <SelectContent>{(v.predicates ?? []).map((pr: any) =>
                        <SelectItem key={pr.name} value={pr.name}>{pr.name}</SelectItem>)}</SelectContent>
                    </Select>
                  </Field>
                )}
                {plan.needs_second_signer && (
                  <Field label="Second signer (email)">
                    <Input className="field" placeholder="somebody who holds approve for this layer"
                      value={signer} onChange={(e) => setSigner(e.target.value)} />
                  </Field>
                )}
              </CardContent>
            </Card>
          )}
          <Button onClick={doMove} disabled={!plan}>Move it</Button>
        </div>
      </Drawer>
    </div>
  )
}

export function MyRules({ me }: { me: any }) {
  const { rows } = useList('/policies')
  const applies = rows.filter((p: any) => p.kind === 'rule' && (p.role === '*' || p.role === me.role))
  const denies = applies.filter((p: any) => p.effect === 'deny')
  const allows = applies.filter((p: any) => p.effect === 'allow')
  const Section = ({ title, items, tone }: any) => (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardContent>
        {items.length === 0
          ? <p className="muted">Nothing here.</p>
          : items.map((p: any) => (
              <div key={p.id} className="policy-sentence" style={{ padding: '.25rem 0' }}>
                <Badge variant={tone}>{p.effect}</Badge> {ruleSentence(p)}
                {p.strict && <> <Badge>locked</Badge></>}
              </div>
            ))}
      </CardContent>
    </Card>
  )
  return (
    <div className="space-y-3">
      <p className="muted">
        The rules in effect for your role ({me.role}). Read-only — putting one on
        the ladder needs <span className="mono">approve:</span>the layer it is about.
      </p>
      <Section title="What I may not do" items={denies} tone="destructive" />
      <Section title="What I'm explicitly allowed" items={allows} tone="secondary" />
    </div>
  )
}

function Policies() {
  const { rows, load } = useList('/policies')
  const { rows: roles } = useList('/roles')
  const [kind, setKind] = useState('rule')
  const [effect, setEffect] = useState('deny'), [role, setRole] = useState('*')
  const [action, setAction] = useState('transition'), [resource, setResource] = useState('*')
  const [strict, setStrict] = useState(false), [content, setContent] = useState('')
  const [layer, setLayer] = useState('charter'), [namespace, setNamespace] = useState('')
  const [note, setNote] = useState('')
  const add = () => post('/policies', { kind, effect, role, action, resource, strict, content, layer, namespace, note })
    .then(() => { setNote(''); load() }).catch(fail)
  const del = (id: string) => api(`/policies/${id}`, { method: 'DELETE' }).then(load).catch(fail)

  const [text, setText] = useState(''), [scan, setScan] = useState<any>(null)
  const [egress, setEgress] = useState(false)
  const runScan = () => post('/content/scan', { text, egress }).then(setScan).catch(fail)

  // versioned history + point-in-time reconstruction
  const [hist, setHist] = useState<any[] | null>(null)
  const [at, setAt] = useState(''), [effective, setEffective] = useState<any[] | null>(null)
  const openHist = () => api('/policies/history').then((h) => setHist(h)).catch(fail)
  const showAt = () => at && api(`/policies/at?t=${encodeURIComponent(new Date(at).toISOString())}`)
    .then(setEffective).catch(fail)

  return (
    <div className="space-y-3">
      <p className="muted">
        Role-keyed allow/deny artifacts, evaluated by <span className="mono">policies.enforce</span>.
        These are a different mechanism from the ladder: a policy gates an
        <em> action name</em>, a rung carries a rule at a <em>place</em>.
      </p>
      <Card>
        <CardHeader><CardTitle>Add a governed artifact (rule / skill / command / agent)</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">A <strong>rule</strong> states who may (or may not) do what, and where. Fill the fields left to right — the preview reads it back as a sentence before you add it.</p>
          <div className="field-form">
            <Field label="Type">
              <Select value={kind} onValueChange={(v) => setKind(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{['rule', 'skill', 'command', 'agent'].map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            {kind === 'rule' ? (
              <>
                <Field label="Effect">
                  <Select value={effect} onValueChange={(v) => setEffect(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>{['deny', 'allow'].map((e) => <SelectItem key={e} value={e}>{e === 'deny' ? 'Deny' : 'Allow'}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field label="Who (role)">
                  <Select value={role} onValueChange={(v) => setRole(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="*">any role</SelectItem>
                      {roles.map((r: any) => <SelectItem key={r.name} value={r.name}>{r.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Action">
                  <Input className="field" list="policy-actions" placeholder="* = any action" value={action} onChange={(e) => setAction(e.target.value)} />
                  <datalist id="policy-actions">{POLICY_ACTIONS.map((a) => <option key={a} value={a} />)}</datalist>
                </Field>
                <Field label="On (resource)">
                  <Input className="field" placeholder="* = anything" value={resource} onChange={(e) => setResource(e.target.value)} />
                </Field>
                <Field label="Where (namespace)">
                  <Input className="field" placeholder="blank = everywhere" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
                </Field>
                <Field label="Layer">
                  <Select value={layer} onValueChange={(v) => setLayer(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>{['factory', 'harness', 'charter'].map((l) => <SelectItem key={l} value={l}>{LAYER_HINT[l]}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field label="Lock">
                  <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', height: '2.25rem' }}>
                    <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} />
                    no lower layer can override
                  </label>
                </Field>
              </>
            ) : (
              <Field label={`${kind} content`}>
                <Input className="field" style={{ width: '20rem' }} placeholder={`what this ${kind} says`} value={content} onChange={(e) => setContent(e.target.value)} />
              </Field>
            )}
            <Field label="Reason (optional)">
              <Input className="field" placeholder="why — recorded in history" value={note} onChange={(e) => setNote(e.target.value)} />
            </Field>
            <Button onClick={add}>Add {kind}</Button>
            <Button variant="outline" onClick={openHist}>History</Button>
          </div>
          {kind === 'rule' && (
            <div className="policy-preview">
              <span className="policy-sentence">{ruleSentence({ effect, role, action, resource, namespace })}</span>
              {' '}
              <Badge variant="outline">{layer} layer</Badge>
              {strict && <> <Badge>locked</Badge></>}
            </div>
          )}
          <Table>
            <TableHeader><TableRow><TableHead>Type</TableHead><TableHead>Rule</TableHead><TableHead>Layer</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody><EmptyRow show={!rows.length} cols={4}>Nothing here yet.</EmptyRow>{rows.map((p) => (
              <TableRow key={p.id}>
                <TableCell><Badge variant="outline">{p.kind}</Badge></TableCell>
                <TableCell>
                  {p.kind === 'rule'
                    ? <span className="policy-sentence"><Badge variant={p.effect === 'deny' ? 'destructive' : 'secondary'}>{p.effect}</Badge> {ruleSentence(p)}</span>
                    : <span className="mono">{p.content}</span>}
                </TableCell>
                <TableCell>{p.layer} {p.strict && <Badge>locked</Badge>}</TableCell>
                <TableCell><Button variant="outline" size="sm" onClick={() => del(p.id)}>Delete</Button></TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Content filter — test redaction</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">
            Two questions, not one. <strong>In a run</strong> the filter asks only
            “is this a credential” — a tool call carrying one is refused, and an email
            address in a CODEOWNERS file is the file working. <strong>Leaving</strong>{' '}
            adds personal data, because a pull request body goes to a third party.
          </p>
          <div className="toolbar">
            <Input className="field" placeholder="text to check" value={text} onChange={(e) => setText(e.target.value)} />
            <Toggle on={egress} onChange={setEgress} label="leaving this machine" />
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

      <Drawer open={hist !== null} title="Policy history" onClose={() => { setHist(null); setEffective(null) }}>
        <div className="space-y-3">
          <div className="field-form">
            <Field label="Rules in effect at">
              <Input className="field" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} />
            </Field>
            <Button variant="secondary" size="sm" onClick={showAt} disabled={!at}>Show</Button>
          </div>
          {effective && (
            <div className="policy-preview">
              <div className="field-label">{effective.length} rule(s) in effect</div>
              {effective.map((p: any) => (
                <div key={p.policy_id} className="policy-sentence"><Badge variant={p.effect === 'deny' ? 'destructive' : 'secondary'}>{p.effect}</Badge> {ruleSentence(p)}</div>
              ))}
              {!effective.length && <span className="muted">no rules in effect then</span>}
            </div>
          )}
          <div className="field-label">Change log</div>
          {(hist ?? []).map((v: any) => (
            <div key={v.id} className="kv-row" style={{ alignItems: 'flex-start' }}>
              <span className="policy-sentence">
                <Badge variant={v.change === 'deleted' ? 'destructive' : v.change === 'created' ? 'default' : 'secondary'}>{v.change}</Badge>{' '}
                {ruleSentence(v)}{v.note && <span className="muted"> — “{v.note}”</span>}
              </span>
              <span className="mono">{v.created_at?.slice(0, 19)}</span>
            </div>
          ))}
          {hist !== null && !hist.length && <span className="muted">No changes recorded yet.</span>}
        </div>
      </Drawer>
    </div>
  )
}

const SETTING_HINTS = [
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
          <div className="field-form">
            <Field label="Key"><Input className="field" placeholder="e.g. policy.enforcement" value={key}
                   list="setting-hints" onChange={(e) => setKey(e.target.value)} /></Field>
            <datalist id="setting-hints">{SETTING_HINTS.map((h) => <option key={h} value={h} />)}</datalist>
            <Field label="Value"><Input className="field" placeholder="stored encrypted" type="password" value={value}
                   onChange={(e) => setValue(e.target.value)} /></Field>
            <Button onClick={save} disabled={!key}>Save</Button>
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
      <Notifications />
      <Webhooks />
    </section>
  )
}

const ALERT_RECIPES = ['', 'denied', 'policy-change', 'approval-overdue', 'approval', 'run-held', 'run-error', 'pr-opened']

function Notifications() {
  const { rows, load } = useList('/notification-rules')
  const [label, setLabel] = useState(''), [recipe, setRecipe] = useState('denied')
  const [channel, setChannel] = useState('slack'), [target, setTarget] = useState('')
  const add = () => post('/notification-rules', { label, recipe: recipe === 'any' ? '' : recipe, channel, target })
    .then(() => { setLabel(''); setTarget(''); load(); toast.success('Rule added') }).catch(fail)
  const del = (id: string) => api(`/notification-rules/${id}`, { method: 'DELETE' }).then(load).catch(fail)
  return (
    <Card>
      <CardHeader><CardTitle>Notifications — alert on governance events</CardTitle></CardHeader>
      <CardContent>
        <p className="muted">Turn the audit stream into signals: pick an event (blank = any) and where to send it — a Slack incoming webhook, an email, or a plain webhook.</p>
        <div className="field-form">
          <Field label="Label"><Input className="field" placeholder="e.g. denials → #security" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
          <Field label="On event">
            <Select value={recipe} onValueChange={(v) => setRecipe(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{ALERT_RECIPES.map((r) => <SelectItem key={r || 'any'} value={r || 'any'}>{r || 'any event'}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label="Channel">
            <Select value={channel} onValueChange={(v) => setChannel(v ?? '')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>{['slack', 'email', 'webhook'].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
            </Select>
          </Field>
          <Field label={channel === 'email' ? 'Email' : 'URL'}><Input className="field" style={{ width: '20rem' }} placeholder={channel === 'email' ? 'sec@acme.com' : 'https://hooks.slack.com/…'} value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
          <Button onClick={add} disabled={!label || !target}>Add rule</Button>
        </div>
        <Table>
          <TableHeader><TableRow><TableHead>Rule</TableHead><TableHead>On</TableHead><TableHead>Channel</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody><EmptyRow show={!rows.length} cols={4}>No notification rules yet.</EmptyRow>{rows.map((r: any) => (
            <TableRow key={r.id}>
              <TableCell>{r.label}</TableCell>
              <TableCell><Badge variant="secondary">{r.recipe || 'any'}</Badge></TableCell>
              <TableCell className="mono">{r.channel}</TableCell>
              <TableCell><Button variant="outline" size="sm" onClick={() => del(r.id)}>Delete</Button></TableCell>
            </TableRow>
          ))}</TableBody>
        </Table>
      </CardContent>
    </Card>
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
          <div className="field-form">
            <Field label="Name"><Input className="field" placeholder="e.g. terser prompt" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Layer">
              <Select value={layer} onValueChange={(v) => setLayer(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{['project', 'platform', 'harness', 'charter'].map((l) => <SelectItem key={l} value={l}>{l}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Hypothesis"><Input className="field" placeholder="we believe X will improve Y" value={hyp} onChange={(e) => setHyp(e.target.value)} /></Field>
            <Field label="Change under test"><Input className="field" placeholder="what you're changing" value={change} onChange={(e) => setChange(e.target.value)} /></Field>
            <Button onClick={create} disabled={!name}>Create experiment</Button>
          </div>
          <Table>
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Layer</TableHead><TableHead>Hypothesis</TableHead><TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody><EmptyRow show={!rows.length} cols={5}>No experiments yet — state a hypothesis above.</EmptyRow>{rows.map((e: any) => (
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
            <div className="field-form">
              <Field label="Phase">
                <Select value={phase} onValueChange={(v) => setPhase(v ?? '')}>
                  <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                  <SelectContent>{['before', 'after'].map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Metric"><Input className="field" placeholder="e.g. score" value={metric} onChange={(e) => setMetric(e.target.value)} /></Field>
              <Field label="Samples"><Input className="field" placeholder="comma numbers: 0.8, 0.9" value={samples} onChange={(e) => setSamples(e.target.value)} /></Field>
              <Field label="Round"><Input className="field" type="number" placeholder="1" value={round} onChange={(e) => setRound(e.target.value)} /></Field>
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
  const [tier, setTier] = useState(''), [effect, setEffect] = useState('deny')
  const [pRole, setPRole] = useState('*')
  const [pAction, setPAction] = useState('invoke'), [resource, setResource] = useState('*')
  const [pNamespace, setPNamespace] = useState('')
  const [strict, setStrict] = useState(false), [idea, setIdea] = useState('')
  useEffect(() => { if (!tier && roleNames.length) setTier(roleNames[0]) }, [roleNames, tier])
  const propose = () => post('/proposals', pkind === 'suggestion'
    ? { target_kind: 'suggestion', action: 'adopt', layer: tier, payload: { text: idea } }
    : { target_kind: 'policy', action: 'create', layer: tier,
        payload: { effect, role: pRole, action: pAction, resource, namespace: pNamespace, strict, kind: 'rule' } })
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
          <CardHeader><CardTitle>Approval workflows (admin)</CardTitle></CardHeader>
          <CardContent>
            <p className="muted">For each governance <strong>tier</strong> (a role), set the ordered chain of roles that must sign off on a change to it — a distinct signer per slot. No workflow set → a change cascades up the role ladder.</p>
            <div className="field-form">
              <Field label="Tier (role)">
                <Select value={wfLayer} onValueChange={(v) => setWfLayer(v ?? '')}>
                  <SelectTrigger className="field"><SelectValue placeholder="role…" /></SelectTrigger>
                  <SelectContent>{roleNames.map((r: string) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                </Select>
              </Field>
              <Field label="Approval chain (roles, in order)">
                <Input className="field" style={{ width: '20rem' }} placeholder="e.g. platform, admin" value={wfChain} onChange={(e) => setWfChain(e.target.value)} />
              </Field>
              <Button onClick={saveWf}>Save workflow</Button>
            </div>
            <Table>
              <TableHeader><TableRow><TableHead>Tier</TableHead><TableHead>Must be approved by</TableHead></TableRow></TableHeader>
              <TableBody><EmptyRow show={!wfRows.length} cols={2}>No workflows — changes cascade up the ladder by default.</EmptyRow>{wfRows.map((w: any) => (
                <TableRow key={w.layer}><TableCell>{w.layer}</TableCell><TableCell className="mono">{(w.chain || []).join(' → ')}</TableCell></TableRow>
              ))}</TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Propose a change</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">Propose a <strong>policy rule</strong> (fill it in like a statement — the preview reads it back), or a free-text <strong>suggestion</strong>. It then walks the review tier's approval chain.</p>
          <div className="field-form">
            <Field label="Proposal">
              <Select value={pkind} onValueChange={(v) => setPkind(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="policy">policy rule</SelectItem><SelectItem value="suggestion">suggestion</SelectItem></SelectContent>
              </Select>
            </Field>
            {pkind === 'policy' ? (
              <>
                <Field label="Effect">
                  <Select value={effect} onValueChange={(v) => setEffect(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>{['deny', 'allow'].map((e) => <SelectItem key={e} value={e}>{e === 'deny' ? 'Deny' : 'Allow'}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field label="Who (role)">
                  <Select value={pRole} onValueChange={(v) => setPRole(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="*">any role</SelectItem>
                      {roleNames.map((r: string) => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Action">
                  <Input className="field" list="policy-actions" placeholder="* = any action" value={pAction} onChange={(e) => setPAction(e.target.value)} />
                </Field>
                <Field label="On (resource)">
                  <Input className="field" placeholder="* = anything" value={resource} onChange={(e) => setResource(e.target.value)} />
                </Field>
                <Field label="Where (namespace)">
                  <Input className="field" placeholder="blank = everywhere" value={pNamespace} onChange={(e) => setPNamespace(e.target.value)} />
                </Field>
                <Field label="Lock">
                  <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', height: '2.25rem' }}>
                    <input type="checkbox" checked={strict} onChange={(e) => setStrict(e.target.checked)} /> no lower layer overrides
                  </label>
                </Field>
              </>
            ) : (
              <Field label="Your idea">
                <Input className="field" style={{ width: '24rem' }} placeholder="what should change (escalates up the ladder)" value={idea} onChange={(e) => setIdea(e.target.value)} />
              </Field>
            )}
            <Field label="Review tier (role)">
              <Select value={tier} onValueChange={(v) => setTier(v ?? '')}>
                <SelectTrigger className="field"><SelectValue placeholder="role…" /></SelectTrigger>
                <SelectContent>{roleNames.map((r: string) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Button onClick={propose} disabled={pkind === 'suggestion' && !idea}>Propose</Button>
          </div>
          {pkind === 'policy' && (
            <div className="policy-preview">
              <span className="policy-sentence">{ruleSentence({ effect, role: pRole, action: pAction, resource, namespace: pNamespace })}</span>
              {strict && <> <Badge>locked</Badge></>}
              {' '}<span className="muted">— reviewed by the {tier} tier{'’'}s chain.</span>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Proposed change</TableHead><TableHead>Review tier</TableHead><TableHead>Progress</TableHead>
              <TableHead>Status</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody><EmptyRow show={!rows.length} cols={5}>No proposals yet — propose a change above.</EmptyRow>{rows.map((p: any) => (
              <TableRow key={p.id}>
                <TableCell>{p.target_kind === 'suggestion'
                  ? <span><Badge variant="outline">suggestion</Badge> {p.payload?.text ?? ''}</span>
                  : <span className="policy-sentence"><Badge variant={p.payload?.effect === 'deny' ? 'destructive' : 'secondary'}>{p.payload?.effect}</Badge> {ruleSentence(p.payload || {})}{p.payload?.strict ? ' (locked)' : ''}</span>}</TableCell>
                <TableCell>{p.layer}</TableCell>
                <TableCell><Pipeline stages={p.chain || []} current={p.status === 'pending' ? (p.chain || [])[p.current] : undefined} /></TableCell>
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

export function Packs({ me, roles }: any) {
  const { rows, load } = useList('/packs')
  const rank = (r: string) => roles.find((x: Role) => x.name === r)?.rank ?? 0
  const canManage = (packRole: string) => rank(me.role) >= rank(packRole)
  const toggle = (p: any) =>
    api(`/packs/${p.key}/${p.enabled ? 'disable' : 'enable'}`, { method: 'POST' })
      .then(load).catch(fail)
  const [detail, setDetail] = useState<any>(null)
  const openDetail = (key: string) => api(`/packs/${key}`).then(setDetail).catch(fail)

  const layers = Array.from(new Set(rows.map((p: any) => p.role)))
    .sort((a: any, b: any) => rank(a) - rank(b))
  const enabledCount = rows.filter((p: any) => p.enabled).length

  return (
    <div className="space-y-3">
      <p className="muted">
        Browse starter bundles of standards & governed artifacts — the modern software / platform / team-workflow
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
                    <Button variant="ghost" size="sm" onClick={() => openDetail(p.key)}>View details</Button>
                    <span className="app-spacer" />
                    <div className="switch-row">
                      <span className="muted">{p.enabled ? 'on' : 'off'}</span>
                      <Toggle on={p.enabled} disabled={!canManage(p.role)}
                              label={`enable ${p.title}`} onChange={() => toggle(p)} />
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ))}

      <Drawer open={!!detail} title={detail?.title ?? ''} onClose={() => setDetail(null)}>
        {detail && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div><Badge variant="secondary">{detail.role}</Badge>{detail.enabled && <> <Badge>enabled</Badge></>}
              <p className="muted" style={{ marginTop: '.4rem' }}>{detail.description}</p></div>

            {detail.standards.length > 0 && <div>
              <div className="field-label">Standards it seeds</div>
              {detail.standards.map((s: any, i: number) => (
                <div key={i} style={{ marginTop: '.5rem' }}>
                  <div><Badge variant="outline">{s.topic}</Badge> <strong>{s.title}</strong></div>
                  <p className="muted" style={{ margin: '.2rem 0 0' }}>{s.body}</p>
                </div>
              ))}
            </div>}

            {detail.artifacts.length > 0 && <div>
              <div className="field-label">Governed artifacts</div>
              {detail.artifacts.map((a: any, i: number) => (
                <div key={i} className="policy-sentence" style={{ marginTop: '.3rem' }}>
                  <Badge variant="outline">{a.kind}</Badge>{' '}
                  {a.kind === 'rule' ? ruleSentence(a) : a.content}
                </div>
              ))}
            </div>}

            {!detail.standards.length && !detail.artifacts.length &&
              <p className="muted">This pack has no seeded content.</p>}
          </div>
        )}
      </Drawer>
    </div>
  )
}

function Users({ me }: any) {
  // "Add the users, give them permissions" — one screen, and a preset is a
  // starting point rather than a role, which the copy says out loud.
  const { rows, load } = useList('/users')
  const [catalog, setCatalog] = useState<any>({ permissions: [], layers: [] })
  const [presets, setPresets] = useState<Role[]>([])
  const [email, setEmail] = useState(''), [password, setPassword] = useState('')
  const [preset, setPreset] = useState('developer')
  const [open, setOpen] = useState<any>(null)

  useEffect(() => {
    api('/permissions').then(setCatalog).catch(fail)
    api('/roles').then(setPresets).catch(() => {})
  }, [])

  const add = () => post('/users', { email, password, role: preset })
    .then((r) => {
      setEmail(''); setPassword('')
      toast.success(`Added ${r.user.email} — token shown once: ${r.token}`)
      load()
    }).catch(fail)

  return (
    <section className="page">
      <h2 className="page-title">Users</h2>
      <p className="muted">A person holds a set of permissions, and that set is what is checked.
        Presets are a starting point — editing one later does not change anybody already added.</p>

      <Card><CardHeader><CardTitle>Add someone</CardTitle></CardHeader><CardContent>
        <div className="field-form">
          <Field label="Email"><Input className="field" value={email} placeholder="dana@acme.io"
            onChange={(e) => setEmail(e.target.value)} /></Field>
          <Field label="Password"><Input className="field" type="password" value={password}
            onChange={(e) => setPassword(e.target.value)} /></Field>
          <Field label="Start from">
            <Select value={preset} onValueChange={(v) => setPreset(v ?? 'developer')}>
              <SelectTrigger className="field"><SelectValue /></SelectTrigger>
              <SelectContent>
                {presets.map((r) => <SelectItem key={r.name} value={r.name}>{r.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Button onClick={add} disabled={!email || !password}>Add</Button>
        </div>
      </CardContent></Card>

      <Card><CardContent>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Email</TableHead><TableHead>Started from</TableHead>
            <TableHead>Permissions</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            <EmptyRow show={!rows.length} cols={4}>Nobody yet.</EmptyRow>
            {rows.map((u: any) => (
              <TableRow key={u.id}>
                <TableCell>{u.email}</TableCell>
                <TableCell className="muted">{u.role}</TableCell>
                <TableCell className="muted">{(u.permissions ?? []).length} held</TableCell>
                <TableCell>
                  {u.id === me?.id
                    ? <span className="muted" title="Granting yourself more is the one thing this has to prevent">your own</span>
                    : <Button size="sm" variant="outline" onClick={() => setOpen(u)}>Permissions</Button>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent></Card>

      <PermissionEditor user={open} catalog={catalog} presets={presets}
        onClose={() => setOpen(null)} onSaved={load} />
    </section>
  )
}

function PermissionEditor({ user, catalog, presets, onClose, onSaved }: any) {
  const [held, setHeld] = useState<string[]>([])
  useEffect(() => { setHeld(user?.permissions ?? []) }, [user])
  if (!user) return null

  const toggle = (p: string) =>
    setHeld((h) => h.includes(p) ? h.filter((x) => x !== p) : [...h, p])
  const applyPreset = (name: string) => {
    const preset = presets.find((r: Role) => r.name === name) as any
    setHeld(preset?.permissions ?? [])
  }
  const save = () =>
    api(`/users/${user.id}/permissions`, { method: 'PUT', body: JSON.stringify({ permissions: held }) })
      .then(() => { toast.success('Saved'); onSaved?.(); onClose() }).catch(fail)

  return (
    <Drawer open={!!user} title={user.email} onClose={onClose}>
      <div className="space-y-3">
        <div className="toolbar">
          <span className="muted">Start from:</span>
          {presets.map((r: Role) => (
            <Button key={r.name} size="sm" variant="outline"
              onClick={() => applyPreset(r.name)}>{r.name}</Button>
          ))}
        </div>
        <div className="space-y-1">
          {(catalog.permissions ?? []).map((p: any) => (
            <label key={p.permission} className="perm-row">
              <input type="checkbox" checked={held.includes(p.permission)}
                onChange={() => toggle(p.permission)} />
              <span className="mono">{p.permission}</span>
              <span className="muted">{p.description}</span>
            </label>
          ))}
        </div>
        <p className="muted">{held.length} held. This set is what is checked — not the preset.</p>
        <Button onClick={save}>Save permissions</Button>
      </div>
    </Drawer>
  )
}

function Pipelines({ me }: any) {
  // The canvas IS the builder: what you draw is what gets saved, and saving
  // writes a new version rather than editing in place.
  const { rows, load } = useList('/pipelines')
  const [graph, setGraph] = useState<Graph | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [check, setCheck] = useState<any>(null)
  const [actions, setActions] = useState<any[]>([])
  const [templates, setTemplates] = useState<any[]>([])
  const canEdit = (me?.permissions ?? []).includes('approve:factory')

  useEffect(() => {
    api('/pipelines/actions').then(setActions).catch(() => {})
    api('/pipelines/templates').then(setTemplates).catch(() => {})
  }, [])

  // Validation is inline, not on save — an unreachable stage should show up
  // while you are drawing it, not when you press the button.
  useEffect(() => {
    if (!graph) return setCheck(null)
    const id = setTimeout(() => {
      post('/pipelines/validate', graph).then(setCheck).catch(() => {})
    }, 250)
    return () => clearTimeout(id)
  }, [graph])

  const openTemplate = (name: string) =>
    api(`/pipelines/templates/${name}`).then((g) => { setGraph(g); setSelected(null) }).catch(fail)
  const openSaved = (p: any) =>
    api(`/pipelines/${p.id}/export`)
      .then((g) => { setGraph({ ...g, layout: p.layout }); setSelected(null) }).catch(fail)

  const addStage = () => {
    if (!graph) return
    let name = 'new-stage', n = 1
    while (graph.stages[name]) name = `new-stage-${++n}`
    setGraph({ ...graph, stages: { ...graph.stages, [name]: { action: 'teardown', next: 'landed' } } })
    setSelected(name)
  }
  const removeStage = (name: string) => {
    if (!graph) return
    const { [name]: _drop, ...rest } = graph.stages
    setGraph({ ...graph, stages: rest })
    setSelected(null)
  }
  const save = () => {
    if (!graph) return
    post('/pipelines', graph)
      .then((r) => { toast.success(`Saved ${r.name} v${r.version}`); load() })
      .catch(fail)
  }

  if (!graph) {
    return (
      <section className="page">
        <h2 className="page-title">Workflows</h2>
        <p className="muted">How work ships here. Pick one to edit, or start from a template —
          each says what it gives up, because a template chosen without knowing that is a
          decision nobody made.</p>

        <Card><CardHeader><CardTitle>Yours</CardTitle></CardHeader><CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Name</TableHead><TableHead>Version</TableHead>
              <TableHead>Stages</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!rows.length} cols={4}>
                Nothing yet{canEdit ? ' — start from a template below.' : ' — ask whoever holds approve:factory.'}
              </EmptyRow>
              {rows.map((p: any) => (
                <TableRow key={p.id}>
                  <TableCell>{p.name}</TableCell>
                  <TableCell className="muted">v{p.version}</TableCell>
                  <TableCell className="muted">{Object.keys(p.stages ?? {}).length}</TableCell>
                  <TableCell>
                    <Button size="sm" variant="outline" onClick={() => openSaved(p)}>Open</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent></Card>

        <div className="template-grid">
          {templates.map((t: any) => (
            <Card key={t.name}>
              <CardHeader><CardTitle>{t.name}</CardTitle></CardHeader>
              <CardContent>
                <p>{t.about}</p>
                <p className="muted">{t.stages} stages</p>
                {t.gives_up && <p className="muted">Gives up: {t.gives_up}</p>}
                <Button size="sm" variant="outline" onClick={() => openTemplate(t.name)}>Open</Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    )
  }

  return (
    <section className="page canvas-page">
      <div className="canvas-bar">
        <Button variant="ghost" size="sm" onClick={() => { setGraph(null); setSelected(null) }}>← Workflows</Button>
        <Input className="field" value={graph.name}
          onChange={(e) => setGraph({ ...graph, name: e.target.value })} />
        <Input className="field" value={graph.model ?? ''} placeholder="default model"
          onChange={(e) => setGraph({ ...graph, model: e.target.value })} />
        {canEdit && <Button size="sm" variant="outline" onClick={addStage}>Add stage</Button>}
        {check && (check.ok
          ? <Badge variant="outline">{check.stages} stages · valid</Badge>
          : <Badge variant="destructive" title={check.error}>invalid</Badge>)}
        {canEdit && <Button size="sm" onClick={save} disabled={!check?.ok}>Save as new version</Button>}
      </div>
      {check && !check.ok && <p className="muted canvas-error">{check.error}</p>}
      {check?.ok && <p className="muted canvas-path">{(check.path ?? []).join('  →  ')}</p>}
      <div className="canvas-layout">
        <Canvas graph={graph} onChange={setGraph} onSelect={setSelected} selected={selected} />
        {selected && (
          <Inspector graph={graph} name={selected} actions={actions} phases={PHASES}
            onChange={setGraph} onDelete={() => removeStage(selected)} />
        )}
      </div>
    </section>
  )
}

// The phases a stage can run. A team adds one by writing its prompt; until the
// harness lands (Phase 5) these are the six the default pipelines use.
const PHASES = ['refine', 'plan', 'run', 'prove', 'review', 'security', 'improve']

/**
 * Runs as they happen.
 *
 * Merges what the server has with what the live channel says since. The list
 * is the truth on load; a websocket event updates the run it names and adds one
 * that is new, so a run started by a webhook appears without a refresh.
 */
function useLiveRuns(rows: any[]): LiveRun[] {
  const [moves, setMoves] = useState<Record<string, LiveRun>>({})

  useEffect(() => {
    const on = (e: any) => setMoves((m) => ({ ...m, [e.detail.id]: e.detail }))
    window.addEventListener('oref-run', on)
    return () => window.removeEventListener('oref-run', on)
  }, [])

  return useMemo(() => {
    const byId: Record<string, LiveRun> = {}
    for (const r of rows) byId[r.id] = { ...r }
    for (const [id, m] of Object.entries(moves)) byId[id] = { ...(byId[id] ?? {}), ...m }
    return Object.values(byId)
  }, [rows, moves])
}

function Runs({ me }: any) {
  const { rows, load } = useList('/runs')
  const { rows: items } = useList('/work-items')
  const [item, setItem] = useState('')
  const [live, setLive] = useState(false)
  const canRun = (me?.permissions ?? []).includes('run:factory')
  const runs = useLiveRuns(rows)

  const start = () => post('/runs', { work_item_id: item })
    .then(() => { toast.success('Run started'); load() }).catch(fail)
  const approve = (id: string) => post(`/runs/${id}/approve`, {})
    .then(() => { toast.success('Approved'); load() }).catch(fail)

  return (
    <section className="page">
      <h2 className="page-title">Runs</h2>
      <p className="muted">Work going through the factory. A run advances on the server, one stage
        at a time, and survives a restart.</p>
      <div className="canvas-bar">
        <Button size="sm" variant={live ? 'default' : 'outline'} onClick={() => setLive(!live)}>
          {live ? 'List' : 'Live canvas'}
        </Button>
        <span className="muted">
          {live ? 'The workflow you designed, with runs standing on it.' : ''}
        </span>
      </div>
      {live && <LiveCanvas runs={runs} onApprove={approve} />}
      {canRun && (
        <div className="field-form">
          <Field label="Work item">
            <Select value={item} onValueChange={(v) => setItem(v ?? '')}>
              <SelectTrigger className="field"><SelectValue placeholder="pick one" /></SelectTrigger>
              <SelectContent>
                {items.map((w: any) => <SelectItem key={w.id} value={w.id}>{w.title}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Button onClick={start} disabled={!item}>Run</Button>
        </div>
      )}
      {!live && <Card><CardContent>
        <Table>
          <TableHeader><TableRow>
            <TableHead>Run</TableHead><TableHead>Stage</TableHead><TableHead>Revisions</TableHead>
            <TableHead>Pull request</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody>
            <EmptyRow show={!runs.length} cols={5}>Nothing running yet.</EmptyRow>
            {runs.map((r: any) => (
              <TableRow key={r.id}>
                <TableCell className="mono">{r.id.slice(0, 8)}</TableCell>
                <TableCell>
                  {r.outcome
                    ? <Badge variant="outline">{r.outcome}</Badge>
                    : r.held ? <Badge>held</Badge> : r.stage}
                </TableCell>
                <TableCell className="muted">{r.revisions}</TableCell>
                <TableCell>
                  {r.pr_url ? <a href={r.pr_url} target="_blank" rel="noreferrer">open →</a> : '—'}
                </TableCell>
                <TableCell>
                  {r.held && <Button size="sm" variant="outline" onClick={() => approve(r.id)}>Approve</Button>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent></Card>}
    </section>
  )
}

/** The same graph as design mode, with the runs on it. */
function LiveCanvas({ runs, onApprove }: { runs: LiveRun[]; onApprove: (id: string) => void }) {
  const { rows: pipelines } = useList('/pipelines')
  const [name, setName] = useState('')
  const [graph, setGraph] = useState<Graph | null>(null)

  // Default to whichever workflow has runs on it — that is what somebody
  // opening this screen came to look at.
  const busiest = useMemo(() => {
    const count: Record<string, number> = {}
    for (const r of runs as any[]) if (r.pipeline_id) count[r.pipeline_id] = (count[r.pipeline_id] ?? 0) + 1
    const top = Object.entries(count).sort((a, b) => b[1] - a[1])[0]?.[0]
    return pipelines.find((p: any) => p.id === top)?.name ?? pipelines[0]?.name ?? ''
  }, [runs, pipelines])

  const shown = name || busiest
  const pipeline = useMemo(() =>
    pipelines.find((p: any) => p.name === shown), [pipelines, shown])

  useEffect(() => {
    if (!pipeline) return setGraph(null)
    api(`/pipelines/${pipeline.id}`).then(setGraph).catch(() => setGraph(null))
  }, [pipeline?.id])

  // Only this workflow's runs, or a run from another graph lands on a stage
  // that happens to share a name.
  const mine = useMemo(() =>
    (runs as any[]).filter((r) => !pipeline || r.pipeline_id === pipeline.id ||
      pipelines.some((p: any) => p.id === r.pipeline_id && p.name === shown)),
    [runs, pipeline, pipelines, shown])

  const active = mine.filter((r: any) => !r.outcome).length
  const held = mine.filter((r: any) => r.held).length

  if (!graph) return <p className="muted">No workflow to watch yet.</p>
  return (
    <>
      <div className="canvas-bar">
        <Select value={shown} onValueChange={(v) => setName(v ?? '')}>
          <SelectTrigger className="field"><SelectValue placeholder="workflow" /></SelectTrigger>
          <SelectContent>
            {pipelines.map((p: any) => <SelectItem key={p.id} value={p.name}>{p.name}</SelectItem>)}
          </SelectContent>
        </Select>
        <Badge variant="outline">{active} running</Badge>
        {held > 0 && <Badge>{held} waiting on a person</Badge>}
      </div>
      <div className="canvas-layout">
        <Canvas graph={graph} runs={mine} onApprove={onApprove}
          onSelect={() => {}} selected={null} />
      </div>
    </>
  )
}

function Teams() {
  const { rows, load } = useList('/teams')
  const { rows: users } = useList('/users')
  const [name, setName] = useState(''), [cap, setCap] = useState('0')
  const add = () => post('/teams', { name, max_concurrency: Number(cap) || 0 })
    .then(() => { setName(''); setCap('0'); load() }).catch(fail)
  const del = (id: string) => api(`/teams/${id}`, { method: 'DELETE' }).then(load).catch(fail)
  const assign = (userId: string, teamId: string) =>
    api(`/users/${userId}/team`, { method: 'PUT', body: JSON.stringify({ team_id: teamId || null }) })
      .then(() => toast.success('team updated')).catch(fail)
  const teamName = (id: string) => rows.find((t: any) => t.id === id)?.name ?? '—'

  return (
    <section className="page">
      <h2 className="page-title">Teams</h2>
      <p className="muted">Group users for cost attribution and live concurrency caps (0 = unlimited concurrent invokes).</p>
      <Card>
        <CardHeader><CardTitle>New team</CardTitle></CardHeader>
        <CardContent>
          <div className="field-form">
            <Field label="Team name"><Input className="field" placeholder="e.g. payments" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Max concurrent invokes"><Input className="field" type="number" min="0" placeholder="0 = unlimited" value={cap} onChange={(e) => setCap(e.target.value)} /></Field>
            <Button onClick={add} disabled={!name}>Create team</Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>Team</TableHead><TableHead>Max concurrency</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!rows.length} cols={3}>No teams yet.</EmptyRow>
              {rows.map((t: any) => (
                <TableRow key={t.id}>
                  <TableCell>{t.name}</TableCell>
                  <TableCell className="mono">{t.max_concurrency || '∞'}</TableCell>
                  <TableCell><Button variant="outline" size="sm" onClick={() => del(t.id)}>Delete</Button></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Membership</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>User</TableHead><TableHead>Team</TableHead></TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!users.length} cols={2}>No users.</EmptyRow>
              {users.map((u: any) => (
                <TableRow key={u.id}>
                  <TableCell>{u.email}</TableCell>
                  <TableCell>
                    <Select value={u.team_id ?? ''} onValueChange={(v) => assign(u.id, v === 'none' ? '' : (v ?? ''))}>
                      <SelectTrigger className="field"><SelectValue placeholder={u.team_id ? teamName(u.team_id) : 'unassigned'} /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="none">unassigned</SelectItem>
                        {rows.map((t: any) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  )
}

// Visibility-first home: highlight the few actionable things, drill in for detail.
function MfaCard() {
  const [ok, setOk] = useState(true), [enabled, setEnabled] = useState(false)
  const [secret, setSecret] = useState(''), [uri, setUri] = useState(''), [code, setCode] = useState('')
  const load = () => api('/auth/mfa/status').then((s) => setEnabled(!!s.enabled)).catch(() => setOk(false))
  useEffect(() => { load() }, [])
  if (!ok) return null
  const enroll = () => post('/auth/mfa/enroll', {}).then((r) => { setSecret(r.secret); setUri(r.otpauth_uri) }).catch(fail)
  const confirm = () => post('/auth/mfa/confirm', { code }).then(() => {
    setSecret(''); setUri(''); setCode(''); load(); toast.success('MFA enabled')
  }).catch(() => toast.error('invalid code'))
  const disable = () => post('/auth/mfa/disable', { code }).then(() => {
    setCode(''); load(); toast.success('MFA disabled')
  }).catch(() => toast.error('invalid code'))
  return (
    <Card>
      <CardHeader><CardTitle>Two-factor authentication (TOTP){enabled && <Badge variant="secondary" style={{ marginLeft: '.5rem' }}>enabled</Badge>}</CardTitle></CardHeader>
      <CardContent>
        {enabled ? (
          <div className="field-form">
            <p className="muted">MFA is on for your account. Enter a current code to turn it off.</p>
            <Field label="Authenticator code"><Input className="field" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <Button variant="outline" onClick={disable} disabled={!code}>Disable MFA</Button>
          </div>
        ) : secret ? (
          <div className="field-form">
            <p className="muted">Add this secret to your authenticator app, then confirm with a code.</p>
            <p className="mono" style={{ wordBreak: 'break-all' }}>{secret}</p>
            <p className="mono muted" style={{ wordBreak: 'break-all', fontSize: '.75rem' }}>{uri}</p>
            <Field label="Authenticator code"><Input className="field" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
            <Button onClick={confirm} disabled={!code}>Confirm &amp; enable</Button>
          </div>
        ) : (
          <div className="field-form">
            <p className="muted">Protect your account with a time-based one-time password.</p>
            <Button onClick={enroll}>Set up MFA</Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// A duration a person can read. Seconds are what the API reports, because the
// API should not guess what unit a reader wants.
export function human(seconds: number): string {
  if (!seconds || seconds < 1) return '—'
  if (seconds < 90) return `${Math.round(seconds)}s`
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`
  if (seconds < 172800) return `${Math.round(seconds / 3600)}h`
  return `${Math.round(seconds / 86400)}d`
}

export function Overview({ goto, can = () => true }: { goto: (v: any) => void; can?: (v: any) => boolean }) {
  // Everything here is about runs. It used to count `invoke-failed` and
  // `rollback` — recipes that no longer exist anywhere — so the home page was
  // reporting on a subsystem the factory never used.
  const [m, setM] = useState<any>(null)
  const [pending, setPending] = useState(0)
  const [findings, setFindings] = useState<any[]>([])
  const [runs, setRuns] = useState<any[]>([])
  useEffect(() => {
    api('/metrics').then(setM).catch(() => {})
    api('/approvals?status=pending').then((r) => setPending(r.length)).catch(() => {})
    api('/runs').then((r) => setRuns(r.slice(0, 8))).catch(() => {})
    // The improve lane: what went wrong, each traced to its evidence.
    api('/improve').then((r) => setFindings(r.findings ?? [])).catch(() => {})
  }, [])
  const d = m?.delivery ?? {}

  const cards = [
    { label: 'Waiting on a person', n: pending, go: 'approvals', attn: pending > 0, Icon: CheckSquare },
    { label: 'Runs in flight', n: d.in_flight ?? 0, go: 'runs', attn: false, Icon: Activity },
    { label: 'Runs failed', n: d.failed ?? 0, go: 'runs', attn: (d.failed ?? 0) > 0, Icon: Shield },
    { label: 'Things to look at', n: findings.length, go: 'metrics', attn: findings.length > 0, Icon: Eye },
  ]
  const worst = (m?.stage_health ?? []).filter((r: any) => r.trouble_pct > 0).slice(0, 4)

  return (
    <section className="page">
      <h2 className="page-title">Overview</h2>
      <p className="muted">What needs attention now. Select a card to drill in.</p>
      <div className="highlight-grid">
        {cards.filter((c) => can(c.go)).map((c) => (
          <button key={c.label} className={`highlight-card${c.attn ? ' highlight-attn' : ''}`} onClick={() => goto(c.go)}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className={c.attn ? 'highlight-num-attn' : 'highlight-num'}>{c.n}</span>
              <c.Icon size={18} className={c.attn ? '' : 'text-muted-foreground'} />
            </div>
            <div className="muted">{c.label}</div>
          </button>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle>Delivery</CardTitle></CardHeader>
        <CardContent>
          {d.runs ? (
            <div className="metric-grid">
              <div className="kv-row"><span>Landed</span><b>{d.landed_pct}% <span className="muted">of {d.finished} finished</span></b></div>
              <div className="kv-row"><span>To a pull request</span><b>{human(d.avg_seconds_to_pull_request)}</b></div>
              <div className="kv-row"><span>To an outcome</span><b>{human(d.avg_seconds_to_outcome)}</b></div>
              <div className="kv-row"><span>Landed · closed · failed</span><b>{d.landed} · {d.closed} · {d.failed}</b></div>
            </div>
          ) : <span className="muted">Nothing has run yet — start one under Work.</span>}
        </CardContent>
      </Card>

      {worst.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Stages that keep going wrong</CardTitle></CardHeader>
          <CardContent>
            <p className="muted">A stage that refuses on every repository is a fact about the workflow, not about any one ticket.</p>
            {worst.map((r: any) => (
              <div key={r.stage} className="kv-row">
                <span>{r.stage}</span>
                <b>{r.trouble_pct}% <span className="muted">of {r.attempts} attempt(s)</span></b>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {findings.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Things to look at</CardTitle></CardHeader>
          <CardContent>
            <div className="work-list">
              {findings.map((a: any, i: number) => (
                <div key={i} className="work-head">
                  <Badge variant={a.severity === 'high' ? 'destructive' : 'secondary'}>{a.severity}</Badge>
                  <Badge variant="outline">{a.kind}</Badge>
                  <span className="muted">{a.detail}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Latest runs</CardTitle></CardHeader>
        <CardContent>
          {runs.length ? (
            <div className="work-list">
              {runs.map((r: any) => (
                <div key={r.id} className="work-head">
                  <Badge variant={r.held ? 'destructive' : 'outline'}>{r.outcome || r.stage}</Badge>
                  {r.held && <Badge>waiting on a person</Badge>}
                  <span className="mono muted">{r.id.slice(0, 8)}</span>
                  {r.pr_url && <a className="muted" href={r.pr_url} target="_blank" rel="noreferrer">pull request</a>}
                </div>
              ))}
            </div>
          ) : <span className="muted">No runs yet.</span>}
        </CardContent>
      </Card>
      <MfaCard />
    </section>
  )
}

// The stages a work item can be in. Derived from its runs by the server
// (work_items.STAGES) — there is no board anybody drags a card across.
const WORK_STAGES = ['open', 'running', 'waiting', 'landed', 'closed', 'failed']
// oversight.LEVELS, in order of how much a person has to touch.
const OVERSIGHT_LEVELS = ['manual', 'assisted', 'supervised', 'autonomous', 'dark']

function Work() {
  const { rows, load } = useList('/work-items')
  const [repos, setRepos] = useState<any[]>([])
  const [title, setTitle] = useState(''), [repo, setRepo] = useState('')
  useEffect(() => { api('/repositories').then(setRepos).catch(fail) }, [])
  // Naming work and running it are one action: a ticket nobody runs is a ticket.
  const add = () => post('/work-items', { repo_id: repo, title })
    .then((w) => post('/runs', { work_item_id: w.id })
      .then(() => toast.success('Run started'))
      .catch((e) => toast.message('Work created', { description: `not started: ${e.message}` })))
    .then(() => { setTitle(''); load() }).catch(fail)
  const start = (id: string) => post('/runs', { work_item_id: id })
    .then(() => { toast.success('Run started'); load() }).catch(fail)
  const [selId, setSelId] = useState<string | null>(null)
  const selected = rows.find((r) => r.id === selId) ?? null  // re-derive so it tracks reloads
  const stages = WORK_STAGES.filter((s) => rows.some((w) => w.stage === s))

  return (
    <section className="page">
      <h2 className="page-title">Work</h2>
      <p className="muted">Your work, by what its latest run is doing. Select an item for detail.</p>
      <div className="field-form">
        <Field label="Title"><Input className="field" placeholder="what needs doing" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Repository">
          <Select value={repo} onValueChange={(v) => setRepo(v ?? '')}>
            <SelectTrigger className="field"><SelectValue placeholder="repo…" /></SelectTrigger>
            <SelectContent>{repos.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Button onClick={add} disabled={!title || !repo}>Ship work</Button>
      </div>

      {rows.length === 0
        ? <Card><CardContent><p className="muted">No work items yet — name one above and ship it to start the governed loop.</p></CardContent></Card>
        : (
          <div className="board">
            {stages.map((s) => (
              <div key={s} className="board-col">
                <div className="board-col-head"><span>{s}</span><Badge variant="secondary">{rows.filter((w) => w.stage === s).length}</Badge></div>
                {rows.filter((w) => w.stage === s).map((w) => (
                  <button key={w.id} className={`board-card${selId === w.id ? ' board-card-selected' : ''}`} onClick={() => setSelId(w.id)}>
                    <div className="work-title">{w.title}</div>
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

      <Drawer open={!!selected} title={selected?.title ?? ''} onClose={() => setSelId(null)}>
        {selected && <WorkRow bare w={selected} onStart={start} />}
      </Drawer>
    </section>
  )
}

function WorkRow({ w, onStart, bare }: any) {
  // No move/attest/request-approval here any more: a work item has no state
  // machine of its own. What happens to it is a run, and a run is approved at
  // `POST /runs/{id}/approve`.
  const [logs, setLogs] = useState<any[] | null>(null)
  const [runs, setRuns] = useState<any[]>([])
  useEffect(() => { api(`/runs?work_item_id=${w.id}`).then(setRuns).catch(() => {}) }, [w.id])
  // live log tail: subscribe to WS-relayed log lines for this item while open
  useEffect(() => {
    if (logs === null) return
    const onLog = (e: any) => { if (e.detail.subject === w.id) setLogs((ls) => [...(ls ?? []), e.detail]) }
    window.addEventListener('oref-log', onLog)
    return () => window.removeEventListener('oref-log', onLog)
  }, [logs === null, w.id])
  const showLogs = () => logs ? setLogs(null)
    : api(`/work-items/${w.id}/logs`).then((l) => setLogs(l)).catch(fail)
  return (
    <Card>
      <CardContent>
        <div className="work-head">
          {!bare && <span className="work-title">{w.title}</span>}
          <Badge>{w.stage}</Badge>
          {w.external_ref && <Badge variant="outline">{w.external_ref}</Badge>}
        </div>
        <div className="work-actions">
          <Button size="sm" onClick={() => onStart(w.id)}>Start a run</Button>
          <Button variant="outline" size="sm" onClick={showLogs}>{logs ? 'Hide logs' : 'Logs'}</Button>
        </div>
        {runs.length > 0 && (
          <div className="work-list" style={{ marginTop: '0.6rem' }}>
            {runs.map((r) => (
              <div key={r.id} className="work-head">
                <Badge variant={r.held ? 'destructive' : 'outline'}>{r.outcome || r.stage}</Badge>
                {r.held && <Badge>waiting on a person</Badge>}
                {r.pr_url && <a className="muted" href={r.pr_url} target="_blank" rel="noreferrer">pull request</a>}
              </div>
            ))}
          </div>
        )}
        {logs && (
          <div className="mono" style={{ marginTop: '0.6rem', borderTop: '1px solid var(--border)', paddingTop: '0.6rem', maxHeight: '12rem', overflow: 'auto' }}>
            {logs.length ? logs.map((l: any, i: number) => (
              <div key={i} className={l.level === 'error' ? 'log-error' : 'muted'}>{l.at?.slice(11, 19)} [{l.level}] {l.line}</div>
            )) : <span className="muted">no logs yet — lines stream here live</span>}
          </div>
        )}

      </CardContent>
    </Card>
  )
}

function Approvals() {
  // A held run, cleared by somebody holding `approve:code`. This used to list a
  // separate queue of kanban-transition requests signed by role rank.
  const { rows, load } = useList('/approvals?status=pending')
  const clear = (runId: string) => post(`/runs/${runId}/approve`, {})
    .then(() => { toast.success('approved'); load() }).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Waiting on a person</h2>
      <p className="muted">Runs held at a gate. Clearing one needs <span className="mono">approve:code</span>, and you cannot clear your own.</p>
      <div className="work-list">
        {rows.map((r) => (
          <Card key={r.run_id}>
            <CardContent>
              <div className="work-head">
                <span className="work-title">held at {r.stage}</span>
                <Badge variant="outline">{r.run_id.slice(0, 8)}</Badge>
              </div>
              <div className="work-actions">
                <Button size="sm" onClick={() => clear(r.run_id)}>Approve</Button>
              </div>
            </CardContent>
          </Card>
        ))}
        {!rows.length && <div className="muted">nothing is waiting</div>}
      </div>
    </section>
  )
}

function Usage({ me }: any) {
  // What runs cost, and the ceilings on them. Units are tokens as the provider
  // reported them — the product does not know anybody's rate card.
  const [data, setData] = useState<any>(null)
  const { rows: budgets, load: loadBudgets } = useList('/budgets')
  const { rows: repos } = useList('/repositories')
  const { rows: teams } = useList('/teams')
  const [scope, setScope] = useState('org'), [scopeId, setScopeId] = useState('')
  const [limit, setLimit] = useState(''), [window, setWindow] = useState('0')
  const mayEdit = (me?.permissions ?? []).includes('approve:factory')
  const load = () => api('/usage').then(setData).catch(fail)
  useEffect(() => { load() }, [])

  const add = () => post('/budgets', {
    scope, scope_id: scope === 'org' ? '' : scopeId,
    limit: Number(limit) || 0, window_seconds: Number(window) || 0,
  }).then(() => { setLimit(''); loadBudgets() }).catch(fail)
  const del = (id: string) => api(`/budgets/${id}`, { method: 'DELETE' }).then(loadBudgets).catch(fail)

  const options = scope === 'repo' ? repos : scope === 'team' ? teams : []
  const nameOf = (b: any) => b.scope === 'org' ? 'everything'
    : (repos.find((r: any) => r.id === b.scope_id)?.name
       ?? teams.find((t: any) => t.id === b.scope_id)?.name ?? b.scope_id)

  return (
    <section className="page">
      <h2 className="page-title">Spend</h2>
      <p className="muted">
        What runs cost, in units the provider reported. A ceiling is checked
        <em> between</em> stages — nothing knows what a turn costs until it is over.
      </p>

      <Card>
        <CardHeader><CardTitle>Ceilings</CardTitle></CardHeader>
        <CardContent>
          {mayEdit && (
            <div className="field-form">
              <Field label="Scope">
                <Select value={scope} onValueChange={(v) => { setScope(v ?? 'org'); setScopeId('') }}>
                  <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="org">org</SelectItem>
                    <SelectItem value="repo">repo</SelectItem>
                    <SelectItem value="team">team</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
              {scope !== 'org' && (
                <Field label={scope === 'repo' ? 'Repository' : 'Team'}>
                  <Select value={scopeId} onValueChange={(v) => setScopeId(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue placeholder="which…" /></SelectTrigger>
                    <SelectContent>
                      {options.map((o: any) => <SelectItem key={o.id} value={o.id}>{o.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </Field>
              )}
              <Field label="Units"><Input className="field" type="number" value={limit}
                onChange={(e) => setLimit(e.target.value)} /></Field>
              <Field label="Per (seconds)"><Input className="field" type="number" value={window}
                title="0 = a lifetime cap that never rolls" onChange={(e) => setWindow(e.target.value)} /></Field>
              <Button onClick={add} disabled={!limit || (scope !== 'org' && !scopeId)}>Set ceiling</Button>
            </div>
          )}
          <Table>
            <TableHeader><TableRow>
              <TableHead>Scope</TableHead><TableHead>Used</TableHead>
              <TableHead>Limit</TableHead><TableHead>Window</TableHead><TableHead />
            </TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!budgets.length} cols={5}>
                No ceiling set — runs may spend without limit.
              </EmptyRow>
              {budgets.map((b: any) => (
                <TableRow key={b.id}>
                  <TableCell><Badge variant="outline">{b.scope}</Badge> {nameOf(b)}</TableCell>
                  <TableCell className={b.used >= b.limit ? 'log-error' : ''}>{b.used}</TableCell>
                  <TableCell>{b.limit}</TableCell>
                  <TableCell className="muted">{b.window_seconds ? `${b.window_seconds}s` : 'lifetime'}</TableCell>
                  <TableCell>{mayEdit && <Button variant="outline" size="sm" onClick={() => del(b.id)}>Remove</Button>}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="muted">
            A ceiling on <strong>one</strong> run is the repository's{' '}
            <span className="mono">max_run_units</span>, in its settings drawer.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>By run ({data?.total_units ?? 0} units)</CardTitle></CardHeader>
        <CardContent>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Run</TableHead><TableHead>Stage</TableHead><TableHead>Units</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!(data?.by_run ?? []).length} cols={3}>
                Nothing has run yet.
              </EmptyRow>
              {(data?.by_run ?? []).map((r: any) => (
                <TableRow key={r.run_id}>
                  <TableCell className="mono">{r.run_id.slice(0, 8)}</TableCell>
                  <TableCell><Badge variant="outline">{r.outcome || r.stage}</Badge></TableCell>
                  <TableCell>{r.units}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </section>
  )
}

function Events({ isAdmin }: any) {
  const { rows, load } = useList('/events?limit=100')
  const [days, setDays] = useState('90')
  const [chain, setChain] = useState<any>(null)
  const purge = () => post(`/audit/purge?days=${Number(days) || 90}`, {})
    .then((r) => { toast.success(`Purged ${r.purged} event(s)`); load() }).catch(fail)
  const verify = () => api('/audit/verify').then(setChain).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Audit trail</h2>
      <p className="muted">Tamper-evident: every event is hash-chained to the previous. Verify the chain, or export a signed record for auditors.</p>
      <div className="field-form">
        <Button variant="secondary" onClick={verify}>Verify trail</Button>
        {chain && <Badge variant={chain.ok ? 'default' : 'destructive'}>
          {chain.ok ? `✓ intact · ${chain.count} events` : `✗ broken at ${chain.broken_at}`}
        </Badge>}
        <span className="app-spacer" />
        <Button variant="outline" onClick={() => download('/audit/export.csv', 'audit.csv').catch(fail)}>Export CSV</Button>
        <Button variant="outline" onClick={() => download('/audit/export', 'audit-signed.json').catch(fail)}>Export signed</Button>
      </div>
      {isAdmin && (
        <div className="field-form">
          <Field label="Retention (days)"><Input className="field" type="number" placeholder="90" value={days} onChange={(e) => setDays(e.target.value)} /></Field>
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

const METRIC_LABEL: Record<string, string> = {
  avg_lead_seconds: 'avg lead time (s)', median_lead_seconds: 'median lead time (s)',
  items: 'items', count: 'count',
}
const humanKey = (k: string) => METRIC_LABEL[k] ?? k.replace(/_/g, ' ')

// Compliance evidence packs + time-boxed auditor grants.
function Evidence({ me }: any) {
  const isAdmin = me?.role === 'admin'
  const [frameworks, setFrameworks] = useState<string[]>([])
  const [fw, setFw] = useState('soc2')
  const [pack, setPack] = useState<any>(null)
  useEffect(() => { api('/evidence/frameworks').then(setFrameworks).catch(() => {}) }, [])
  const gen = () => api(`/evidence?framework=${fw}`).then(setPack).catch(fail)
  useEffect(() => { gen() }, [fw])

  // auditor grants (admin only)
  const [grants, setGrants] = useState<any[]>([])
  const loadGrants = () => api('/auditor-grants').then(setGrants).catch(() => {})
  useEffect(() => { if (isAdmin) loadGrants() }, [])
  const [label, setLabel] = useState(''), [ttl, setTtl] = useState('14'), [issued, setIssued] = useState('')
  const mint = () => post('/auditor-grants', { label, ttl_days: Number(ttl) || 14 })
    .then((r) => { setIssued(r.token); setLabel(''); loadGrants(); toast.success('Auditor access minted') }).catch(fail)
  const revoke = (id: string) => api(`/auditor-grants/${id}`, { method: 'DELETE' }).then(loadGrants).catch(fail)

  const badge = (s: string) => s === 'met' ? 'default' : s === 'partial' ? 'secondary' : 'destructive'
  return (
    <section className="page">
      <h2 className="page-title">Compliance evidence</h2>
      <p className="muted">A framework-mapped bundle drawn from the audit trail, policies, versioned history, and attestations — proof that controls are enforced. Backed by the tamper-evident chain.</p>
      <div className="field-form">
        <Field label="Framework">
          <Select value={fw} onValueChange={(v) => setFw(v ?? 'soc2')}>
            <SelectTrigger className="field"><SelectValue /></SelectTrigger>
            <SelectContent>{frameworks.map((f) => <SelectItem key={f} value={f}>{f.toUpperCase()}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Button variant="outline" onClick={() => download(`/evidence?framework=${fw}`, `evidence-${fw}.json`).catch(fail)}>Download pack</Button>
      </div>
      {pack && (
        <Card>
          <CardHeader><CardTitle>{pack.framework.toUpperCase()} · {pack.summary.met}/{pack.summary.controls} controls met ({pack.summary.coverage_pct}%)</CardTitle></CardHeader>
          <CardContent>
            <div className="toolbar" style={{ marginBottom: '.5rem' }}>
              <Badge variant={pack.integrity.ok ? 'default' : 'destructive'}>
                {pack.integrity.ok ? '✓ audit trail intact' : '✗ audit trail broken'}
              </Badge>
              <span className="muted">generated {pack.generated_at?.slice(0, 19)}</span>
            </div>
            <Table>
              <TableHeader><TableRow><TableHead>Control</TableHead><TableHead>Requirement</TableHead><TableHead>Status</TableHead><TableHead>Evidence</TableHead></TableRow></TableHeader>
              <TableBody>{pack.controls.map((c: any) => (
                <TableRow key={c.id}>
                  <TableCell><span className="mono">{c.control}</span> {c.title}</TableCell>
                  <TableCell className="muted">{c.requirement}</TableCell>
                  <TableCell><Badge variant={badge(c.status)}>{c.status}</Badge></TableCell>
                  <TableCell className="mono">{Object.entries(c.evidence).map(([k, v]) => `${k}=${v}`).join(' · ')}</TableCell>
                </TableRow>
              ))}</TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      {isAdmin && (
        <Card>
          <CardHeader><CardTitle>Auditor access</CardTitle></CardHeader>
          <CardContent>
            <p className="muted">Mint a time-boxed, read-only access code for an external auditor — they browse evidence + the audit trail and change nothing; it expires on its own.</p>
            <div className="field-form">
              <Field label="Auditor / firm"><Input className="field" placeholder="e.g. Ernst & Young" value={label} onChange={(e) => setLabel(e.target.value)} /></Field>
              <Field label="Expires (days)"><Input className="field" type="number" value={ttl} onChange={(e) => setTtl(e.target.value)} /></Field>
              <Button onClick={mint} disabled={!label}>Mint access code</Button>
            </div>
            {issued && (
              <div className="policy-preview">
                <div>Access code — copy now, shown once:</div>
                <pre className="mono" style={{ whiteSpace: 'pre-wrap' }}>{issued}</pre>
                <p className="muted">The auditor signs in with this code (read-only).</p>
              </div>
            )}
            <Table>
              <TableHeader><TableRow><TableHead>Auditor</TableHead><TableHead>Expires</TableHead><TableHead /></TableRow></TableHeader>
              <TableBody>
                <EmptyRow show={!grants.length} cols={3}>No auditor access granted.</EmptyRow>
                {grants.map((g) => (
                  <TableRow key={g.id}>
                    <TableCell>{g.label}</TableCell>
                    <TableCell className="mono">{g.expires_at?.slice(0, 10)} {g.expired && <Badge variant="destructive">expired</Badge>}</TableCell>
                    <TableCell><Button variant="outline" size="sm" onClick={() => revoke(g.id)}>Revoke</Button></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </section>
  )
}

function Metrics() {
  const [m, setM] = useState<any>(null)
  // The improve lane replaced four separate analyses in 2.15.0.
  const [improve, setImprove] = useState<any>(null)
  useEffect(() => { api('/improve').then(setImprove).catch(() => {}) }, [])
  const [names, setNames] = useState<Record<string, string>>({})
  useEffect(() => {
    api('/metrics').then(setM).catch(fail)
    // resolve actor ids → emails when permitted (platform/admin); dev falls back to short id
    api('/users').then((us: any[]) => setNames(Object.fromEntries(us.map((u) => [u.id, u.email])))).catch(() => {})
  }, [])
  if (!m) return null
  const d = m.delivery ?? {}
  const panels = [
    { title: 'Work by stage', data: m.wip_by_stage, accent: 'accent-blue', actor: false },
    { title: 'Events', data: m.event_counts, accent: 'accent-green', actor: false },
    { title: 'Activity by actor', data: m.activity_by_actor, accent: 'accent-purple', actor: true },
  ]
  const keyLabel = (p: any, k: string) => p.actor ? (names[k] ?? `${k.slice(0, 8)}…`) : humanKey(k)
  return (
    <section className="page">
      <h2 className="page-title">Metrics</h2>

      <Card className="accent-orange">
        <CardHeader><CardTitle>Delivery</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">
            What shipped and how long it took. <strong>Landed</strong> is over
            <em> finished</em> runs — counting one still in flight as a failure to
            land would make the number sag whenever the factory is busy.
          </p>
          <div className="metric-grid">
            <div className="kv-row"><span>Runs</span><b>{d.runs ?? 0}</b></div>
            <div className="kv-row"><span>In flight</span><b>{d.in_flight ?? 0}</b></div>
            <div className="kv-row"><span>Waiting on a person</span><b>{d.held ?? 0}</b></div>
            <div className="kv-row"><span>Landed</span><b>{d.landed ?? 0} ({d.landed_pct ?? 0}%)</b></div>
            <div className="kv-row"><span>Closed</span><b>{d.closed ?? 0}</b></div>
            <div className="kv-row"><span>Failed</span><b>{d.failed ?? 0}</b></div>
            <div className="kv-row"><span>Reached a pull request</span><b>{d.reached_a_pull_request ?? 0}</b></div>
            <div className="kv-row"><span>Time to a pull request</span><b>{human(d.avg_seconds_to_pull_request ?? 0)}</b></div>
            <div className="kv-row"><span>Time to an outcome</span><b>{human(d.avg_seconds_to_outcome ?? 0)}</b></div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Stage health</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">Worst first — the row somebody opened this to find.</p>
          <Table>
            <TableHeader><TableRow>
              <TableHead>Stage</TableHead><TableHead>Attempts</TableHead>
              <TableHead>Refused</TableHead><TableHead>Errors</TableHead>
              <TableHead>Redone</TableHead><TableHead>Trouble</TableHead><TableHead>Units</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!(m.stage_health ?? []).length} cols={7}>
                Nothing has run yet.
              </EmptyRow>
              {(m.stage_health ?? []).map((r: any) => (
                <TableRow key={r.stage}>
                  <TableCell>{r.stage}</TableCell>
                  <TableCell>{r.attempts}</TableCell>
                  <TableCell>{r.refused}</TableCell>
                  <TableCell>{r.error}</TableCell>
                  <TableCell>{r.retries}</TableCell>
                  <TableCell className={r.trouble_pct > 0 ? 'log-error' : ''}>{r.trouble_pct}%</TableCell>
                  <TableCell className="muted">{r.units}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div className="metric-grid">
        {panels.map((p) => (
          <Card key={p.title} className={p.accent}>
            <CardHeader><CardTitle>{p.title}</CardTitle></CardHeader>
            <CardContent>
              {Object.entries(p.data ?? {}).map(([k, v]) => (
                <div key={k} className="kv-row"><span>{keyLabel(p, k)}</span><b>{String(v)}</b></div>
              ))}
              {!Object.keys(p.data ?? {}).length && <div className="muted">none yet</div>}
            </CardContent>
          </Card>
        ))}
      </div>

      {improve && <ImproveLane improve={improve} />}
    </section>
  )
}

/**
 * The improve lane — what went wrong, and what would have prevented it.
 *
 * Findings are read-only until somebody acts on one, and acting means
 * *proposing*, never applying. What acceptance buys is a work item, which then
 * goes through the same stage graph and the same review as anything a person
 * filed — the lane that proposes improvements does not get to skip the gate
 * everything else goes through.
 */
function ImproveLane({ improve }: { improve: any }) {
  const { rows: repos } = useList('/repositories')
  const [repo, setRepo] = useState('')
  const [raised, setRaised] = useState<Record<string, boolean>>({})

  const propose = (f: any) =>
    post('/improve/propose', { kind: f.kind, detail: f.detail, repo_id: repo })
      .then(() => {
        setRaised((r) => ({ ...r, [f.detail]: true }))
        toast.success('Proposed — it needs a signature before it becomes work')
      }).catch(fail)

  return (
    <Card>
      <CardHeader><CardTitle>Things to look at ({improve.total})</CardTitle></CardHeader>
      <CardContent>
        <div className="toolbar">
          <Badge variant={improve.score >= 90 ? 'outline' : 'destructive'}>
            health {improve.score}
          </Badge>
          {!improve.total && <span className="muted">nothing to report</span>}
        </div>
        {improve.total > 0 && (<>
          <div className="work-actions">
            <Select value={repo} onValueChange={(v) => setRepo(v ?? '')}>
              <SelectTrigger className="field"><SelectValue placeholder="fix it in…" /></SelectTrigger>
              <SelectContent>
                {repos.map((r: any) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <Table>
            <TableHeader><TableRow>
              <TableHead>What</TableHead><TableHead>Severity</TableHead>
              <TableHead>Detail</TableHead><TableHead>Suggestion</TableHead>
              <TableHead>Evidence</TableHead><TableHead />
            </TableRow></TableHeader>
            <TableBody>{improve.findings.map((f: any, i: number) => (
              <TableRow key={i}>
                <TableCell><Badge variant={f.severity === 'high' ? 'destructive' : 'secondary'}>{f.kind}</Badge></TableCell>
                <TableCell className="mono">{f.severity}</TableCell>
                <TableCell>{f.detail}</TableCell>
                <TableCell className="muted">{f.suggestion}</TableCell>
                <TableCell className="muted mono">{(f.evidence ?? []).length}</TableCell>
                <TableCell>
                  {raised[f.detail]
                    ? <Badge variant="outline">proposed</Badge>
                    : <Button size="sm" variant="outline" disabled={!repo || !f.suggestion}
                        onClick={() => propose(f)}>Propose as work</Button>}
                </TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </>)}
        <p className="muted">Every finding names the events it came from — one that cannot be
          traced is dropped rather than repaired. Proposing does not change anything: it puts
          the finding in front of a person, and accepting it creates a work item that goes
          through the same pipeline as any other change.</p>
      </CardContent>
    </Card>
  )
}
