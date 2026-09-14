import { useEffect, useState, useCallback, Fragment } from 'react'
import type { MouseEvent } from 'react'
import { api } from '../api/client'
import { formatIsoDate, platformSlug } from '../format'
import type { CampaignMetrics, CampaignMetricsResponse, CampaignTrace } from '../types'

const PLATFORMS         = ['Meta Ads', 'Google Ads', 'LinkedIn Ads']
const DEFAULT_DATE_FROM = '2026-06-01'
const DEFAULT_DATE_TO   = '2026-06-30'
const HIGH_CTR          = 0.03
const LOW_CTR           = 0.01

const COLUMNS = ['campaign', 'platform', 'spend_usd', 'impressions', 'clicks', 'ctr', 'cpc'] as const
type Column = typeof COLUMNS[number]
const COLUMN_LABELS: Record<Column, string> = {
  campaign: 'Campaign', platform: 'Platform', spend_usd: 'Spend (USD)',
  impressions: 'Impressions', clicks: 'Clicks', ctr: 'CTR', cpc: 'CPC',
}
const TRACE_COLUMN_COUNT = 6

const formatUsd     = (value: number) => '$' + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const formatCount   = (value: number) => value.toLocaleString('en-US')
const formatPercent = (value: number | null) => value == null ? '-' : (value * 100).toFixed(2) + '%'
const formatCpc     = (value: number | null) => value == null ? '-' : '$' + value.toFixed(2)
const campaignKey   = (row: CampaignMetrics) => `${row.platform}|${row.campaign}`

function compareValues(left: string | number | null, right: string | number | null): number {
  if (left === right) return 0
  if (left === null) return -1
  if (right === null) return 1
  return typeof left === 'string' ? left.localeCompare(String(right)) : left - Number(right)
}

function ctrClass(ctr: number | null): string {
  if (ctr == null) return ''
  return ctr >= HIGH_CTR ? 'ctr-hi' : ctr < LOW_CTR ? 'ctr-lo' : ''
}

export function MetricsView() {
  const [metrics, setMetrics]             = useState<CampaignMetricsResponse | null>(null)
  const [platform, setPlatform]           = useState('')
  const [dateFrom, setDateFrom]           = useState(DEFAULT_DATE_FROM)
  const [dateTo, setDateTo]               = useState(DEFAULT_DATE_TO)
  const [sortColumn, setSortColumn]       = useState<Column>('spend_usd')
  const [sortDirection, setSortDirection] = useState<1 | -1>(-1)
  const [loading, setLoading]             = useState(false)
  const [error, setError]                 = useState<string | null>(null)
  const [openTraceKey, setOpenTraceKey]   = useState<string | null>(null)
  const [trace, setTrace]                 = useState<CampaignTrace | null>(null)

  const closeTrace = () => { setOpenTraceKey(null); setTrace(null) }

  const loadMetrics = useCallback(async () => {
    setLoading(true); setError(null)
    setOpenTraceKey(null); setTrace(null)
    try {
      setMetrics(await api.campaignMetrics(platform || undefined, dateFrom, dateTo))
    } catch (err) {
      setError(String(err))
    } finally {
      setLoading(false)
    }
  }, [platform, dateFrom, dateTo])

  useEffect(() => { loadMetrics() }, [loadMetrics])

  const toggleTrace = async (campaign: CampaignMetrics, event: MouseEvent) => {
    event.stopPropagation()
    const traceKey = campaignKey(campaign)
    if (openTraceKey === traceKey) { closeTrace(); return }
    setOpenTraceKey(traceKey)
    try {
      setTrace(await api.campaignTrace(campaign.platform, campaign.campaign))
    } catch (err) {
      setError(String(err))
    }
  }

  const handleSort = (column: Column) => {
    setSortDirection(sortColumn === column ? (sortDirection * -1) as 1 | -1 : -1)
    setSortColumn(column)
  }

  const clearFilters = () => {
    setPlatform('')
    setDateFrom(DEFAULT_DATE_FROM)
    setDateTo(DEFAULT_DATE_TO)
  }

  const sortedCampaigns = metrics
    ? [...metrics.campaigns].sort((left, right) => sortDirection * compareValues(left[sortColumn], right[sortColumn]))
    : []

  // rules every source delivery shares are shown once; each week then lists only what is specific to it
  const sharedRules = trace && trace.weeks.length
    ? trace.weeks[0].transformations.filter(rule => trace.weeks.every(week => week.transformations.includes(rule)))
    : []

  if (error) return <div className="error">{error}</div>

  const totals = metrics?.totals
  const kpiCards = [
    { label: 'Total Spend', value: totals ? formatUsd(totals.spend_usd)    : '-', caption: metrics ? `${metrics.campaigns.length} campaigns` : '' },
    { label: 'Impressions', value: totals ? formatCount(totals.impressions) : '-', caption: 'total' },
    { label: 'Clicks',      value: totals ? formatCount(totals.clicks)      : '-', caption: 'total' },
    { label: 'Avg CTR',     value: totals ? formatPercent(totals.ctr)       : '-', caption: 'clicks ÷ impressions' },
  ]

  return (
    <div className="view-content">
      <div className="view-head">
        <div>
          <div className="view-eyebrow">Campaign Performance</div>
          <div className="view-title">{loading ? 'Loading…' : 'Metrics'}</div>
        </div>
      </div>

      <div className="kpi-strip">
        {kpiCards.map(card => (
          <div key={card.label} className="kpi-card">
            <div className="kpi-label">{card.label}</div>
            <div className={`kpi-value ${loading ? 'kpi-loading' : ''}`}>{card.value}</div>
            <div className="kpi-sub">{card.caption}</div>
          </div>
        ))}
      </div>

      <div className="filters">
        <label className="filter-label">Platform</label>
        <select value={platform} onChange={event => setPlatform(event.target.value)}>
          <option value="">All platforms</option>
          {PLATFORMS.map(platformName => <option key={platformName}>{platformName}</option>)}
        </select>
        <span className="filter-sep">From</span>
        <input type="date" value={dateFrom} onChange={event => setDateFrom(event.target.value)} />
        <span className="filter-sep">to</span>
        <input type="date" value={dateTo} onChange={event => setDateTo(event.target.value)} />
        <button className="clear-btn" onClick={clearFilters}>✕ Clear filters</button>
      </div>

      <div className="spend-hint">↗ Click any spend value to see which deliveries and rules produced it</div>

      {metrics && metrics.campaigns.length === 0 ? (
        <div className="empty-state">
          <div className="empty-icon">🔍</div>
          <div className="empty-title">No campaigns match these filters</div>
          <div className="empty-sub">Try changing the platform or date range</div>
        </div>
      ) : (
        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                {COLUMNS.map(column => (
                  <th key={column} onClick={() => handleSort(column)} className={sortColumn === column ? 'sorted' : ''}>
                    {COLUMN_LABELS[column]}
                    {column === 'spend_usd' && <span style={{ opacity: .4, marginLeft: 4, fontSize: '.6rem' }}>↗</span>}
                    {column !== 'campaign' && column !== 'platform' && (
                      <span className="sort-ind">{sortColumn === column ? (sortDirection > 0 ? '↑' : '↓') : ''}</span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedCampaigns.map((campaign, index) => {
                const rowKey              = campaignKey(campaign)
                const isTraceOpen         = openTraceKey === rowKey
                const startsPlatformGroup = index === 0 || sortedCampaigns[index - 1].platform !== campaign.platform
                const slug                = platformSlug(campaign.platform)

                return (
                  <Fragment key={rowKey}>
                    {startsPlatformGroup && !platform && (
                      <tr className="plat-divider">
                        <td colSpan={COLUMNS.length}>
                          <span className={`badge p-${slug}`}>{campaign.platform}</span>
                        </td>
                      </tr>
                    )}
                    <tr className={`cam-row plat-${slug}`}>
                      <td className="td-campaign">{campaign.campaign}</td>
                      <td><span className={`badge p-${slug}`}>{campaign.platform}</span></td>
                      <td
                        className={`td-num td-spend spend-link${isTraceOpen ? ' spend-open' : ''}`}
                        onClick={event => toggleTrace(campaign, event)}
                        title="Click to trace source deliveries"
                      >
                        {formatUsd(campaign.spend_usd)}
                        <span className="spend-trace-icon">{isTraceOpen ? '▲' : '↗'}</span>
                      </td>
                      <td className="td-num">{formatCount(campaign.impressions)}</td>
                      <td className="td-num">{formatCount(campaign.clicks)}</td>
                      <td className={`td-num ${ctrClass(campaign.ctr)}`}>{formatPercent(campaign.ctr)}</td>
                      <td className={`td-num ${campaign.cpc == null ? 'td-na' : ''}`}>{formatCpc(campaign.cpc)}</td>
                    </tr>
                    {isTraceOpen && trace && (
                      <tr className="trace-row open">
                        <td colSpan={COLUMNS.length} className="trace-cell">
                          <div className="trace-inner">
                            <div className="trace-head">
                              <span>Source deliveries for <strong>{trace.campaign}</strong> · {trace.platform}</span>
                              <button className="trace-close" onClick={closeTrace}>✕ Close</button>
                            </div>
                            {sharedRules.length > 0 && (
                              <div className="trace-rules">Rules applied to every week: {sharedRules.join(' · ')}</div>
                            )}
                            <table className="trace-tbl">
                              <thead>
                                <tr>
                                  <td className="trace-th">Week</td>
                                  <td className="trace-th">File</td>
                                  <td className="trace-th">Health</td>
                                  <td className="trace-th" style={{ textAlign: 'right' }}>Impressions</td>
                                  <td className="trace-th" style={{ textAlign: 'right' }}>Clicks</td>
                                  <td className="trace-th" style={{ textAlign: 'right' }}>Spend</td>
                                </tr>
                              </thead>
                              <tbody>
                                {trace.weeks.map(week => {
                                  const weekSpecificRules = week.transformations.filter(rule => !sharedRules.includes(rule))
                                  const hasLineage = weekSpecificRules.length > 0 || week.quality_notes.length > 0
                                  return (
                                    <Fragment key={week.week_start}>
                                      <tr className={`trace-row-${week.delivery_status}`}>
                                        <td className="trace-week">{formatIsoDate(week.week_start)}</td>
                                        <td className="trace-file">{week.filename ?? '- missing -'}</td>
                                        <td><span className={`status-badge s-${week.delivery_status}-b`}>{week.delivery_status.toUpperCase()}</span></td>
                                        <td className="trace-spend">{formatCount(week.impressions)}</td>
                                        <td className="trace-spend">{formatCount(week.clicks)}</td>
                                        <td className="trace-spend">{formatUsd(week.spend_usd)}</td>
                                      </tr>
                                      {hasLineage && (
                                        <tr className="trace-lineage">
                                          <td colSpan={TRACE_COLUMN_COUNT}>
                                            {weekSpecificRules.map(rule => <div key={rule}>{rule}</div>)}
                                            {week.quality_notes.map(note => <div key={note} className="trace-note">⚠ {note}</div>)}
                                          </td>
                                        </tr>
                                      )}
                                    </Fragment>
                                  )
                                })}
                              </tbody>
                              <tfoot>
                                <tr className="trace-total">
                                  <td colSpan={3} style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: '.72rem', color: 'var(--text2)' }}>Total across {trace.weeks.length} weeks</td>
                                  <td className="trace-spend">{formatCount(trace.weeks.reduce((sum, week) => sum + week.impressions, 0))}</td>
                                  <td className="trace-spend">{formatCount(trace.weeks.reduce((sum, week) => sum + week.clicks, 0))}</td>
                                  <td className="trace-spend">{formatUsd(trace.weeks.reduce((sum, week) => sum + week.spend_usd, 0))}</td>
                                </tr>
                              </tfoot>
                            </table>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
            {totals && (
              <tfoot>
                <tr className="totals-row">
                  <td colSpan={2}><span className="totals-label">Total ({metrics?.campaigns.length} campaigns)</span></td>
                  <td className="td-num">{formatUsd(totals.spend_usd)}</td>
                  <td className="td-num">{formatCount(totals.impressions)}</td>
                  <td className="td-num">{formatCount(totals.clicks)}</td>
                  <td className="td-num">{formatPercent(totals.ctr)}</td>
                  <td className={`td-num ${totals.cpc == null ? 'td-na' : ''}`}>{formatCpc(totals.cpc)}</td>
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </div>
  )
}
