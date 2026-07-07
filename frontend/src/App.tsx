import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api, post, download, getToken, setToken, clearToken, oauthLoginUrl } from './api'
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
  Package, Boxes, Plug, Target, Users, BarChart3, Coins, Network, Activity, ScanSearch,
  FlaskConical, ScrollText, Mail, Settings as SettingsIcon, ShieldCheck, PanelLeftClose,
  PanelLeft, LogOut, Eye, Bot, Lock,
} from 'lucide-react'

// One icon per view — used by the sidebar and (later) overview cards.
const VIEW_ICON: Record<string, any> = {
  overview: LayoutDashboard, work: ListChecks, approvals: CheckSquare, repos: GitBranch,
  processes: Workflow, policies: Shield, proposals: GitPullRequest, packs: Package,
  governance: ShieldCheck, myrules: Eye, harnesses: Bot, systems: Boxes, integrations: Plug, targets: Target, teams: Users,
  metrics: BarChart3, usage: Coins, traffic: Network, audits: Activity, coverage: ScanSearch,
  experiments: FlaskConical, events: ScrollText, invitations: Mail, settings: SettingsIcon,
}
const GROUP_ICON: Record<string, any> = {
  Home: LayoutDashboard, Work: ListChecks, Governance: ShieldCheck, Platform: Boxes,
  Insights: BarChart3, Admin: SettingsIcon,
}

type View = 'overview' | 'work' | 'approvals' | 'repos' | 'processes' | 'systems' | 'integrations' | 'targets' | 'policies' | 'packs' | 'proposals' | 'coverage' | 'audits' | 'experiments' | 'invitations' | 'settings' | 'governance' | 'events' | 'metrics' | 'teams' | 'usage' | 'traffic' | 'myrules' | 'harnesses'
type Role = { name: string; rank: number }
const fail = (e: any) => toast.error(e.message ?? String(e))

// Role-scoped navigation — each view lists exactly the roles it serves. This is
// the single source of truth for the frontend; the backend enforces the same
// matrix with 403s. Responsibilities:
//   developer — operates their own dev concerns (services, repos, processes,
//               agents, work) + their own insights (metrics, coverage).
//   platform  — platform concerns (systems, targets, teams), governance
//               authoring, and full org insights. Approves gated work.
//   admin     — oversight only: reporting/insights, governance landscape, and
//               user administration. Does not operate the factory.
type NavTab = { value: View; label: string; roles: string[] }
const ALL = ['developer', 'platform', 'admin']
const NAV: { group: string; tabs: NavTab[] }[] = [
  { group: 'Home', tabs: [
    { value: 'overview', label: 'Overview', roles: ALL } ] },
  // ordered by entity dependency: services → repos → processes → agents → work → approvals
  { group: 'Work', tabs: [
    { value: 'integrations', label: 'Services', roles: ['developer'] },
    { value: 'repos', label: 'Repos', roles: ['developer'] },
    { value: 'processes', label: 'Processes', roles: ['developer'] },
    { value: 'harnesses', label: 'Harnesses', roles: ['developer', 'platform'] },
    { value: 'work', label: 'Work', roles: ['developer'] },
    { value: 'approvals', label: 'Approvals', roles: ['developer', 'platform'] } ] },
  { group: 'Governance', tabs: [
    { value: 'myrules', label: 'My rules', roles: ['developer'] },   // read-only
    { value: 'policies', label: 'Policies', roles: ['platform'] },
    { value: 'proposals', label: 'Proposals', roles: ['platform'] },
    { value: 'packs', label: 'Packs', roles: ['developer', 'platform'] },
    { value: 'governance', label: 'Governance', roles: ['platform', 'admin'] } ] },
  { group: 'Platform', tabs: [
    { value: 'systems', label: 'Systems', roles: ['platform'] },
    { value: 'targets', label: 'Targets', roles: ['platform'] },
    { value: 'teams', label: 'Teams', roles: ['platform', 'admin'] } ] },
  { group: 'Insights', tabs: [
    { value: 'metrics', label: 'Metrics', roles: ALL },
    { value: 'coverage', label: 'Coverage', roles: ALL },
    { value: 'usage', label: 'Usage', roles: ['platform', 'admin'] },
    { value: 'traffic', label: 'Traffic', roles: ['platform', 'admin'] },
    { value: 'audits', label: 'Audits', roles: ['platform', 'admin'] },
    { value: 'experiments', label: 'Experiments', roles: ['platform', 'admin'] },
    { value: 'events', label: 'Audit log', roles: ['platform', 'admin'] } ] },
  { group: 'Admin', tabs: [
    { value: 'invitations', label: 'Invitations', roles: ALL },  // invite your level or lower
    { value: 'settings', label: 'Settings', roles: ['platform', 'admin'] } ] },
]

// Empty-state row for a list; render inside <TableBody> when there are no rows.
export function EmptyRow({ show, cols, children }: { show: boolean; cols: number; children: any }) {
  if (!show) return null
  return <TableRow><TableCell colSpan={cols} className="muted">{children}</TableCell></TableRow>
}

// A process, drawn: stages as nodes, flow left→right, gated stages locked, the
// current stage lit, feedback loops noted. The process concept made visible.
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
      }
    } catch { setLive(false) }
    return () => ws?.close()
  }, [token])

  useEffect(() => {
    document.title = me ? `Open Refinery · ${view[0].toUpperCase()}${view.slice(1)}` : 'Open Refinery'
  }, [view, me])

  // Never sit on a view the role can't access (defence in depth alongside the backend).
  useEffect(() => {
    if (me && !NAV.flatMap((n) => n.tabs).find((t) => t.value === view)?.roles.includes(me.role)) {
      setGroup('Home'); setView('overview')
    }
  }, [view, me])

  // Everyone lands on the visibility-first Overview (what needs attention now).
  useEffect(() => {
    if (!me) return
    setGroup('Home')
    setView('overview')
  }, [me])

  // First-run: platform/admin see the setup wizard until the org is onboarded.
  useEffect(() => {
    if (!me) return
    if (['platform', 'admin'].includes(me.role)) {
      api('/onboarding').then((r) => setOnboarded(!!r.onboarded)).catch(() => setOnboarded(true))
    } else setOnboarded(true)  // developers inherit the configured org
  }, [me])

  const isAdmin = !!me && me.role === 'admin'
  const [group, setGroup] = useState('Home')
  const [collapsed, setCollapsed] = useState(false)
  const [onboarded, setOnboarded] = useState<boolean | null>(null)

  const allow = (t: NavTab) => !!me && t.roles.includes(me.role)
  // is `view` permitted for the current role? (mirrors the backend authorization)
  const can = (v: View) => !!me && (NAV.flatMap((n) => n.tabs).find((t) => t.value === v)?.roles.includes(me.role) ?? false)
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
              {/* Home */}
              <TabsContent value="overview"><Overview goto={goto} can={can} /></TabsContent>
              {/* Work: services → repos → processes → agents → work → approvals */}
              <TabsContent value="integrations"><Integrations /></TabsContent>
              <TabsContent value="repos"><Repos /></TabsContent>
              <TabsContent value="processes"><Processes /></TabsContent>
              <TabsContent value="harnesses"><Harnesses me={me} roles={roles} /></TabsContent>
              <TabsContent value="work"><Work /></TabsContent>
              <TabsContent value="approvals"><Approvals /></TabsContent>
              {/* Governance */}
              {can('myrules') && <TabsContent value="myrules"><MyRules me={me} /></TabsContent>}
              <TabsContent value="policies"><Policies /></TabsContent>
              <TabsContent value="proposals"><Proposals me={me} roles={roles} isAdmin={isAdmin} /></TabsContent>
              <TabsContent value="packs"><Packs me={me} roles={roles} /></TabsContent>
              {can('governance') && <TabsContent value="governance"><Governance /></TabsContent>}
              {/* Platform */}
              <TabsContent value="systems"><Systems /></TabsContent>
              <TabsContent value="targets"><Targets /></TabsContent>
              <TabsContent value="teams"><Teams /></TabsContent>
              {/* Insights */}
              <TabsContent value="metrics"><Metrics /></TabsContent>
              <TabsContent value="coverage"><Coverage /></TabsContent>
              <TabsContent value="usage"><Usage /></TabsContent>
              <TabsContent value="traffic"><Traffic /></TabsContent>
              <TabsContent value="audits"><Audits /></TabsContent>
              <TabsContent value="experiments"><Experiments /></TabsContent>
              <TabsContent value="events"><Events isAdmin={isAdmin} /></TabsContent>
              {/* Admin */}
              {can('invitations') && <TabsContent value="invitations"><Invitations me={me} roles={roles} /></TabsContent>}
              {can('settings') && <TabsContent value="settings"><Settings /></TabsContent>}
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
        <LoginBrand tagline={email ? `Set a password to join as ${email}.` : 'This invitation is invalid or expired.'} />
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

// Brand lockup for the login/onboarding screens: the lit mark on a dark panel.
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
        <LoginBrand tagline="A dark factory with the lights on." />
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

// First-run setup wizard — the first admin goes from signed-up to a running
// factory: connect a service, import a repo, enable a pack, shape the first
// process from the tracker's own columns, ship the first work item.
// Onboarding follows the entity dependency direction: services → repos →
// processes → first work. Admins also invite the team who'll run the factory.
const WIZ_BASE = ['Welcome', 'Connect', 'Repository', 'Standards', 'Process', 'First work']
export function Wizard({ onDone, me, roles }: { onDone: () => void; me: any; roles: Role[] }) {
  const isAdmin = me?.role === 'admin'
  const steps = isAdmin
    ? [...WIZ_BASE.slice(0, 5), 'Invite', 'First work']  // invite before shipping
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

  // step 4 — process (from a tracker's columns, or manual)
  const { rows: procs, load: reloadProcs } = useList('/processes')
  const [pname, setPname] = useState('My process'), [parch, setParch] = useState('board')
  const [pstages, setPstages] = useState('backlog, in progress, review, done')
  const [fromTracker, setFromTracker] = useState('')
  const pullColumns = (id: string) => api(`/integrations/${id}/workflow`)
    .then((r) => { if (r.stages?.length) setPstages(r.stages.join(', ')) })
    .then(() => toast.success('Columns imported')).catch(fail)
  const addProc = () => post('/processes', {
    name: pname, archetype: parch, oversight: 'supervised',
    stages: pstages.split(',').map((s) => s.trim()).filter(Boolean),
  }).then(() => { reloadProcs(); toast.success('Process created') }).catch(fail)

  // invite step (admin) — bring in the team who'll run the factory
  const myRank = roles.find((r) => r.name === me?.role)?.rank ?? 0
  const inviteOptions = roles.filter((r) => r.rank <= myRank).map((r) => r.name)  // your level or lower
  const [iemail, setIemail] = useState(''), [irole, setIrole] = useState('developer')
  const [invited, setInvited] = useState<string[]>([])
  const invite = () => post('/invitations', { email: iemail, role: irole, ttl_days: 7 })
    .then(() => { setInvited((v) => [...v, `${iemail} (${irole})`]); setIemail(''); toast.success('Invitation sent') }).catch(fail)

  // first work item
  const [wtitle, setWtitle] = useState(''), [wrepo, setWrepo] = useState(''), [wproc, setWproc] = useState('')
  const ship = () => post('/work-items', { repo_id: wrepo, process_id: wproc, title: wtitle })
    .then(() => toast.success('Work shipped')).catch(fail)

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
              <p>Welcome. In a few steps you'll connect your tools, import a repository, adopt a set of standards, and shape the first process from your own board — then ship a work item through it.</p>
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
              <p className="muted">Adopt a starter set of standards & processes. Enable what fits (you can add more later).</p>
              <div className="board">{packs.slice(0, 9).map((p: any) => (
                <button key={p.key} className={`wizard-pill${p.enabled ? ' picked' : ''}`}
                        onClick={() => !p.enabled && enablePack(p.key)}>
                  <Package size={15} /> {p.title}{p.enabled && <Badge>on</Badge>}
                </button>
              ))}</div>
            </div>
          )}

          {cur === 'Process' && (
            <div className="space-y-3">
              <p className="muted">Shape your first process. Pull the stages from a connected tracker's board, or type your own.</p>
              {trackers.length > 0 && (
                <div className="field-form">
                  <Field label="From tracker columns">
                    <Select value={fromTracker} onValueChange={(v) => { setFromTracker(v ?? ''); if (v) pullColumns(v) }}>
                      <SelectTrigger className="field"><SelectValue placeholder="tracker…" /></SelectTrigger>
                      <SelectContent>{trackers.map((i) => <SelectItem key={i.id} value={i.id}>{i.kind} · {i.account}</SelectItem>)}</SelectContent>
                    </Select>
                  </Field>
                </div>
              )}
              <div className="field-form">
                <Field label="Name"><Input className="field" value={pname} onChange={(e) => setPname(e.target.value)} /></Field>
                <Field label="Type">
                  <Select value={parch} onValueChange={(v) => setParch(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent><SelectItem value="board">board</SelectItem><SelectItem value="doctrine">doctrine</SelectItem></SelectContent>
                  </Select>
                </Field>
                <Field label="Stages"><Input className="field" style={{ width: '20rem' }} value={pstages} onChange={(e) => setPstages(e.target.value)} /></Field>
                <Button onClick={addProc} disabled={!pname || !pstages}>Create process</Button>
              </div>
              {/* preview the process as a pipeline */}
              <Pipeline stages={pstages.split(',').map((s) => s.trim()).filter(Boolean)} />
              <div className="toolbar">{procs.map((p: any) => <Badge key={p.id} variant="secondary">{p.name}</Badge>)}</div>
            </div>
          )}

          {cur === 'Invite' && (
            <div className="space-y-3">
              <p className="muted">Bring in the team who'll run the factory. Invite users at platform or developer level — they inherit everything you set up here.</p>
              <div className="field-form">
                <Field label="Email"><Input className="field" placeholder="teammate@acme.com" value={iemail} onChange={(e) => setIemail(e.target.value)} /></Field>
                <Field label="Role">
                  <Select value={irole} onValueChange={(v) => setIrole(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                    <SelectContent>{inviteOptions.map((r) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Button onClick={invite} disabled={!iemail}>Send invite</Button>
              </div>
              <div className="toolbar">{invited.map((v, i) => <Badge key={i} variant="secondary">{v}</Badge>)}</div>
            </div>
          )}

          {cur === 'First work' && (
            <div className="space-y-3">
              <p className="muted">Ship your first work item through the process you just built.</p>
              <div className="field-form">
                <Field label="Title"><Input className="field" placeholder="first task" value={wtitle} onChange={(e) => setWtitle(e.target.value)} /></Field>
                <Field label="Repository">
                  <Select value={wrepo} onValueChange={(v) => setWrepo(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue placeholder="repo…" /></SelectTrigger>
                    <SelectContent>{repos.map((r: any) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field label="Process">
                  <Select value={wproc} onValueChange={(v) => setWproc(v ?? '')}>
                    <SelectTrigger className="field"><SelectValue placeholder="process…" /></SelectTrigger>
                    <SelectContent>{procs.map((p: any) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Button onClick={ship} disabled={!wtitle || !wrepo || !wproc}>Ship it</Button>
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
  const { rows: integs } = useList('/integrations')
  const [name, setName] = useState(''), [url, setUrl] = useState('')
  const add = () => post('/repositories', { name, git_url: url })
    .then(() => { setName(''); setUrl(''); load() }).catch(fail)
  const linkIntegration = (repoId: string, choice: string) =>
    post(`/repositories/${repoId}/integration`, { integration_id: choice === 'auto' ? null : choice })
      .then(load).catch(fail)
  const schedule = (repoId: string, interval_hours: number) =>
    post(`/repositories/${repoId}/schedule`, { interval_hours }).then(load).catch(fail)
  return (
    <section className="page">
      <h2 className="page-title">Repositories</h2>
      <p className="muted">A repository is a project you govern — add one here or import from a connected integration.</p>
      <div className="field-form">
        <Field label="Name"><Input className="field" placeholder="e.g. checkout-api" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Git URL"><Input className="field" placeholder="git@github.com:org/repo.git" value={url} onChange={(e) => setUrl(e.target.value)} /></Field>
        <Button onClick={add} disabled={!name || !url}>Add repo</Button>
      </div>
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Git URL</TableHead><TableHead>Ingest source</TableHead><TableHead>Auto-ingest (h)</TableHead></TableRow></TableHeader>
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
                <TableCell>
                  <Input className="field" type="number" defaultValue={r.ingest_interval_hours ?? 0}
                         title="0 = manual"
                         onBlur={(e) => schedule(r.id, Number(e.target.value) || 0)} />
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
      <p className="muted">A process is the ordered steps work moves through, plus its oversight — which steps are gated and who must approve.</p>
      <div className="field-form">
        <Field label="Name"><Input className="field" placeholder="e.g. Feature" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Type">
          <Select value={arch} onValueChange={(v) => setArch(v ?? '')}>
            <SelectTrigger className="field"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="board">board</SelectItem><SelectItem value="doctrine">doctrine</SelectItem></SelectContent>
          </Select>
        </Field>
        <Field label="Steps (in order)"><Input className="field" placeholder="todo, doing, done" value={stages} onChange={(e) => setStages(e.target.value)} /></Field>
        <Field label="Oversight">
          <Select value={oversight} onValueChange={(v) => setOversight(v ?? '')}>
            <SelectTrigger className="field"><SelectValue /></SelectTrigger>
            <SelectContent>{['dark', 'autonomous', 'supervised', 'assisted', 'manual'].map((o) =>
              <SelectItem key={o} value={o}>{o}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Gated steps"><Input className="field" placeholder="blank = none" value={gates} onChange={(e) => setGates(e.target.value)} /></Field>
        <Field label="Min approver role">
          <Select value={minApprover} onValueChange={(v) => setMinApprover(v ?? '')}>
            <SelectTrigger className="field"><SelectValue /></SelectTrigger>
            <SelectContent>{roleRows.map((r: any) =>
              <SelectItem key={r.name} value={r.name}>{r.name}+</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Approval chain (roles)"><Input className="field" placeholder="blank = single approver" value={chain}
               onChange={(e) => setChain(e.target.value)} /></Field>
        <Button onClick={add} disabled={!name}>Add process</Button>
      </div>
      <div className="work-list">
        {!rows.length && <Card><CardContent><p className="muted">No processes yet — define one above.</p></CardContent></Card>}
        {rows.map((p) => (
          <Card key={p.id}>
            <CardContent>
              <div className="work-head">
                <span className="work-title">{p.name}</span>
                <Badge variant="secondary">{p.archetype}</Badge>
                <Badge variant="outline">{p.oversight}</Badge>
              </div>
              <div style={{ marginTop: '.6rem' }}>
                <Pipeline stages={p.stages} gates={p.gates} transitions={p.transitions} />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </section>
  )
}

// Credential field metadata — label + placeholder + whether it's a secret.
const FIELD_META: Record<string, { label: string; ph: string; secret?: boolean }> = {
  token: { label: 'Access token', ph: 'paste token', secret: true },
  site: { label: 'Site', ph: 'acme.atlassian.net' },
  email: { label: 'Email', ph: 'you@acme.com' },
  repo: { label: 'Repository', ph: 'owner/name (optional)' },
}
const CAP_LABEL: Record<string, string> = {
  source: 'code host', tracker: 'issue tracker', workflow: 'columns', docs: 'docs', notify: 'notify',
}

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
  const [catalog, setCatalog] = useState<any[]>([])
  const [providers, setProviders] = useState<Record<string, boolean>>({})
  const [kind, setKind] = useState('github')
  const [creds, setCreds] = useState<Record<string, string>>({})
  const [showToken, setShowToken] = useState(false)
  useEffect(() => {
    api('/connectors').then(setCatalog).catch(() => {})
    api('/auth/providers').then(setProviders).catch(() => {})
  }, [])
  const conn = catalog.find((c) => c.kind === kind)
  const fields: string[] = conn?.fields ?? ['token']
  const oauth = !!providers[kind]                       // OAuth configured for this service
  const missing = fields.some((f) => f !== 'repo' && !creds[f])
  const pick = (v: string) => { setKind(v); setCreds({}); setShowToken(false) }
  const connectToken = () => {
    const credential: Record<string, string> = {}
    for (const f of fields) if (creds[f]) credential[f] = creds[f]
    post('/integrations', { kind, credential })
      .then(() => { setCreds({}); setShowToken(false); toast.success('Connected'); onConnected?.() }).catch(fail)
  }
  const connectOAuth = () => post(`/integrations/${kind}/oauth/start`, {})
    .then((r) => { window.location.href = r.authorize_url }).catch(fail)
  return (
    <div className="space-y-3">
      <div className="field-form">
        <Field label="Service">
          <Select value={kind} onValueChange={(v) => pick(v ?? '')}>
            <SelectTrigger className="field"><SelectValue /></SelectTrigger>
            <SelectContent>{catalog.map((c) => <SelectItem key={c.kind} value={c.kind}>{c.label}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        {oauth
          ? <Button onClick={connectOAuth}>Continue with {conn?.label} →</Button>
          : (
            <>
              {fields.map((f) => {
                const m = FIELD_META[f] ?? { label: f, ph: f }
                return <Field key={f} label={m.label}><Input className="field" placeholder={m.ph}
                  type={m.secret ? 'password' : 'text'} value={creds[f] ?? ''}
                  onChange={(e) => setCreds((c) => ({ ...c, [f]: e.target.value }))} /></Field>
              })}
              <Button onClick={connectToken} disabled={missing}>Connect with token</Button>
            </>
          )}
      </div>
      {/* token fallback when OAuth is the primary path */}
      {oauth && (showToken
        ? (
          <div className="field-form">
            {fields.map((f) => {
              const m = FIELD_META[f] ?? { label: f, ph: f }
              return <Field key={f} label={m.label}><Input className="field" placeholder={m.ph}
                type={m.secret ? 'password' : 'text'} value={creds[f] ?? ''}
                onChange={(e) => setCreds((c) => ({ ...c, [f]: e.target.value }))} /></Field>
            })}
            <Button variant="outline" onClick={connectToken} disabled={missing}>Connect with token</Button>
          </div>
        )
        : <Button variant="link" size="sm" onClick={() => setShowToken(true)}>Use an access token instead</Button>)}
      {!oauth && conn && (
        <p className="muted">OAuth isn’t configured for {conn.label}. Connect with a token, or an admin can set OAuth up in Settings for a one-click connect.</p>
      )}
      {conn && (
        <div className="toolbar">{conn.caps.map((c: string) => <Badge key={c} variant="outline">{CAP_LABEL[c] ?? c}</Badge>)}</div>
      )}
    </div>
  )
}

function Integrations() {
  const { rows, load } = useList('/integrations')
  return (
    <section className="page">
      <h2 className="page-title">Services</h2>
      <p className="muted">Connect the services you use — a code host or issue tracker. OAuth is the preferred one-click path; a token works too. Credentials are encrypted at rest.</p>
      <Card>
        <CardHeader><CardTitle>Connect a service</CardTitle></CardHeader>
        <CardContent><ConnectService onConnected={load} /></CardContent>
      </Card>
      <div className="work-list">
        {!rows.length && <p className="muted">No integrations connected yet.</p>}
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

const POLICY_ACTIONS = ['transition', 'invoke', 'rollback', 'tool', 'command', 'egress', '*']
const LAYER_HINT: Record<string, string> = {
  factory: 'factory · org-wide service', harness: 'harness · agent tooling', charter: 'charter · repo/project',
}

// Read-only governance view for developers: the rules that actually apply to
// them, in plain language. No authoring — legibility, not control.
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
    <section className="page">
      <h2 className="page-title">Rules that apply to me</h2>
      <p className="muted">The governance rules in effect for your role ({me.role}). Read-only — proposing changes is a platform/admin action.</p>
      <Section title="What I may not do" items={denies} tone="destructive" />
      <Section title="What I'm explicitly allowed" items={allows} tone="secondary" />
    </section>
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
  const runScan = () => post('/content/scan', { text }).then(setScan).catch(fail)

  // versioned history + point-in-time reconstruction
  const [hist, setHist] = useState<any[] | null>(null)
  const [at, setAt] = useState(''), [effective, setEffective] = useState<any[] | null>(null)
  const openHist = () => api('/policies/history').then((h) => setHist(h)).catch(fail)
  const showAt = () => at && api(`/policies/at?t=${encodeURIComponent(new Date(at).toISOString())}`)
    .then(setEffective).catch(fail)

  return (
    <section className="page">
      <h2 className="page-title">Policies</h2>
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
          <div className="field-form">
            <Field label="Key"><Input className="field" placeholder="e.g. github.client_id" value={key}
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
      <p className="muted">Pick a repository to see how much of its claimed behavior is actually enforced, and where the surfaces drift.</p>
      <div className="field-form">
        <Field label="Repository">
          <Select value={repoId} onValueChange={(v) => setRepoId(v ?? '')}>
            <SelectTrigger className="field"><SelectValue placeholder="repository…" /></SelectTrigger>
            <SelectContent>{repos.map((r: any) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
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
          <div className="field-form">
            <Field label="Surface">
              <Select value={surface} onValueChange={(v) => setSurface(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{['charter', 'harness', 'code'].map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Claimed behavior"><Input className="field" placeholder="what it claims to do" value={text} onChange={(e) => setText(e.target.value)} /></Field>
            <Field label="Backed by">
              <div className="switch-row" style={{ height: '2.25rem' }}>
                <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                  <input type="checkbox" checked={hasI} onChange={(e) => setHasI(e.target.checked)} /> instruction
                </label>
                <label className="muted" style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                  <input type="checkbox" checked={hasG} onChange={(e) => setHasG(e.target.checked)} /> gate
                </label>
              </div>
            </Field>
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
      <p className="muted">{g.enforcement === 'strict'
        ? 'Strict: an action is blocked unless a rule explicitly allows it (whitelist). Refusals are audited.'
        : 'Audit: an action is allowed unless a rule denies it. Denials are audited.'}
        {' '}Higher-authority layers win; a locked (strict) rule can’t be overridden from below.</p>

      <Card>
        <CardHeader><CardTitle>Layer lattice</CardTitle></CardHeader>
        <CardContent>
          <p className="muted">Precedence runs downward — a higher layer overrides a lower one on the same action.</p>
          {(() => {
            const counts: Record<string, number> = { factory: 0, harness: 0, charter: 0 }
            for (const l of g.layers) for (const r of l.rules) if (counts[r.layer] !== undefined) counts[r.layer]++
            const rows = [['factory', 'org service'], ['harness', 'agent tooling'], ['charter', 'repo / project']]
            return (
              <div className="lattice" style={{ marginTop: '.5rem' }}>
                {rows.map(([layer, desc], i) => (
                  <div key={layer}>
                    <div className="lattice-row">
                      <span><strong>{layer}</strong> <span className="rank">{desc}</span></span>
                      <Badge variant="secondary">{counts[layer]} rule{counts[layer] === 1 ? '' : 's'}</Badge>
                    </div>
                    {i < rows.length - 1 && <div className="pl-arrow" style={{ textAlign: 'center' }}>↓ overrides</div>}
                  </div>
                ))}
              </div>
            )
          })()}
        </CardContent>
      </Card>

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
            <div key={layer.rank} style={{ marginBottom: '.8rem' }}>
              <div className="field-label">Authored by {layer.rules[0]?.author_role ?? `rank ${layer.rank}`} · rank {layer.rank}</div>
              <Table>
                <TableHeader><TableRow><TableHead>Rule</TableHead><TableHead /></TableRow></TableHeader>
                <TableBody>{layer.rules.map((p: any) => (
                  <TableRow key={p.id}>
                    <TableCell className="policy-sentence">
                      <Badge variant={p.effect === 'deny' ? 'destructive' : 'secondary'}>{p.effect}</Badge> {ruleSentence(p)}
                    </TableCell>
                    <TableCell>{p.strict && <Badge>locked</Badge>}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Overrides — where a locked rule shadows a lower layer</CardTitle></CardHeader>
        <CardContent>
          {g.overrides.length === 0
            ? <p className="muted">No overrides — no locked rule is currently shadowing a lower layer.</p>
            : g.overrides.map((o: any, i: number) => (
                <div key={i} className="policy-sentence" style={{ padding: '.3rem 0' }}>
                  <Badge>{o.winner.author_role}</Badge>’s locked <strong>{o.winner.effect}</strong> on{' '}
                  <span className="mono">{o.winner.action}/{o.winner.resource}</span> overrides{' '}
                  <Badge variant="outline">{o.shadowed.author_role}</Badge>’s <strong>{o.shadowed.effect}</strong>.
                </div>
              ))}
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

            {detail.processes.length > 0 && <div>
              <div className="field-label">Example processes</div>
              {detail.processes.map((pr: any, i: number) => (
                <div key={i} className="kv-row"><span>{pr.name} <span className="muted">({pr.archetype})</span></span>
                  <span className="mono">{(pr.stages || []).join(' → ')}</span></div>
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

            {!detail.standards.length && !detail.processes.length && !detail.artifacts.length &&
              <p className="muted">This pack has no seeded content.</p>}
          </div>
        )}
      </Drawer>
    </section>
  )
}

function Invitations({ me, roles }: any) {
  const { rows, load } = useList('/invitations')
  const myRank = roles.find((r: Role) => r.name === me.role)?.rank ?? 0
  const options = roles.filter((r: Role) => r.rank <= myRank).map((r: Role) => r.name)  // your level or lower
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
          <div className="field-form">
            <Field label="Email"><Input className="field" placeholder="new.user@acme.com" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
            <Field label="Role">
              <Select value={role} onValueChange={(v) => setRole(v ?? '')}>
                <SelectTrigger className="field"><SelectValue placeholder="role…" /></SelectTrigger>
                <SelectContent>{options.map((r: string) => <SelectItem key={r} value={r}>{r}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Expires (days)"><Input className="field" type="number" placeholder="7" value={ttl} onChange={(e) => setTtl(e.target.value)} /></Field>
            <Button onClick={invite} disabled={!email || !role}>Send invite</Button>
          </div>
          {link && <div className="kv-row"><span className="muted">invite link</span><span className="mono">{link}</span></div>}
        </CardContent>
      </Card>
      <Card><CardContent>
        <Table>
          <TableHeader><TableRow><TableHead>Email</TableHead><TableHead>Role</TableHead><TableHead>Expires</TableHead><TableHead /></TableRow></TableHeader>
          <TableBody><EmptyRow show={!rows.length} cols={4}>No pending invitations.</EmptyRow>{rows.map((i) => (
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

function Usage() {
  const [data, setData] = useState<any>(null)
  useEffect(() => { api('/usage').then(setData).catch(fail) }, [])
  const teams = data?.by_team ?? []
  return (
    <section className="page">
      <h2 className="page-title">Usage &amp; cost attribution</h2>
      <p className="muted">Units metered per governed invoke, attributed to the actor's team.</p>
      <Card>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>Team</TableHead><TableHead>Units</TableHead></TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!teams.length} cols={2}>No usage recorded yet.</EmptyRow>
              {teams.map((r: any) => (
                <TableRow key={r.team_id ?? 'unassigned'}>
                  <TableCell>{r.team}</TableCell>
                  <TableCell className="mono">{r.units}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
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
          <div className="field-form">
            <Field label="System name"><Input className="field" placeholder="e.g. checkout" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Kind">
              <Select value={kind} onValueChange={(v) => setKind(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{['service', 'microservices', 'server'].map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Button onClick={add} disabled={!name}>Create system</Button>
          </div>
          <div className="field-group" style={{ marginTop: '.75rem' }}>
            <span className="field-label">Member repositories (click to include)</span>
            <div className="toolbar">
              {repos.map((r: any) => (
                <Button key={r.id} size="sm" variant={picked.includes(r.id) ? 'default' : 'outline'}
                        onClick={() => toggle(r.id)}>{r.name}</Button>
              ))}
              {!repos.length && <span className="muted">no repositories yet — add one under Repos</span>}
            </div>
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

function RoutingPolicyEditor() {
  const [region, setRegion] = useState(''), [comp, setComp] = useState(''), [prefer, setPrefer] = useState('priority')
  useEffect(() => {
    api('/routing-policy').then((p) => {
      setRegion(p.require_region ?? ''); setComp((p.require_compliance ?? []).join(', '))
      setPrefer(p.prefer ?? 'priority')
    }).catch(() => {})
  }, [])
  const save = () => api('/routing-policy', { method: 'PUT', body: JSON.stringify({
    require_region: region, require_compliance: comp.split(',').map((s) => s.trim()).filter(Boolean), prefer,
  }) }).then(() => toast.success('routing policy saved')).catch(fail)
  return (
    <div className="field-form" style={{ marginTop: '0.6rem' }}>
      <Field label="Require region"><Input className="field" placeholder="blank = any" value={region} onChange={(e) => setRegion(e.target.value)} /></Field>
      <Field label="Require compliance"><Input className="field" placeholder="hipaa, soc2 (csv)" value={comp} onChange={(e) => setComp(e.target.value)} /></Field>
      <Field label="Prefer">
        <Select value={prefer} onValueChange={(v) => setPrefer(v ?? 'priority')}>
          <SelectTrigger className="field"><SelectValue /></SelectTrigger>
          <SelectContent>{['priority', 'cost'].map((p) => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent>
        </Select>
      </Field>
      <Button variant="secondary" size="sm" onClick={save}>Save routing policy</Button>
    </div>
  )
}

function Traffic() {
  const [g, setG] = useState<any>(null)
  useEffect(() => { api('/traffic').then(setG).catch(fail) }, [])
  const label = (id: string) => g?.nodes.find((n: any) => n.id === id)?.label ?? id
  const teamOf = (id: string) => g?.nodes.find((n: any) => n.id === id)?.team ?? ''
  const edges = g?.edges ?? []
  return (
    <section className="page">
      <h2 className="page-title">Traffic</h2>
      <p className="muted">Cross-agent traffic from the usage ledger — who sends how much to which target.</p>
      <Card>
        <CardContent>
          <Table>
            <TableHeader><TableRow><TableHead>Actor</TableHead><TableHead>Team</TableHead><TableHead>Target</TableHead><TableHead>Calls</TableHead><TableHead>Units</TableHead></TableRow></TableHeader>
            <TableBody>
              <EmptyRow show={!edges.length} cols={5}>No traffic yet.</EmptyRow>
              {edges.map((e: any, i: number) => (
                <TableRow key={i}>
                  <TableCell>{label(e.source)}</TableCell>
                  <TableCell className="mono">{teamOf(e.source)}</TableCell>
                  <TableCell>{label(e.target)}</TableCell>
                  <TableCell className="mono">{e.count}</TableCell>
                  <TableCell className="mono">{e.units}</TableCell>
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
  const [region, setRegion] = useState(''), [compliance, setCompliance] = useState(''), [cost, setCost] = useState('0')
  const addTarget = () => post('/targets', {
    name, kind, endpoint, credential: token ? { token } : null,
    region, compliance: compliance.split(',').map((s) => s.trim()).filter(Boolean), unit_cost: Number(cost) || 0,
  }).then(() => { setName(''); setEndpoint(''); setToken(''); setRegion(''); setCompliance(''); setCost('0'); loadT() }).catch(fail)
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
          <div className="field-form">
            <Field label="Name"><Input className="field" placeholder="e.g. opus" value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Kind">
              <Select value={kind} onValueChange={(v) => setKind(v ?? '')}>
                <SelectTrigger className="field"><SelectValue /></SelectTrigger>
                <SelectContent>{['model', 'mcp', 'api'].map((k) => <SelectItem key={k} value={k}>{k}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Endpoint / model id"><Input className="field" placeholder="claude-opus-4-8 / URL" value={endpoint} onChange={(e) => setEndpoint(e.target.value)} /></Field>
            <Field label="Token (optional)"><Input className="field" placeholder="API key" type="password" value={token} onChange={(e) => setToken(e.target.value)} /></Field>
            <Field label="Region"><Input className="field" placeholder="e.g. eu (optional)" value={region} onChange={(e) => setRegion(e.target.value)} /></Field>
            <Field label="Compliance tags"><Input className="field" placeholder="hipaa, soc2 (csv)" value={compliance} onChange={(e) => setCompliance(e.target.value)} /></Field>
            <Field label="Unit cost"><Input className="field" type="number" min="0" placeholder="0" value={cost} onChange={(e) => setCost(e.target.value)} /></Field>
            <Button onClick={addTarget} disabled={!name}>Add target</Button>
          </div>
          <RoutingPolicyEditor />
          <Table>
            <TableHeader><TableRow><TableHead>Name</TableHead><TableHead>Kind</TableHead><TableHead>Endpoint</TableHead><TableHead>Region</TableHead><TableHead>Compliance</TableHead><TableHead>Cost</TableHead><TableHead /></TableRow></TableHeader>
            <TableBody><EmptyRow show={!targets.length} cols={9}>No targets yet — add a model, MCP, or API target.</EmptyRow>{targets.map((t) => (
              <TableRow key={t.id}>
                <TableCell>{t.name}</TableCell>
                <TableCell><Badge variant="secondary">{t.kind}</Badge></TableCell>
                <TableCell className="mono">{t.endpoint}</TableCell>
                <TableCell className="mono">{t.region || '—'}</TableCell>
                <TableCell className="mono">{(t.compliance ?? []).join(', ') || '—'}</TableCell>
                <TableCell className="mono">{t.unit_cost || 0}</TableCell>
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
          <p className="muted">Point a process (optionally a specific step) at a target; higher priority wins, with failover to the next.</p>
          <div className="field-form">
            <Field label="Process">
              <Select value={rProc} onValueChange={(v) => setRProc(v ?? '')}>
                <SelectTrigger className="field"><SelectValue placeholder="process…" /></SelectTrigger>
                <SelectContent>{procs.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Target">
              <Select value={rTarget} onValueChange={(v) => setRTarget(v ?? '')}>
                <SelectTrigger className="field"><SelectValue placeholder="target…" /></SelectTrigger>
                <SelectContent>{targets.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Step"><Input className="field" placeholder="blank = any step" value={rStep} onChange={(e) => setRStep(e.target.value)} /></Field>
            <Field label="Priority"><Input className="field" type="number" placeholder="0" value={rPrio} onChange={(e) => setRPrio(e.target.value)} /></Field>
            <Button onClick={addRoute} disabled={!rProc || !rTarget}>Add route</Button>
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
          <div className="field-form">
            <Field label="Target">
              <Select value={qTarget} onValueChange={(v) => setQTarget(v ?? '')}>
                <SelectTrigger className="field"><SelectValue placeholder="target…" /></SelectTrigger>
                <SelectContent>{targets.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label="Limit (units)"><Input className="field" type="number" placeholder="e.g. 1000" value={qLimit} onChange={(e) => setQLimit(e.target.value)} /></Field>
            <Field label="Window (seconds)"><Input className="field" type="number" placeholder="0 = lifetime" value={qWindow} onChange={(e) => setQWindow(e.target.value)} /></Field>
            <Button onClick={addQuota} disabled={!qTarget || !qLimit}>Add quota</Button>
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

// Visibility-first home: highlight the few actionable things, drill in for detail.
export function Overview({ goto, can = () => true }: { goto: (v: any) => void; can?: (v: any) => boolean }) {
  const [items, setItems] = useState<any[]>([])
  const [pending, setPending] = useState(0)
  const [events, setEvents] = useState<any[]>([])
  useEffect(() => {
    api('/work-items').then(setItems).catch(() => {})
    api('/approvals?status=pending').then((r) => setPending(r.length)).catch(() => {})
    api('/events').then(setEvents).catch(() => {})  // 403 for some roles → stays empty
  }, [])
  const count = (recipe: string) => events.filter((e) => e.recipe === recipe).length
  const denials = count('denied')
  const failures = count('invoke-failed')
  const pendingApply = Math.max(0, count('rollback') - count('rollback-applied'))
  const byStage = items.reduce((m: Record<string, number>, w) => {
    m[w.current_stage] = (m[w.current_stage] ?? 0) + 1; return m
  }, {})

  const cards = [
    { label: 'Approvals awaiting', n: pending, go: 'approvals', attn: pending > 0, Icon: CheckSquare },
    { label: 'Work in progress', n: items.length, go: 'work', attn: false, Icon: ListChecks },
    { label: 'Policy denials', n: denials, go: 'events', attn: denials > 0, Icon: Shield },
    { label: 'Failed invokes', n: failures, go: 'events', attn: failures > 0, Icon: Activity },
    { label: 'Rollbacks to apply', n: pendingApply, go: 'work', attn: pendingApply > 0, Icon: GitBranch },
  ]
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
        <CardHeader><CardTitle>Work by stage</CardTitle></CardHeader>
        <CardContent>
          {items.length ? (
            <div className="toolbar">
              {Object.entries(byStage).map(([s, n]) => (
                <Badge key={s} variant="secondary">{s}: {n}</Badge>
              ))}
            </div>
          ) : <span className="muted">No work items yet — start one under Work.</span>}
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
  const [selId, setSelId] = useState<string | null>(null)
  const selected = rows.find((r) => r.id === selId) ?? null  // re-derive so it tracks reloads
  const stages: string[] = []
  for (const w of rows) if (!stages.includes(w.current_stage)) stages.push(w.current_stage)

  return (
    <section className="page">
      <h2 className="page-title">Work</h2>
      <p className="muted">Your work by stage. Select an item to act on it.</p>
      <div className="field-form">
        <Field label="Title"><Input className="field" placeholder="what needs doing" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="Repository">
          <Select value={repo} onValueChange={(v) => setRepo(v ?? '')}>
            <SelectTrigger className="field"><SelectValue placeholder="repo…" /></SelectTrigger>
            <SelectContent>{repos.map((r) => <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Field label="Process">
          <Select value={proc} onValueChange={(v) => setProc(v ?? '')}>
            <SelectTrigger className="field"><SelectValue placeholder="process…" /></SelectTrigger>
            <SelectContent>{procs.map((p) => <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>)}</SelectContent>
          </Select>
        </Field>
        <Button onClick={add} disabled={!title || !repo || !proc}>Ship work</Button>
      </div>

      {rows.length === 0
        ? <Card><CardContent><p className="muted">No work items yet — name one above and ship it to start the governed loop.</p></CardContent></Card>
        : (
          <div className="board">
            {stages.map((s) => (
              <div key={s} className="board-col">
                <div className="board-col-head"><span>{s}</span><Badge variant="secondary">{rows.filter((w) => w.current_stage === s).length}</Badge></div>
                {rows.filter((w) => w.current_stage === s).map((w) => (
                  <button key={w.id} className={`board-card${selId === w.id ? ' board-card-selected' : ''}`} onClick={() => setSelId(w.id)}>
                    <div className="work-title">{w.title}</div>
                  </button>
                ))}
              </div>
            ))}
          </div>
        )}

      <Drawer open={!!selected} title={selected?.title ?? ''} onClose={() => setSelId(null)}>
        {selected && <WorkRow bare w={selected} onMove={move} onAttest={attest}
                              onRequest={requestApproval} onReload={load} />}
      </Drawer>
    </section>
  )
}

function WorkRow({ w, onMove, onAttest, onRequest, onReload, bare }: any) {
  const [to, setTo] = useState(''), [check, setCheck] = useState('')
  const [pm, setPm] = useState<any>(null)
  const [hist, setHist] = useState<any>(null), [rbTo, setRbTo] = useState(''), [plan, setPlan] = useState<any>(null)
  const [logs, setLogs] = useState<any[] | null>(null)
  // live log tail: subscribe to WS-relayed log lines for this item while open
  useEffect(() => {
    if (logs === null) return
    const onLog = (e: any) => { if (e.detail.subject === w.id) setLogs((ls) => [...(ls ?? []), e.detail]) }
    window.addEventListener('oref-log', onLog)
    return () => window.removeEventListener('oref-log', onLog)
  }, [logs === null, w.id])
  const showLogs = () => logs ? setLogs(null)
    : api(`/work-items/${w.id}/logs`).then((l) => setLogs(l)).catch(fail)
  const markApplied = (status: string) => post(`/work-items/${w.id}/rollback/applied`, { status })
    .then(() => { toast.success(`rollback ${status}`); return api(`/work-items/${w.id}/history`).then(setHist) }).catch(fail)
  const runPm = () => pm ? setPm(null)
    : api(`/work-items/${w.id}/postmortem`).then(setPm).catch(fail)
  const showHist = () => hist ? (setHist(null), setPlan(null))
    : api(`/work-items/${w.id}/history`).then((h) => { setHist(h); setRbTo(h.rollback_targets[0] ?? '') }).catch(fail)
  const rollback = () => post(`/work-items/${w.id}/rollback`, { to: rbTo })
    .then((r) => {
      setPlan(r.plan); toast.success(`rolled back to ${rbTo}`); onReload?.()
      return api(`/work-items/${w.id}/history`).then((h) => { setHist(h); setRbTo(h.rollback_targets[0] ?? '') })
    }).catch(fail)
  return (
    <Card>
      <CardContent>
        <div className="work-head">
          {!bare && <span className="work-title">{w.title}</span>}
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
          <Button variant="outline" size="sm" onClick={showHist}>{hist ? 'Hide history' : 'History'}</Button>
          <Button variant="outline" size="sm" onClick={showLogs}>{logs ? 'Hide logs' : 'Logs'}</Button>
        </div>
        {logs && (
          <div className="mono" style={{ marginTop: '0.6rem', borderTop: '1px solid var(--border)', paddingTop: '0.6rem', maxHeight: '12rem', overflow: 'auto' }}>
            {logs.length ? logs.map((l: any, i: number) => (
              <div key={i} className={l.level === 'error' ? 'log-error' : 'muted'}>{l.at?.slice(11, 19)} [{l.level}] {l.line}</div>
            )) : <span className="muted">no logs yet — lines stream here live</span>}
          </div>
        )}
        {hist && (
          <div style={{ marginTop: '0.6rem', borderTop: '1px solid var(--border)', paddingTop: '0.6rem' }}>
            <Pipeline
              stages={hist.history.filter((h: any) => h.kind !== 'rollback-applied')
                .map((h: any) => h.stage).filter((s: string, i: number, a: string[]) => a.indexOf(s) === i)}
              current={w.current_stage} />
            <div className="mono" style={{ marginTop: '.3rem' }}>timeline: {hist.history.map((h: any) => h.kind === 'rollback' ? `↩ ${h.stage}` : h.kind === 'rollback-applied' ? `✓applied(${h.changes?.status})` : h.stage).join(' → ') || '—'}</div>
            {hist.rollback_targets.length > 0 ? (
              <div className="work-actions" style={{ marginTop: '0.4rem' }}>
                <span className="muted">roll back to</span>
                <Select value={rbTo} onValueChange={(v) => setRbTo(v ?? '')}>
                  <SelectTrigger className="field"><SelectValue placeholder="stage…" /></SelectTrigger>
                  <SelectContent>{hist.rollback_targets.map((s: string) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                </Select>
                <Button variant="destructive" size="sm" onClick={rollback} disabled={!rbTo}>Roll back</Button>
              </div>
            ) : <div className="muted" style={{ marginTop: '0.3rem' }}>no prior stage to roll back to</div>}
            {plan && (
              <div style={{ marginTop: '0.4rem' }}>
                <div className="muted">reverse plan (for the harness to apply):</div>
                <div className="kv-row"><span className="muted">code</span><span className="mono">{plan.code ? `revert → ${plan.code.revert_to}` : '—'}</span></div>
                <div className="kv-row"><span className="muted">migrations</span><span className="mono">{plan.migrations.map((m: any) => `↓ ${m.downgrade}`).join(', ') || '—'}</span></div>
                {Object.entries(plan).filter(([k]) => k !== 'code' && k !== 'migrations').map(([cat, m]: any) => (
                  <div key={cat} className="kv-row"><span className="muted">{cat}</span><span className="mono">{Object.entries(m).map(([k, v]) => `${k}→${v}`).join(', ') || '—'}</span></div>
                ))}
                <div className="work-actions" style={{ marginTop: '0.4rem' }}>
                  <span className="muted">harness applied it?</span>
                  <Button variant="secondary" size="sm" onClick={() => markApplied('applied')}>Mark applied</Button>
                  <Button variant="outline" size="sm" onClick={() => markApplied('failed')}>Mark failed</Button>
                </div>
              </div>
            )}
          </div>
        )}
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
                <Pipeline stages={r.required_roles} current={next ?? undefined} />
                <div className="work-actions">
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

function Metrics() {
  const [m, setM] = useState<any>(null)
  const [ga, setGa] = useState<any>(null)
  const [names, setNames] = useState<Record<string, string>>({})
  useEffect(() => {
    api('/metrics').then(setM).catch(fail)
    api('/governance/analysis').then(setGa).catch(() => {})
    // resolve actor ids → emails when permitted (platform/admin); dev falls back to short id
    api('/users').then((us: any[]) => setNames(Object.fromEntries(us.map((u) => [u.id, u.email])))).catch(() => {})
  }, [])
  if (!m) return null
  const panels = [
    { title: 'WIP by step', data: m.wip_by_stage, accent: 'accent-blue', actor: false },
    { title: 'Events', data: m.event_counts, accent: 'accent-green', actor: false },
    { title: 'Activity by actor', data: m.activity_by_actor, accent: 'accent-purple', actor: true },
    { title: 'Lead times', data: m.lead_times, accent: 'accent-orange', actor: false },
  ]
  const keyLabel = (p: any, k: string) => p.actor ? (names[k] ?? `${k.slice(0, 8)}…`) : humanKey(k)
  return (
    <section className="page">
      <h2 className="page-title">Metrics</h2>
      <div className="metric-grid">
        {panels.map((p) => (
          <Card key={p.title} className={p.accent}>
            <CardHeader><CardTitle>{p.title}</CardTitle></CardHeader>
            <CardContent>
              {Object.entries(p.data).map(([k, v]) => (
                <div key={k} className="kv-row"><span>{keyLabel(p, k)}</span><b>{String(v)}</b></div>
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
