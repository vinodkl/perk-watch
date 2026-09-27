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
type Msg = { role: 'user' | 'assistant'; content: string; tools?: string[]; unverified?: string[]; pending?: boolean }

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
  const [filter, setFilter] = React.useState<'all' | 'missed' | 'manual'>('all')
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
  if (error) return <main className="message"><h1>PerkWatch</h1><p>{error}. Start the API with <code>uv run --extra ui python prototype/app_proto.py</code>.</p></main>
  if (!tracker) return <main className="message">Loading your wallet…</main>

  const atRisk = tracker.benefits.filter(b => b.current.status === 'at_risk').sort((a, b) => b.current.remaining_minor - a.current.remaining_minor)
  const cards = [...new Set(tracker.benefits.map(b => b.card))].sort((a, b) => cardPriority(a) - cardPriority(b))
  const through = Object.values(tracker.data_through).filter((x): x is string => !!x).sort()
  const stale = through.length > 0 && through[0] < tracker.as_of
  const keep = (b: Benefit) => filter === 'all' || (filter === 'missed' && b.ytd.missed_minor > 0) || (filter === 'manual' && b.tracking === 'manual')
  const selected = tracker.benefits.find(b => b.benefit_id === benefitId)

  return <>
    <header className="topbar"><div className="brand"><span className="mark">⌕</span><b>PerkWatch</b></div><div className="head-actions"><label className="date-pill">AS OF <input aria-label="As of date" type="date" value={asOf || tracker.as_of} onChange={e => changeDate(e.target.value)} /></label><span className="avatar">VN</span></div></header>
    <main className="wallet-layout">
      <aside className="wallet-column">
        <div className="wallet-intro"><h1>{greeting()}, Vinod.</h1><p>{atRisk.length ? <>{atRisk.length} credit{atRisk.length === 1 ? '' : 's'} expire{atRisk.length === 1 ? 's' : ''} in the next few days. Here's what's left and what slipped by.</> : <>Nothing is about to expire. Here's how your credits are tracking this year.</>}</p></div>
        <div className="card-stack" aria-label="Your cards">{cards.slice(0, 2).map((card, i) => <article className={`bank-card bank-card-${i}`} key={card}><span className="chip"/><b>{card}</b><small>{tracker.benefits.filter(b => b.card === card).length} CREDITS</small></article>)}</div>
        <section className="wallet-summary">
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
        {!!atRisk.length && <section className="group expiring"><h2 className="eyebrow">EXPIRING SOON · {atRisk.length}</h2><div className="coupon-list">{atRisk.map(b => <Coupon key={b.benefit_id} benefit={b} onOpen={openBenefit}/>)}</div></section>}
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
    </main>
    {selected && <BenefitRail benefit={selected} asOf={tracker.as_of} dataThrough={tracker.data_through[selected.card_id]} onClose={closeBenefit} onChanged={reload}/>}
    {askOpen && <AskRail asOf={tracker.as_of} onClose={() => setAskOpen(false)}/>}
    <button className="ask-float" onClick={() => setAskOpen(true)}>Ask PerkWatch — “what should I use this week?” <span>→</span></button>
  </>
}

function Legend() {
  const items: [Period['status'], string][] = [['used', 'used'], ['partial', 'partly used'], ['missed', 'missed'], ['at_risk', 'at risk'], ['open', 'open'], ['unmarked', 'manual, not marked'], ['pending', 'waiting for statement']]
  return <div className="legend">{items.map(([status, label]) => <span key={status}><i className={`dot ${status}`}>{GLYPH[status]}</i>{label}</span>)}</div>
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
    <div className="coupon-actions"><button onClick={() => onOpen(b.benefit_id)}>Ask about it</button><button className="secondary" onClick={() => onOpen(b.benefit_id)}>Details</button></div></div>
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
  async function toggle(p: Period) {
    await api(`/api/benefits/${encodeURIComponent(b.benefit_id)}/mark`, { period_start: p.start, as_of: asOf })
    onChanged()
  }
  return <>
    <button className="rail-scrim" aria-label="Close benefit" onClick={onClose}/>
    <aside className="evidence-rail" aria-label={b.title}><header><b>▤ &nbsp;{b.card}</b><button onClick={onClose} aria-label="Close">×</button></header>
      <div className="rail-content"><h2>{b.title}</h2>
        <p className="rail-subtitle">{PERIOD_NAME[b.period]} · {b.tracking === 'manual' ? 'tracked by you' : 'tracked from statement credits'}</p>
        <section className="receipt"><h3>{c.label} · CURRENT PERIOD</h3><p>{fmtDate(c.start)} – {fmtDate(c.end)} · STATEMENTS THROUGH {fmtDate(dataThrough)}</p>
          <Dots periods={b.periods} large onToggle={b.tracking === 'manual' ? toggle : undefined}/>
          {b.tracking === 'manual' && <p className="rail-hint">Tap a period to mark it used (or unmark it).</p>}
          <div className="receipt-line"><span>THIS {PERIOD_UNIT[b.period].toUpperCase()}</span><b>{money(c.amount_minor)}</b></div>
          {credits.map(credit => <div className="receipt-line" key={credit.transaction_id}><span>{fmtDate(credit.date)} statement credit <i>{credit.label}</i></span><b>−{money(credit.amount_minor)}</b></div>)}
          {!credits.length && b.tracking === 'auto' && <div className="receipt-line"><span>No statement credits yet this year</span><b>—</b></div>}
          <div className="receipt-line"><span>MISSED THIS YEAR</span><b className="mustard-text">{money(b.ytd.missed_minor)}</b></div>
          <div className="receipt-total"><b>{c.status === 'at_risk' ? `LEFT · ${c.days_left} DAYS` : 'LEFT TO CLAIM'}</b><strong>{money(c.remaining_minor)}</strong></div>
        </section>
        <section className="chat-card"><small className="section-label">ASK ABOUT THIS BENEFIT</small>
          <Chat storeKey={b.benefit_id} endpoint={`/api/benefits/${encodeURIComponent(b.benefit_id)}/chat`} asOf={asOf}
            suggestions={c.remaining_minor > 0 ? ['How can I use what is left before it resets?', 'What counts for this credit?', 'Is this worth it for me?'] : ['What counts for this credit?', 'Any tips for next period?']}
            placeholder={`Ask anything about ${b.title}…`}/></section>
        <Community benefitId={b.benefit_id}/>
        <details className="fine-print"><summary><small>THE FINE PRINT · OFFICIAL TERMS</small></summary><p>{b.terms || 'No terms text in prepared data.'}</p></details>
      </div>
      <footer>Amounts come from your statements, not the model.</footer>
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
      <p className="blurb">{data.blurb}</p>
      <ul className="tips">{data.tips.map((tip, i) => <li key={i}>{tip.tip} <a href={tip.source_url} target="_blank" rel="noreferrer">{tip.source_title || new URL(tip.source_url).hostname} ↗</a>{tip.last_verified && <small> · verified {fmtDate(tip.last_verified)}</small>}</li>)}</ul></>}
  </article>
}

function Chat({ storeKey, endpoint, asOf, suggestions, placeholder }: { storeKey: string; endpoint: string; asOf: string; suggestions: string[]; placeholder: string }) {
  const [messages, setMessages] = React.useState<Msg[]>(() => chatStore.get(storeKey) || [])
  const [draft, setDraft] = React.useState('')
  const log = React.useRef<HTMLDivElement>(null)
  React.useEffect(() => { setMessages(chatStore.get(storeKey) || []) }, [storeKey])
  React.useEffect(() => { chatStore.set(storeKey, messages.filter(m => !m.pending)); log.current?.scrollTo({ top: log.current.scrollHeight }) }, [messages, storeKey])
  const busy = messages.some(m => m.pending)
  async function send(question: string) {
    if (!question.trim() || busy) return
    const history: Msg[] = [...messages, { role: 'user', content: question }]
    setMessages([...history, { role: 'assistant', content: 'Checking your credits…', pending: true }]); setDraft('')
    try {
      const reply = await api<{ answer: string; tool_trace: { tool: string }[]; unverified_amounts: string[] }>(endpoint, { messages: history.map(({ role, content }) => ({ role, content })), as_of: asOf })
      setMessages([...history, { role: 'assistant', content: reply.answer, tools: reply.tool_trace.map(t => t.tool), unverified: reply.unverified_amounts }])
    } catch (e) {
      setMessages([...history, { role: 'assistant', content: `Sorry, that failed: ${e instanceof Error ? e.message : e}` }])
    }
  }
  return <div className="chat">
    {!!messages.length && <div className="chat-log" ref={log}>{messages.map((m, i) => <div key={i} className={`msg ${m.role} ${m.pending ? 'pending' : ''}`}>
      {m.role === 'assistant' ? <Markdown text={m.content}/> : m.content}
      {!!m.tools?.length && <p className="ask-trace">TOOLS · {m.tools.join(' → ')}</p>}
      {!!m.unverified?.length && <p className="unverified">⚠ Not found in your data: {m.unverified.join(', ')}</p>}
    </div>)}</div>}
    <div className="suggestions">{suggestions.map(s => <button key={s} className="filter-chip" disabled={busy} onClick={() => send(s)}>{s}</button>)}</div>
    <form className="chat-form" onSubmit={e => { e.preventDefault(); send(draft) }}><input value={draft} onChange={e => setDraft(e.target.value)} placeholder={placeholder} maxLength={2000}/><button disabled={busy || !draft.trim()}>Ask</button></form>
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

function AskRail({ asOf, onClose }: { asOf: string; onClose: () => void }) {
  return <><button className="rail-scrim" aria-label="Close Ask" onClick={onClose}/><aside className="evidence-rail" aria-label="Ask PerkWatch"><header><b>Ask PerkWatch</b><button onClick={onClose} aria-label="Close">×</button></header>
    <div className="rail-content"><h2>What's worth doing?</h2><p className="rail-subtitle">Answers use your tracked credits and official terms. Community tips are labeled.</p>
      <section className="chat-card"><Chat storeKey="__wallet__" endpoint="/api/ask" asOf={asOf} placeholder="Ask about any of your credits…"
        suggestions={['What should I use this week?', 'Which credits have I been missing most?', 'Which credit covers airport security fast lanes?']}/></section></div>
    <footer>Amounts come from your statements, not the model.</footer></aside></>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
