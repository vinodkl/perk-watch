import React from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'

type Credit = { transaction_id: string; date: string; amount_minor: number }
type Period = {
  label: string; start: string; end: string; amount_minor: number; used_minor: number
  status: 'used' | 'partial' | 'missed' | 'pending' | 'unmarked' | 'at_risk' | 'open'; credits: Credit[]; marked: boolean
}
type Benefit = {
  benefit_id: string; card_id: string; card: string; title: string; period: string; tracking: 'auto' | 'manual'
  category: string; current: Period & { days_left: number; remaining_minor: number }; periods: Period[]
  ytd: { captured_minor: number; missed_minor: number }; terms: string
}
type Tracker = {
  as_of: string; data_through: Record<string, string | null>
  totals: { captured_minor: number; missed_minor: number; at_risk_minor: number }; benefits: Benefit[]
}
type Tip = { tip: string; source_url: string; source_title?: string; source_date?: string; last_verified?: string }
type Step = { tool: string; args: Record<string, unknown>; summary: string }
type Proposal = { benefit_id: string; title: string; period_start: string; period_label: string; amount: number }
type Reply = { answer: string; tool_trace: Step[]; unverified_amounts: string[]; amounts_checked: number; model: string; proposals?: Proposal[] }
type Msg = { role: 'user' | 'assistant'; content: string; reply?: Reply; pending?: boolean }

const PERIODS = ['monthly', 'quarterly', 'semiannual', 'annual'] as const
const PERIOD_NAME: Record<string, string> = { monthly: 'Monthly', quarterly: 'Quarterly', semiannual: 'Semi-annual', annual: 'Annual' }
const PERIOD_UNIT: Record<string, string> = { monthly: 'month', quarterly: 'quarter', semiannual: 'half', annual: 'year' }
const GLYPH: Partial<Record<Period['status'], string>> = { used: '✓', missed: '✕', unmarked: '?' }
const STATUS_WORD: Record<Period['status'], string> = { used: 'used', partial: 'partly used', missed: 'missed', pending: 'waiting for statement', unmarked: 'not marked', at_risk: 'at risk', open: 'open' }
const cardPriority = (card: string) => /amex|american express/i.test(card) ? 0 : /chase/i.test(card) ? 1 : 2
const money = (minor?: number | null) => minor == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: minor % 100 ? 2 : 0, maximumFractionDigits: 2 }).format(minor / 100)
const fmtDate = (value?: string | null) => value ? new Date(`${value}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'date unavailable'
const greeting = () => { const h = new Date().getHours(); return h < 12 ? 'Morning' : h < 18 ? 'Afternoon' : 'Evening' }
const chatStore = new Map<string, Msg[]>()

async function api<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, body === undefined ? undefined : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw Error(data.detail || `Request failed (${response.status})`)
  return data as T
}

function Sparkle() { return <span className="sparkle" aria-hidden="true">✨</span> }

function CountUp({ value }: { value: number }) {
  const [shown, setShown] = React.useState(value)
  React.useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { setShown(value); return }
    const started = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const progress = Math.min(1, (now - started) / 650)
      setShown(Math.round(value * progress))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    setShown(0)
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])
  return <>{money(shown)}</>
}

function App() {
  const params = new URLSearchParams(location.search)
  const [tracker, setTracker] = React.useState<Tracker | null>(null)
  const [error, setError] = React.useState('')
  const [asOf, setAsOf] = React.useState(params.get('as_of') || '')
  const [benefitId, setBenefitId] = React.useState(params.get('benefit') || '')
  const [askOpen, setAskOpen] = React.useState(false)
  const [askQuestion, setAskQuestion] = React.useState<{ text: string; id: number } | undefined>()
  const [filter, setFilter] = React.useState<'all' | 'missed' | 'manual'>('all')
  const [view, setView] = React.useState<'wallet' | 'evals'>(params.get('view') === 'evals' ? 'evals' : 'wallet')
  function changeView(next: 'wallet' | 'evals') {
    setView(next)
    const url = new URL(location.href)
    next === 'evals' ? url.searchParams.set('view', 'evals') : url.searchParams.delete('view')
    history.pushState(null, '', url)
  }
  const reload = React.useCallback(() => api<Tracker>(`/api/tracker${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''}`)
    .then(t => { setTracker(t); setError('') }).catch(e => setError(e.message)), [asOf])
  React.useEffect(() => { reload() }, [reload])
  React.useEffect(() => {
    const syncRoute = () => setBenefitId(new URLSearchParams(location.search).get('benefit') || '')
    window.addEventListener('popstate', syncRoute)
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])
  function openBenefit(id: string) {
    setBenefitId(id)
    const url = new URL(location.href); url.searchParams.set('benefit', id); history.pushState(null, '', url)
  }
  function closeBenefit() {
    setBenefitId('')
    const url = new URL(location.href); url.searchParams.delete('benefit'); history.pushState(null, '', url)
  }
  function changeDate(value: string) {
    setAsOf(value)
    const url = new URL(location.href)
    value ? url.searchParams.set('as_of', value) : url.searchParams.delete('as_of')
    history.replaceState(null, '', url)
  }
  if (error) return <main className="message"><h1>PerkWatch</h1><p>{error}. Start the API with <code>uv run --extra ui python scripts/serve.py</code>.</p></main>
  if (!tracker) return <main className="message">Loading your wallet…</main>

  const atRisk = tracker.benefits.filter(b => b.current.status === 'at_risk').sort((a, b) => b.current.remaining_minor - a.current.remaining_minor)
  const cards = [...new Set(tracker.benefits.map(b => b.card))].sort((a, b) => cardPriority(a) - cardPriority(b))
  const through = Object.values(tracker.data_through).filter((x): x is string => !!x).sort()
  const stale = through.length > 0 && through[0] < tracker.as_of
  const keep = (b: Benefit) => filter === 'all' || (filter === 'missed' && b.ytd.missed_minor > 0) || (filter === 'manual' && b.tracking === 'manual')
  const selected = tracker.benefits.find(b => b.benefit_id === benefitId)

  return <>
    <header className="topbar"><div className="brand"><span className="mark">⌕</span><b>PerkWatch</b></div><div className="head-actions">
      <button className={`nav-tab ${view === 'evals' ? 'on' : ''}`} onClick={() => changeView(view === 'evals' ? 'wallet' : 'evals')}>⚙ Evals</button>
      <label className="date-pill">AS OF <input aria-label="As of date" type="date" value={asOf || tracker.as_of} onChange={e => changeDate(e.target.value)} /></label><span className="avatar">VN</span></div></header>
    {view === 'evals' ? <EvalsAdmin/> : <main className="wallet-layout">
      <aside className="wallet-column">
        <div className="wallet-intro"><h1>{greeting()}, Vinod.</h1><p>{atRisk.length ? <>{atRisk.length} credit{atRisk.length === 1 ? '' : 's'} expire{atRisk.length === 1 ? 's' : ''} in the next few days. Here's what's left and what slipped by.</> : <>Nothing is about to expire. Here's how your credits are tracking this year.</>}</p></div>
        <div className="card-stack" aria-label="Your cards">{cards.slice(0, 2).map((card, i) => <article className={`bank-card bank-card-${i}`} key={card}><span className="chip"/><b>{card}</b><small>{tracker.benefits.filter(b => b.card === card).length} CREDITS</small></article>)}</div>
        <section className="wallet-summary">
          <div className="provenance"><span className="source statements">FROM YOUR STATEMENTS</span></div>
          <p>At risk now <b className="orange-text"><CountUp value={tracker.totals.at_risk_minor}/></b></p>
          <p>Missed this year <b className="mustard-text"><CountUp value={tracker.totals.missed_minor}/></b></p>
          <p>Captured this year <b className="green-text"><CountUp value={tracker.totals.captured_minor}/></b></p>
          <a href="#perks" className="perks-link">Perks &amp; protections <b>listed, not tracked →</b></a>
          {stale && <div className="stale-warning">Statements end {fmtDate(through[0])}. Credits posted after that aren't counted yet.</div>}
          <div className="card-dates">{cards.map(card => { const id = tracker.benefits.find(b => b.card === card)!.card_id; return <p key={card}><b>{card}</b><span>through {fmtDate(tracker.data_through[id])}</span></p> })}</div>
        </section>
        <Legend/>
      </aside>
      <section className="briefing">
        <div className="welcome"><span className="eyebrow">BENEFITS · {cards.length} CARDS · {tracker.benefits.length} CREDITS</span>
          <h2>{atRisk.length ? `${money(tracker.totals.at_risk_minor)} is about to expire.` : 'Your credits at a glance.'}</h2>
          <p>{tracker.totals.missed_minor ? `You've let ${money(tracker.totals.missed_minor)} slip by so far this year. Let's not add to it.` : 'Nothing missed so far this year.'}</p></div>
        <AskDock tracker={tracker} hidden={askOpen || !!selected} onOpen={() => setAskOpen(true)}
          onAsk={text => { setAskQuestion({ text, id: Date.now() }); setAskOpen(true) }}/>
        <Briefing tracker={tracker}/>
        {!!atRisk.length && <section className="group expiring"><h2 className="eyebrow">EXPIRING SOON · {atRisk.length} <span className="source statements">FROM STATEMENTS</span></h2><div className="coupon-list">{atRisk.map(b => <Coupon key={b.benefit_id} benefit={b} onOpen={openBenefit}/>)}</div></section>}
        <div className="filter-row">{(['all', 'missed', 'manual'] as const).map(f => <button key={f} className={`filter-chip ${filter === f ? 'on' : ''}`} onClick={() => setFilter(f)}>{{ all: 'All credits', missed: 'Missed something', manual: 'Manually tracked' }[f]}</button>)}</div>
        {cards.map(card => {
          const list = tracker.benefits.filter(b => b.card === card && keep(b))
          if (!list.length) return null
          const left = list.reduce((sum, b) => sum + b.current.remaining_minor, 0)
          return <section className="group card-group" key={card}><h2 className="eyebrow card-eyebrow"><span>{card.toUpperCase()}</span><span>{money(left)} LEFT THIS PERIOD</span></h2>
            {PERIODS.map(period => {
              const items = list.filter(b => b.period === period)
              if (!items.length) return null
              return <div className="period-block" key={period}><div className="period-head"><span>{PERIOD_NAME[period]}</span><span>resets in {items[0].current.days_left} days</span></div>
                <div className="benefit-grid">{items.map(b => <BenefitStub key={b.benefit_id} benefit={b} onOpen={openBenefit}/>)}</div></div>
            })}
          </section>
        })}
        <section className="perks-strip" id="perks"><span>◇</span><div><b>Perks &amp; protections</b><small>Lounge access, insurance and status perks are listed in your terms but not tracked as credits.</small></div></section>
      </section>
    </main>}
    {selected && <BenefitRail benefit={selected} asOf={tracker.as_of} dataThrough={tracker.data_through[selected.card_id]} onClose={closeBenefit} onChanged={reload}/>}
    {askOpen && <AskRail asOf={tracker.as_of} suggestions={askSuggestions(tracker)} initialQuestion={askQuestion}
      onChanged={reload} onClose={() => { setAskOpen(false); setAskQuestion(undefined) }}/>}
  </>
}

// One request per as-of date and totals: StrictMode's double effects and re-renders reuse the same promise.
const briefingCache = new Map<string, Promise<Reply>>()

function Briefing({ tracker }: { tracker: Tracker }) {
  const key = `${tracker.as_of}|${JSON.stringify(tracker.totals)}`
  const [state, setState] = React.useState<{ reply?: Reply; error?: string }>({})
  React.useEffect(() => {
    let live = true
    setState({})
    if (!briefingCache.has(key)) briefingCache.set(key, api<Reply>(`/api/briefing?as_of=${encodeURIComponent(tracker.as_of)}`))
    briefingCache.get(key)!.then(reply => { if (live) setState({ reply }) },
      e => { briefingCache.delete(key); if (live) setState({ error: e instanceof Error ? e.message : String(e) }) })
    return () => { live = false }
  }, [key])
  return <section className="ai-plan" aria-live="polite">
    <h2 className="eyebrow">THIS WEEK'S PLAN <span className="source ai">AI-WRITTEN</span></h2>
    {state.error ? <p className="ai-plan-off">The AI plan is unavailable ({state.error}). Everything else on this page comes from your statements.</p>
      : !state.reply ? <p className="ai-plan-loading">Reading your credits and writing a plan…</p>
      : <><Markdown text={state.reply.answer}/><AgentTrace reply={state.reply} emptyNote="written from your wallet, no tools needed"/></>}
  </section>
}

function askSuggestions(t: Tracker): string[] {
  const risk = t.benefits.filter(b => b.current.status === 'at_risk').sort((a, b) => b.current.remaining_minor - a.current.remaining_minor)[0]
  const missed = [...t.benefits].sort((a, b) => b.ytd.missed_minor - a.ytd.missed_minor)[0]
  const manual = t.benefits.find(b => b.tracking === 'manual' && !b.current.marked && b.current.remaining_minor > 0)
  return [
    'What should I use this week?',
    risk && `How do I use ${risk.title} before ${fmtDate(risk.current.end)}?`,
    missed?.ytd.missed_minor && `Why do I keep missing ${missed.title}, and what would help?`,
    manual && `I used my ${manual.title} this ${PERIOD_UNIT[manual.period]}`,
    'Which credit covers airport security fast lanes?',
  ].filter((s): s is string => !!s)
}

function AskDock({ tracker, hidden, onOpen, onAsk }: { tracker: Tracker; hidden: boolean; onOpen: () => void; onAsk: (question: string) => void }) {
  const [draft, setDraft] = React.useState('')
  const [collapsed, setCollapsed] = React.useState(false)
  const hero = React.useRef<HTMLElement>(null)
  React.useEffect(() => {
    if (hidden || !hero.current) { setCollapsed(false); return }
    const observer = new IntersectionObserver(([entry]) => setCollapsed(!entry.isIntersecting), { threshold: 0.05 })
    observer.observe(hero.current)
    return () => observer.disconnect()
  }, [hidden])
  if (hidden) return null
  const atRisk = tracker.benefits.filter(b => b.current.status === 'at_risk').length
  const chips = askSuggestions(tracker).slice(0, 2)
  const submit = (question: string) => { if (question.trim()) { onAsk(question.trim()); setDraft('') } }
  return <>
    <section className="ask-agent-hero" ref={hero}>
      <div className="ask-dock-head">
        <span className="eyebrow"><Sparkle/> ASK PERKWATCH · AI AGENT</span>
        {atRisk > 0 && <span className="ask-dock-badge">{atRisk} EXPIRING</span>}
      </div>
      <p className="ask-dock-subtitle">Your wallet-aware agent for deciding what to use, what counts, and what to do next.</p>
      <form className="ask-dock-form" onSubmit={e => { e.preventDefault(); submit(draft) }}>
        <input value={draft} onChange={e => setDraft(e.target.value)} placeholder="Ask about any credit…" maxLength={2000}/>
        <button disabled={!draft.trim()} aria-label="Ask">→</button>
      </form>
      <div className="ask-dock-chips">{chips.map(s => <button key={s} className="ask-dock-chip" title={s} onClick={() => submit(s)}>{s}</button>)}</div>
      <small className="ask-dock-trust">Amounts and dates come from your tracker, not the model.</small>
    </section>
    {collapsed && <button className={`ask-launcher ${collapsed ? 'visible' : ''}`} onClick={onOpen} aria-label="Open Ask PerkWatch">
      <span><Sparkle/></span><b>Ask PerkWatch</b>{atRisk > 0 && <em>{atRisk}</em>}
    </button>}
  </>
}

function Legend() {
  const items: [Period['status'], string][] = [['used', 'used'], ['partial', 'partly used'], ['missed', 'missed'], ['at_risk', 'at risk'], ['open', 'open'], ['unmarked', 'manual, not marked'], ['pending', 'waiting for statement']]
  return <div className="legend">{items.map(([status, label]) => <span key={status}><i className={`dot ${status}`}>{GLYPH[status]}</i>{label}</span>)}
    <p className="ai-note"><Sparkle/> marks AI-written parts. Amounts and statuses are computed from your statements. AI writes the weekly plan, answers questions and summarizes community tips, and every dollar amount it writes is checked against your data.</p>
  </div>
}

type TrackerCase = { name: string; as_of: string; periods: number; benefits: string[] }
type RetrievalCase = { question: string; expects: string }
type ChatCase = { id: string; question: string; checks: string[]; expects: string }
type EvalSuiteState = {
  title: string; description: string; rerunnable: boolean; network: boolean; call_estimate: number | null
  cases: TrackerCase[] | RetrievalCase[] | ChatCase[]
  status: 'idle' | 'running' | 'done' | 'error'; result: Record<string, unknown> | null
  started_at: number | null; finished_at: number | null; error: string | null
}
type EvalsSnapshot = Record<string, EvalSuiteState>

function evalSummary(name: string, result: Record<string, any>): string {
  if (name === 'tracker') {
    const s = result.synthetic
    return `${s.periods} periods · status ${Math.round(s.status_accuracy * 100)}% · amount ${Math.round(s.amount_accuracy * 100)}% · ${s.mismatches.length} mismatch${s.mismatches.length === 1 ? '' : 'es'}`
  }
  if (name === 'chat') return `${result.passed}/${result.cases} checks passed · judge ${result.mean_judge_score ?? '—'}/5`
  return JSON.stringify(result)
}

function CaseList({ name, cases }: { name: string; cases: TrackerCase[] | RetrievalCase[] | ChatCase[] }) {
  if (name === 'tracker') return <ul className="admin-cases">{(cases as TrackerCase[]).map(c => <li key={c.name}>
    <b>{c.name}</b> <span className="admin-case-meta">as of {c.as_of} · {c.periods} periods</span>
    <span className="admin-case-detail">{c.benefits.join(', ')}</span></li>)}</ul>
  if (name === 'retrieval') return <ul className="admin-cases">{(cases as RetrievalCase[]).map(c => <li key={c.question}>
    <b>“{c.question}”</b> <span className="admin-case-meta">→ expects {c.expects}</span></li>)}</ul>
  return <ul className="admin-cases">{(cases as ChatCase[]).map(c => <li key={c.id}>
    <b>{c.id}</b> <span className="admin-case-meta">{c.expects}</span>
    <span className="admin-case-detail">“{c.question}” · checks: {c.checks.join(', ')}</span></li>)}</ul>
}

function EvalsAdmin() {
  const [snapshot, setSnapshot] = React.useState<EvalsSnapshot | null>(null)
  const [confirmName, setConfirmName] = React.useState<string | null>(null)
  const [openPanels, setOpenPanels] = React.useState<Set<string>>(new Set())
  React.useEffect(() => {
    let live = true
    const poll = () => api<EvalsSnapshot>('/api/admin/evals').then(s => { if (live) setSnapshot(s) }).catch(() => {})
    poll()
    const id = setInterval(poll, 1500)
    return () => { live = false; clearInterval(id) }
  }, [])
  function run(name: string) {
    setConfirmName(null)
    api<EvalSuiteState>(`/api/admin/evals/${name}/run`, {}).then(state => setSnapshot(s => s && { ...s, [name]: state })).catch(() => {})
  }
  function toggle(key: string) {
    setOpenPanels(open => { const next = new Set(open); next.has(key) ? next.delete(key) : next.add(key); return next })
  }
  if (!snapshot) return <main className="admin-shell"><p className="admin-loading">Loading eval suites…</p></main>
  return <main className="admin-shell">
    <div className="admin-head">
      <span className="eyebrow">EVALS · SYNTHETIC FIXTURES ONLY</span>
      <h2>Eval suites</h2>
      <p>The suites the capstone write-up cites. Reruns here always use synthetic data, never your real statements.</p>
    </div>
    <div className="admin-grid">
      {Object.entries(snapshot).map(([name, suite]) => <div className="admin-card" key={name}>
        <div className="admin-card-head"><b>{suite.title}</b><span className={`status-pill status-${suite.status}`}>{suite.status}</span></div>
        <p className="admin-desc">{suite.description}</p>
        <div className="admin-meta">
          <span>{suite.network ? (suite.call_estimate ? `~${suite.call_estimate} OpenAI calls` : 'needs real data') : 'no network · free'}</span>
          {!!suite.finished_at && <span>last run {new Date(suite.finished_at * 1000).toLocaleTimeString()}</span>}
        </div>
        {!!suite.result && <p className="admin-summary">{evalSummary(name, suite.result)}</p>}
        {!!suite.error && <p className="admin-error">⚠ {suite.error}</p>}
        <div className="admin-actions">
          {suite.rerunnable
            ? confirmName === name
              ? <span className="admin-confirm">Run ~{suite.call_estimate ?? 0} OpenAI calls?
                  <button onClick={() => run(name)}>Confirm</button>
                  <button className="ghost" onClick={() => setConfirmName(null)}>Cancel</button></span>
              : <button disabled={suite.status === 'running'}
                  onClick={() => suite.network ? setConfirmName(name) : run(name)}>{suite.status === 'running' ? 'Running…' : 'Rerun'}</button>
            : <span className="admin-cli-only">CLI only: <code>uv run python evals/run.py --suite {name} --real</code></span>}
          <button className="ghost" onClick={() => toggle(`${name}:cases`)}>{openPanels.has(`${name}:cases`) ? 'Hide cases' : `Cases (${suite.cases.length})`}</button>
          {!!suite.result && <button className="ghost" onClick={() => toggle(`${name}:raw`)}>{openPanels.has(`${name}:raw`) ? 'Hide raw' : 'Raw JSON'}</button>}
        </div>
        {openPanels.has(`${name}:cases`) && <CaseList name={name} cases={suite.cases}/>}
        {openPanels.has(`${name}:raw`) && <pre className="admin-raw">{JSON.stringify(suite.result, null, 1)}</pre>}
      </div>)}
    </div>
  </main>
}

function Dots({ periods, large, onToggle }: { periods: Period[]; large?: boolean; onToggle?: (p: Period) => void }) {
  return <span className={`dots ${large ? 'large' : ''}`}>{periods.map(p => {
    const dot = <i className={`dot ${p.status}`} title={`${p.label}: ${STATUS_WORD[p.status]} · ${money(p.used_minor)} of ${money(p.amount_minor)}`}>{GLYPH[p.status]}</i>
    if (!large) return <React.Fragment key={p.start}>{dot}</React.Fragment>
    return <button key={p.start} className="dot-cell" disabled={!onToggle} onClick={() => onToggle?.(p)}>{dot}<small>{p.label}</small></button>
  })}</span>
}

function historyLine(b: Benefit) {
  if (b.tracking === 'manual') return 'Paid inside the app, so statements never show it. Mark it once you have used it.'
  const past = b.periods.slice(0, -1)
  if (!past.length) return 'First period of the year.'
  const used = past.filter(p => p.status === 'used').length
  const unit = PERIOD_UNIT[b.period]
  return `Used ${used} of ${past.length} past ${unit}${past.length === 1 ? '' : 's'}${b.ytd.missed_minor ? ` · ${money(b.ytd.missed_minor)} missed so far` : ''}.`
}

function Coupon({ benefit: b, onOpen }: { benefit: Benefit; onOpen: (id: string) => void }) {
  const c = b.current
  return <article className="coupon"><div className="coupon-main"><h3>{b.title}</h3>
    <p className="coupon-subtitle">{b.card} · {money(c.used_minor)} of {money(c.amount_minor)} used this {PERIOD_UNIT[b.period]}</p>
    {b.periods.length > 1 && <div className="coupon-dots"><Dots periods={b.periods}/></div>}
    <p className="coupon-reason">{historyLine(b)}</p>
    <div className="coupon-actions"><button onClick={() => onOpen(b.benefit_id)}><Sparkle/> Help me use {money(c.remaining_minor)}</button></div></div>
    <div className="coupon-stub"><span className="days-stamp"><b>{c.days_left}</b><small>DAYS LEFT</small></span><strong><CountUp value={c.remaining_minor}/></strong><small>left to claim</small></div></article>
}

function BenefitStub({ benefit: b, onOpen }: { benefit: Benefit; onOpen: (id: string) => void }) {
  const c = b.current
  const pct = Math.min(100, Math.round(100 * c.used_minor / c.amount_minor))
  return <article className={`benefit-stub ${c.status}`} onClick={() => onOpen(b.benefit_id)}>
    <div className="stub-top"><b>{b.title}</b>{c.status === 'used' ? <i className="used-stamp">USED</i> : c.status === 'at_risk' ? <em>{c.days_left}d left</em> : b.tracking === 'manual' ? <em className="manual">manual</em> : null}</div>
    <div className="stub-bottom">{b.periods.length > 1 && <Dots periods={b.periods}/>}<span className="usage-track slim"><span style={{ width: `${pct}%` }}/></span><span className={`stub-amount ${pct >= 100 ? 'full' : ''}`}>{money(c.used_minor)} / {money(c.amount_minor)}</span></div>
  </article>
}

function BenefitRail({ benefit: b, asOf, dataThrough, onClose, onChanged }: { benefit: Benefit; asOf: string; dataThrough: string | null; onClose: () => void; onChanged: () => void }) {
  const c = b.current
  const credits = b.periods.flatMap(p => p.credits.map(credit => ({ ...credit, label: p.label })))
  const nextMove = c.remaining_minor > 0
    ? `Claim ${money(c.remaining_minor)} from this benefit before ${fmtDate(c.end)}.`
    : `This benefit is fully used for the current ${PERIOD_UNIT[b.period]}.`
  async function toggle(p: Period) {
    await api(`/api/benefits/${encodeURIComponent(b.benefit_id)}/mark`, { period_start: p.start, as_of: asOf })
    onChanged()
  }
  return <>
    <button className="rail-scrim" aria-label="Close benefit" onClick={onClose}/>
    <aside className="evidence-rail benefit-guide-rail" aria-label={b.title}><header><b><Sparkle/> Benefit Guide <small>{b.card}</small></b><button onClick={onClose} aria-label="Close">×</button></header>
      <div className="rail-content">
        <section className="chat-card">
          <Chat storeKey={b.benefit_id} endpoint={`/api/benefits/${encodeURIComponent(b.benefit_id)}/chat`} asOf={asOf}
            suggestions={b.tracking === 'manual' && !c.marked ? ['I already used this one', 'What counts for this credit?', 'Any tips for next period?']
              : c.remaining_minor > 0 ? ['How can I use what is left before it resets?', 'What counts for this credit?', 'Is this worth it for me?'] : ['What counts for this credit?', 'Any tips for next period?']}
            placeholder={`Ask anything about ${b.title}…`} emptyNote="answered from this benefit's context, no tools needed"
            composerNote="Amounts come from your statements, not the model." onChanged={onChanged}
            intro={<div className="benefit-guide-intro">
              <div className="benefit-guide-title"><div><h2>{b.title}</h2><p>{PERIOD_NAME[b.period]} · {b.tracking === 'manual' ? 'tracked by you' : 'tracked from statement credits'}</p></div>
                <strong>{c.days_left} days left</strong></div>
              <section className="best-next-move"><small><Sparkle/> BEST NEXT MOVE</small><h3>{nextMove}</h3>
                <p>Ask for eligible ways to use it, or compare practical community ideas with the official terms.</p></section>
              <details className="benefit-guide-section community-section" open><summary><span><b>Community ideas</b><small>Practical tips · not official terms</small></span><span className="toggle-indicator" aria-hidden="true">⌄</span></summary>
                <Community benefitId={b.benefit_id}/>
              </details>
              <details className="benefit-guide-section benefit-details"><summary><span><b>Benefit details</b><small>Usage and statement history</small></span><span className="toggle-indicator" aria-hidden="true">⌄</span></summary>
                <section className="receipt"><h3>{c.label} · CURRENT PERIOD</h3><p>{fmtDate(c.start)} – {fmtDate(c.end)} · STATEMENTS THROUGH {fmtDate(dataThrough)}</p>
                  <Dots periods={b.periods} large onToggle={b.tracking === 'manual' ? toggle : undefined}/>
                  {b.tracking === 'manual' && <p className="rail-hint">Tap a period to mark it used (or unmark it).</p>}
                  <div className="receipt-line"><span>THIS {PERIOD_UNIT[b.period].toUpperCase()}</span><b>{money(c.amount_minor)}</b></div>
                  {credits.map(credit => <div className="receipt-line" key={credit.transaction_id}><span>{fmtDate(credit.date)} statement credit <i>{credit.label}</i></span><b>−{money(credit.amount_minor)}</b></div>)}
                  {!credits.length && b.tracking === 'auto' && <div className="receipt-line"><span>No statement credits yet this year</span><b>—</b></div>}
                  <div className="receipt-line"><span>MISSED THIS YEAR</span><b className="mustard-text">{money(b.ytd.missed_minor)}</b></div>
                  <div className="receipt-total"><b>{c.status === 'at_risk' ? `LEFT · ${c.days_left} DAYS` : 'LEFT TO CLAIM'}</b><strong>{money(c.remaining_minor)}</strong></div>
                </section>
              </details>
              <details className="benefit-guide-section fine-print"><summary><span><b>Fine print</b><small>Official terms</small></span><span className="toggle-indicator" aria-hidden="true">⌄</span></summary><p>{b.terms || 'No terms text in prepared data.'}</p></details>
            </div>}/></section>
      </div>
    </aside>
  </>
}

function Community({ benefitId }: { benefitId: string }) {
  const [data, setData] = React.useState<{ blurb: string; tips: Tip[] } | null>(null)
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    setData(null); setError('')
    api<{ blurb: string; tips: Tip[] }>(`/api/benefits/${encodeURIComponent(benefitId)}/community`).then(setData).catch(e => setError(e.message))
  }, [benefitId])
  return <article className="community-note"><small>WHAT THE COMMUNITY DOES <b>NOT OFFICIAL TERMS</b></small>
    {error ? <p>{error}</p> : !data ? <p>Reading community tips…</p> : !data.tips.length ? <p>No community tips collected for this benefit yet.</p> : <>
      {data.blurb && <><span className="source ai">AI SUMMARY OF THE TIPS BELOW</span><p className="blurb">{data.blurb}</p></>}
      <ul className="tips">{data.tips.map((tip, i) => <li key={i}>{tip.tip} <a href={tip.source_url} target="_blank" rel="noreferrer">{tip.source_title || new URL(tip.source_url).hostname} ↗</a>{tip.last_verified && <small> · verified {fmtDate(tip.last_verified)}</small>}</li>)}</ul></>}
  </article>
}

function AgentTrace({ reply, emptyNote }: { reply: Reply; emptyNote: string }) {
  const steps = reply.tool_trace
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  return <div className="agent-trace">
    <p className="agent-meta"><span className="source ai">AI · {reply.model}</span> {steps.length ? plural(steps.length, 'tool call') : emptyNote}</p>
    {!!steps.length && <ol className="agent-steps">{steps.map((s, i) => <li key={i}>
      <code>{s.tool}</code>{typeof s.args.query === 'string' && <span> “{s.args.query}”</span>}{s.summary && <span className="step-result"> → {s.summary}</span>}
    </li>)}</ol>}
    {reply.unverified_amounts.length
      ? <p className="unverified">⚠ Not found in your data: {reply.unverified_amounts.join(', ')}</p>
      : reply.amounts_checked > 0 && <p className="verified">✓ {plural(reply.amounts_checked, 'amount')} found in your data</p>}
  </div>
}

function ProposalButton({ proposal: p, asOf, onChanged }: { proposal: Proposal; asOf: string; onChanged?: () => void }) {
  const [state, setState] = React.useState<'idle' | 'saving' | 'done' | 'error'>('idle')
  async function confirm() {
    setState('saving')
    try {
      // used: true makes this idempotent: a second tap, or a period marked elsewhere, stays marked.
      await api(`/api/benefits/${encodeURIComponent(p.benefit_id)}/mark`, { period_start: p.period_start, as_of: asOf, used: true })
      setState('done'); onChanged?.()
    } catch { setState('error') }
  }
  return <div className="proposal"><span>Agent suggests: mark <b>{p.title}</b> ({p.period_label}) as used · {money(Math.round(p.amount * 100))}</span>
    <button disabled={state === 'saving' || state === 'done'} onClick={confirm}>{state === 'done' ? 'Marked ✓' : state === 'error' ? 'Retry' : 'Mark used'}</button></div>
}

function Chat({ storeKey, endpoint, asOf, suggestions, placeholder, emptyNote, composerNote, initialQuestion, intro, onChanged }: { storeKey: string; endpoint: string; asOf: string; suggestions: string[]; placeholder: string; emptyNote: string; composerNote?: string; initialQuestion?: { text: string; id: number }; intro?: React.ReactNode; onChanged?: () => void }) {
  const [messages, setMessages] = React.useState<Msg[]>(() => chatStore.get(storeKey) || [])
  const [draft, setDraft] = React.useState('')
  const log = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => { setMessages(chatStore.get(storeKey) || []) }, [storeKey])
  React.useEffect(() => { chatStore.set(storeKey, messages.filter(m => !m.pending)); log.current?.scrollTo({ top: log.current.scrollHeight }) }, [messages, storeKey])
  const busy = messages.some(m => m.pending)
  const sent = React.useRef(0)
  React.useEffect(() => {
    // The ref survives StrictMode's double effect, so each question is sent once.
    if (initialQuestion && sent.current !== initialQuestion.id) { sent.current = initialQuestion.id; send(initialQuestion.text) }
  }, [initialQuestion])
  async function send(question: string) {
    if (!question.trim() || busy) return
    const history: Msg[] = [...messages, { role: 'user', content: question }]
    setMessages([...history, { role: 'assistant', content: 'Checking your credits…', pending: true }]); setDraft('')
    try {
      const reply = await api<Reply>(endpoint, { messages: history.map(({ role, content }) => ({ role, content })), as_of: asOf })
      setMessages([...history, { role: 'assistant', content: reply.answer, reply }])
    } catch (e) {
      setMessages([...history, { role: 'assistant', content: `Sorry, that failed: ${e instanceof Error ? e.message : e}` }])
    }
  }
  return <div className="chat">
    <div className="chat-scroll" ref={log}>{intro}
      {!!messages.length && <div className="chat-log">{messages.map((m, i) => <div key={i} className={`msg ${m.role} ${m.pending ? 'pending' : ''}`}>
        {m.role === 'assistant' ? <Markdown text={m.content}/> : m.content}
        {m.reply && <AgentTrace reply={m.reply} emptyNote={emptyNote}/>}
        {m.reply?.proposals?.map(p => <ProposalButton key={p.benefit_id} proposal={p} asOf={asOf} onChanged={onChanged}/>)}
      </div>)}</div>}
    </div>
    <div className="chat-composer">
      <div className="suggestions">{suggestions.map(s => <button key={s} className="filter-chip" disabled={busy} onClick={() => send(s)}>{s}</button>)}</div>
      {composerNote && <small className="composer-note">{composerNote}</small>}
      <form className="chat-form" onSubmit={e => { e.preventDefault(); send(draft) }}><input value={draft} onChange={e => setDraft(e.target.value)} placeholder={placeholder} maxLength={2000}/><button disabled={busy || !draft.trim()}>Ask</button></form>
    </div>
  </div>
}

function Markdown({ text }: { text: string }) {
  // Minimal renderer for model output: bullets, **bold** and [links](https://...).
  const inline = (line: string, key: number) => <React.Fragment key={key}>{line.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\(https?:[^)\s]+\))/g).map((part, i) => {
    const bold = part.match(/^\*\*(.+)\*\*$/)
    if (bold) return <b key={i}>{bold[1]}</b>
    const link = part.match(/^\[([^\]]+)\]\((https?:[^)\s]+)\)$/)
    if (link) return <a key={i} href={link[2]} target="_blank" rel="noreferrer">{link[1]}</a>
    return part
  })}</React.Fragment>
  const blocks: React.ReactNode[] = []
  let bullets: string[] = []
  const flush = () => { if (bullets.length) blocks.push(<ul key={blocks.length}>{bullets.map((b, i) => <li key={i}>{inline(b, i)}</li>)}</ul>); bullets = [] }
  for (const line of text.split('\n')) {
    const item = line.match(/^\s*(?:[-*•]|\d+\.)\s+(.*)/)
    if (item) { bullets.push(item[1]); continue }
    flush()
    if (line.trim()) blocks.push(<p key={blocks.length}>{inline(line.replace(/^#+\s*/, ''), 0)}</p>)
  }
  flush()
  return <>{blocks}</>
}

function AskRail({ asOf, suggestions, initialQuestion, onChanged, onClose }: { asOf: string; suggestions: string[]; initialQuestion?: { text: string; id: number }; onChanged?: () => void; onClose: () => void }) {
  return <aside className="evidence-rail ask-rail" aria-label="Ask PerkWatch"><header><b><Sparkle/> Ask PerkWatch <small>Wallet-aware assistant</small></b><button onClick={onClose} aria-label="Close">×</button></header>
    <div className="rail-content"><h2>What's worth doing?</h2><p className="rail-subtitle">Answers use your tracked credits and official terms. Community tips are labeled.</p>
      <section className="chat-card"><Chat storeKey="__wallet__" endpoint="/api/ask" asOf={asOf} placeholder="Ask about any of your credits…"
        suggestions={suggestions} emptyNote="answered from your wallet, no tools needed" composerNote="Amounts come from your statements, not the model."
        initialQuestion={initialQuestion} onChanged={onChanged}/></section></div></aside>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
