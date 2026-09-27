import React from 'react'
import { createRoot } from 'react-dom/client'
import './theme.css'

type Item = {
  benefit_id: string; title: string; card_name: string; status: string; reason?: string
  action?: string; amount_minor?: number | null; used_amount_minor?: number | null
  remaining_amount_minor?: number | null; deadline?: string | null; period?: string | null
  partially_used?: boolean
}
type Briefing = {
  as_of: string; groups: { act_soon: Item[]; check_yourself: Item[]; on_track: Item[] }
  unknown_reason_groups: { reason: string; count: number; action: string }[]
  statements: { card_id: string; display_name: string; first_posted_date: string | null; last_posted_date: string | null; stale: boolean }[]
}
type Status = { last_preparation_time?: string | null }
const cardPriority = (card: Briefing['statements'][number]) => /amex|american express/i.test(`${card.card_id} ${card.display_name}`) ? 0 : /chase/i.test(`${card.card_id} ${card.display_name}`) ? 1 : 2
const money = (minor?: number | null) => minor == null ? '—' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(minor / 100)
const fmtDate = (value?: string | null) => value ? new Date(`${value}T00:00:00`).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : 'date unavailable'
const fmtFullDate = (value?: string | null) => value ? new Date(`${value}T00:00:00`).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' }) : 'date unavailable'
function daysLeft(deadline: string | null | undefined, asOf: string) {
  if (!deadline) return null
  return Math.max(0, Math.ceil((Date.parse(`${deadline}T00:00:00Z`) - Date.parse(`${asOf}T00:00:00Z`)) / 86400000))
}

function CountUp({ value, currency = true }: { value: number; currency?: boolean }) {
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
  return <>{currency ? money(shown) : shown.toLocaleString()}</>
}

function App() {
  const [briefing, setBriefing] = React.useState<Briefing | null>(null)
  const [status, setStatus] = React.useState<Status>({})
  const [error, setError] = React.useState('')
  const [asOf, setAsOf] = React.useState(new URLSearchParams(location.search).get('as_of') || '')
  const [benefitId, setBenefitId] = React.useState(new URLSearchParams(location.search).get('benefit') || '')
  React.useEffect(() => {
    const syncRoute = () => setBenefitId(new URLSearchParams(location.search).get('benefit') || '')
    window.addEventListener('popstate', syncRoute)
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])
  React.useEffect(() => {
    const query = asOf ? `?as_of=${encodeURIComponent(asOf)}` : ''
    Promise.all([
      fetch(`/api/briefing${query}`).then(r => { if (!r.ok) throw Error('Could not load briefing'); return r.json() }),
      fetch('/api/status').then(r => { if (!r.ok) throw Error('Could not load status'); return r.json() }),
    ]).then(([b, s]) => { setBriefing(b); setStatus(s); setError('') }).catch(e => setError(e.message))
  }, [asOf])
  function openEvidence(id: string) {
    setBenefitId(id)
    const url = new URL(location.href)
    url.searchParams.set('benefit', id)
    history.pushState(null, '', url)
  }
  function closeEvidence() {
    setBenefitId('')
    const url = new URL(location.href)
    url.searchParams.delete('benefit')
    history.pushState(null, '', url)
  }
  function changeDate(value: string) {
    setAsOf(value)
    const url = new URL(location.href)
    value ? url.searchParams.set('as_of', value) : url.searchParams.delete('as_of')
    history.replaceState(null, '', url)
  }
  if (error) return <main className="message"><h1>PerkWatch</h1><p>{error}. Start the API with <code>python3 scripts/serve.py</code>.</p></main>
  if (!briefing) return <main className="message">Loading your wallet…</main>
  const { act_soon: soon, check_yourself: check, on_track: track } = briefing.groups
  const empty = !soon.length && !track.length
  const imminentValue = soon.reduce((sum, item) => sum + (item.remaining_amount_minor || 0), 0)
  const transactionDates = briefing.statements.map(x => x.last_posted_date).filter((x): x is string => !!x).sort()
  const latestStatement = transactionDates.at(-1)
  return <>
    <header className="topbar"><div className="brand"><span className="mark">⌕</span><b>PerkWatch</b></div><div className="head-actions"><a href="http://127.0.0.1:8001" className="admin">⚒ &nbsp;Admin</a><label className="date-pill">AS OF <input aria-label="As of date" type="date" value={asOf || briefing.as_of} onChange={e => changeDate(e.target.value)} /></label><span className="avatar">VN</span></div></header>
    <main className="wallet-layout">
      <aside className="wallet-column"><div className="wallet-intro"><h1>Your wallet</h1><p>Your cards are holding a few things for you. See what expires soon and what PerkWatch can't confirm.</p></div>
        <div className="card-stack" aria-label="Your cards">{[...briefing.statements].sort((a, b) => cardPriority(a) - cardPriority(b)).slice(0, 2).map((card, i) => <article className={`bank-card bank-card-${i}`} key={card.card_id}><span className="chip"/><b>{card.display_name}</b></article>)}</div>
        <section className="wallet-summary"><p>About to expire <b className="orange-text"><CountUp value={imminentValue}/></b></p><p>Need your eyes <b className="teal-text"><CountUp value={check.length} currency={false}/></b></p><p>Quietly on track <b className="green-text"><CountUp value={track.length} currency={false}/></b></p><a href="#perks" className="perks-link">Perks &amp; protections <b>listed, not counted →</b></a>
          {briefing.statements.some(card => card.stale) && <div className="stale-warning">Statements end {fmtDate(latestStatement)}. Later charges aren't counted yet.</div>}
          <div className="card-dates">{briefing.statements.map(card => <p key={card.card_id}><b>{card.display_name}</b><span>{fmtDate(card.first_posted_date)}–{fmtDate(card.last_posted_date)}</span></p>)}{status.last_preparation_time && <small>PREPARED {new Date(status.last_preparation_time).toLocaleString()}</small>}</div>
        </section>
      </aside>
      <section className="briefing">
        <div className="welcome"><span className="eyebrow">BRIEFING · {briefing.statements.length} CARDS · {soon.length + check.length + track.length} BENEFITS</span><h2>{soon.length ? 'A few things are waiting for you.' : 'Your benefits at a glance.'}</h2><p>{soon.length ? 'One of your credits expires soon.' : 'Here is what PerkWatch can confirm from your statements.'}</p></div>
        {empty ? <section className="empty-state"><h2>PerkWatch can't see these yet</h2><p>Nothing can be calculated from the current data. Review these reasons instead of relying on repeated unknown cards.</p><div className="unknown-grid">{briefing.unknown_reason_groups.map(group => <article className="unknown-ticket" key={group.reason}><span className="ticket-cap">NEEDS YOUR EYES <b>?</b></span><b>{group.count} benefit{group.count === 1 ? '' : 's'}</b><p>{plainReason(group.reason)}</p><a href="http://127.0.0.1:8001">{group.action} →</a></article>)}</div><a className="admin-cta" href="http://127.0.0.1:8001">Review in Admin →</a></section> : <>
          {!!soon.length && <section className="group expiring"><h2 className="eyebrow">EXPIRING SOON</h2>{soon.map(item => <Coupon key={item.benefit_id} item={item} asOf={briefing.as_of} onEvidence={openEvidence}/>)}</section>}
          {!!check.length && <section className="group"><h2 className="eyebrow">PERKWATCH CAN'T SEE THESE — PEEK YOURSELF</h2><div className="unknown-grid">{check.map(item => <article className="unknown-ticket" key={item.benefit_id}><span className="ticket-cap">{ticketReason(item.reason)}<b>?</b></span><h3>{item.title}</h3><small>{item.card_name}</small><p>{plainReason(item.reason)}</p><button className="evidence-link" onClick={() => openEvidence(item.benefit_id)}>Receipts →</button></article>)}</div></section>}
          {!!track.length && <section className="group"><h2 className="eyebrow">QUIETLY ON TRACK · {track.length}</h2><div className="track-grid">{track.map(item => <article className="track-stub" key={item.benefit_id} onClick={() => openEvidence(item.benefit_id)}><div><b>{item.title}</b><small>{item.card_name}</small><span>{item.status === 'exhausted' ? 'Used' : `${money(item.remaining_amount_minor)} left`}{item.deadline ? ` · ${fmtDate(item.deadline)}` : ''}</span></div>{item.status === 'exhausted' && <i>USED</i>}</article>)}</div></section>}
          <section className="perks-strip" id="perks"><span>◇</span><div><b>Perks &amp; protections</b><small>Listed for reference, not counted as credits.</small></div><a href="http://127.0.0.1:8001">Browse →</a></section>
        </>}
      </section>
    </main>
    {benefitId && <EvidenceRail benefitId={benefitId} asOf={briefing.as_of} onClose={closeEvidence}/>}
    <button className="ask-float" disabled>Ask PerkWatch — “what's worth doing this week?” <span>→</span></button>
  </>
}
function Coupon({ item, asOf, onEvidence }: { item: Item; asOf: string; onEvidence: (id: string) => void }) {
  const days = daysLeft(item.deadline, asOf)
  return <article className="coupon"><div className="coupon-main"><h3>{item.title}</h3><p className="coupon-subtitle">{item.card_name} · {item.period || 'benefit'}{item.partially_used && item.used_amount_minor != null ? ` · ${money(item.used_amount_minor)} used` : ''}</p>{item.amount_minor && item.used_amount_minor != null && <div className="usage-track"><span style={{ width: `${Math.min(100, item.used_amount_minor / item.amount_minor * 100)}%` }}/></div>}<p className="coupon-reason">{item.reason || 'Available for eligible purchases before the period ends.'}</p><div className="coupon-actions"><button onClick={() => onEvidence(item.benefit_id)}>Receipts</button><button className="secondary" disabled>Ask about it</button></div></div><div className="coupon-stub"><span className="days-stamp">{days == null ? '—' : <><b><CountUp value={days} currency={false}/></b><small>DAYS LEFT</small></>}</span><strong><CountUp value={item.remaining_amount_minor || 0}/></strong><small>left to claim</small></div></article>
}
type Evidence = { benefit_id: string; title: string; card_name: string; amount_minor: number | null; period: string | null; terms: string; statements_through: string | null; period_start: string | null; period_end: string | null; source_reference: { path: string }; calculation: { used_amount_minor: number | null; remaining_amount_minor: number | null; deadline: string | null; status: string; reason: string }; transactions: { transaction_id: string; posted_date: string; description: string; amount_minor: number; matched_by: string | null }[]; not_counted: { transaction_id: string; posted_date: string; description: string; amount_minor: number; reason: string }[] }
type CommunityIdea = { idea: string; excerpt: string; source_url: string; source_date: string }
function EvidenceRail({ benefitId, asOf, onClose }: { benefitId: string; asOf: string; onClose: () => void }) {
  const [data, setData] = React.useState<Evidence | null>(null)
  const [ideas, setIdeas] = React.useState<CommunityIdea[]>([])
  const [error, setError] = React.useState('')
  React.useEffect(() => {
    const query = `?as_of=${encodeURIComponent(asOf)}`
    Promise.all([fetch(`/api/benefits/${encodeURIComponent(benefitId)}${query}`), fetch(`/api/benefits/${encodeURIComponent(benefitId)}/transactions${query}`), fetch(`/api/benefits/${encodeURIComponent(benefitId)}/community`)]).then(async ([benefit, transactions, community]) => {
      if (![benefit, transactions, community].every(r => r.ok)) throw Error('Could not load receipts')
      const [b, t, c] = await Promise.all([benefit.json(), transactions.json(), community.json()])
      setData({ ...b, ...t }); setIdeas(c.ideas)
    }).catch(e => setError(e.message))
  }, [benefitId, asOf])
  return <>
    <button className="rail-scrim" aria-label="Close Receipts" onClick={onClose}/>
    <aside className="evidence-rail" aria-label="Receipts"><header><b>▤ &nbsp;Receipts</b><button onClick={onClose} aria-label="Close">×</button></header>
      {!data && !error ? <p>Loading receipts…</p> : error ? <p>{error}</p> : data && <div className="rail-content"><h2>{data.title}</h2><p className="rail-subtitle">{data.card_name} · {data.period || 'benefit'}</p>
        <section className="receipt"><h3>{data.title} · CURRENT PERIOD</h3><p>{data.period_start && data.period_end ? `${fmtFullDate(data.period_start)} – ${fmtFullDate(data.period_end)}` : data.period || 'PERIOD'} · STATEMENTS THROUGH {fmtDate(data.statements_through)}</p><div className="receipt-line"><span>PER PERIOD</span><b>{money(data.amount_minor)}</b></div>
          {data.transactions.map(t => <div className="receipt-line" key={t.transaction_id}><span>{fmtDate(t.posted_date)} {t.description} <i>{t.matched_by || 'MATCHED'}</i></span><b>{money(t.amount_minor)}</b></div>)}
          {data.not_counted.map(t => <div className="not-counted-line" key={t.transaction_id}><span>NOT COUNTED · {fmtDate(t.posted_date)} {t.description}<small>{plainReason(t.reason)}</small></span><b>{money(t.amount_minor)}</b></div>)}
          <div className="receipt-total"><b>LEFT TO CLAIM</b><strong>{money(data.calculation.remaining_amount_minor)}</strong></div>
          {data.calculation.status === 'unknown' && <p className="rail-reason">Not counted: {plainReason(data.calculation.reason)}</p>}
        </section><section className="fine-print"><small>THE FINE PRINT · OFFICIAL TERMS</small><p>{data.terms}</p><a href={data.source_reference.path}>{data.source_reference.path}</a></section>
        {ideas.map((idea, i) => <article className="community-note" key={`${idea.source_date}-${i}`}><small>COMMUNITY TIP <b>NOT OFFICIAL TERMS</b></small><p>{idea.idea}</p><small>{fmtFullDate(idea.source_date)}</small> · <a href={idea.source_url} target="_blank" rel="noreferrer">Source ↗</a></article>)}
      </div>}
      <footer>Amounts come from the calculation engine, not the agent.</footer>
    </aside>
  </>
}
function ticketReason(reason?: string) {
  if (reason?.includes('merchant')) return 'UNMATCHED CHARGES'
  if (reason?.includes('period')) return 'PERIOD UNKNOWN'
  if (reason?.includes('account-year')) return 'NEEDS A DATE'
  return 'CHECK THE TERMS'
}
function plainReason(reason?: string) { return (reason || 'PerkWatch cannot calculate this benefit from current data.').replaceAll('_', ' ').replace(/^./, s => s.toUpperCase()) }

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
