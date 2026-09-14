import { useEffect, useState, Fragment } from 'react'
import { api } from '../api/client'
import { formatIsoDate, platformSlug, titleCase } from '../format'
import type { DeliveryReport, DeliverySummary, HealthStatus, QualityCheckResult } from '../types'

const STATUSES      = ['pass', 'warn', 'fail'] as const
const STATUS_LABELS = { pass: 'Passed', warn: 'Warnings', fail: 'Failed' }
const OUTCOME_ICONS = { pass: '✓', warn: '⚠', fail: '✗' }
const COLUMN_COUNT  = 7

const countOutcome = (checks: QualityCheckResult[], outcome: HealthStatus) =>
  checks.filter(check => check.outcome === outcome).length

export function HealthView() {
  const [deliveries, setDeliveries]                 = useState<DeliverySummary[]>([])
  const [expandedDeliveryId, setExpandedDeliveryId] = useState<number | null>(null)
  const [report, setReport]                         = useState<DeliveryReport | null>(null)
  const [ingesting, setIngesting]                   = useState(false)
  const [error, setError]                           = useState<string | null>(null)

  useEffect(() => {
    api.deliveries()
      .then(response => setDeliveries(response.deliveries))
      .catch(err => setError(String(err)))
  }, [])

  const collapse = () => { setExpandedDeliveryId(null); setReport(null) }

  const toggleReport = async (deliveryId: number) => {
    if (expandedDeliveryId === deliveryId) { collapse(); return }
    setExpandedDeliveryId(deliveryId)
    try {
      setReport(await api.deliveryReport(deliveryId))
    } catch (err) {
      setError(String(err))
    }
  }

  const reingest = async () => {
    setIngesting(true); setError(null)
    try {
      const result = await api.runIngestion()
      if (result.errors.length) setError(`Ingestion finished with errors: ${result.errors.join('; ')}`)
      setDeliveries((await api.deliveries()).deliveries)
      collapse()
    } catch (err) {
      setError(String(err))
    } finally {
      setIngesting(false)
    }
  }

  const statusCounts = { pass: 0, warn: 0, fail: 0 }
  deliveries.forEach(delivery => { statusCounts[delivery.status] += 1 })

  return (
    <div className="view-content">
      <div className="view-head">
        <div>
          <div className="view-eyebrow">Ingestion Quality</div>
          <div className="view-title">Delivery Health</div>
        </div>
        <button className="ingest-btn" disabled={ingesting} onClick={reingest}>
          {ingesting ? 'Running…' : '↻ Re-ingest'}
        </button>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="health-summary">
        {STATUSES.map(status => (
          <div key={status} className={`h-stat hs-${status}`}>
            <div className="h-dot" />
            <span className="h-stat-count">{statusCounts[status]}</span>
            <span className="h-stat-label">{STATUS_LABELS[status]}</span>
          </div>
        ))}
        <div className="h-hint">Click any row to see quality check details</div>
      </div>

      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 6, padding: 0 }} />
              <th>Platform</th>
              <th>Week</th>
              <th>File</th>
              <th title="rows loaded / rows received">Rows</th>
              <th>Status</th>
              <th style={{ width: 48 }} />
            </tr>
          </thead>
          <tbody>
            {deliveries.map(delivery => {
              const openReport = expandedDeliveryId === delivery.id ? report : null
              const failCount  = openReport ? countOutcome(openReport.checks, 'fail') : 0
              const warnCount  = openReport ? countOutcome(openReport.checks, 'warn') : 0
              return (
                <Fragment key={delivery.id}>
                  <tr className={`h-row s-${delivery.status}`} onClick={() => toggleReport(delivery.id)}>
                    <td className={`h-stripe h-stripe-${delivery.status}`} />
                    <td><span className={`badge p-${platformSlug(delivery.platform)}`}>{delivery.platform}</span></td>
                    <td className="date-txt">{formatIsoDate(delivery.week_start)}</td>
                    <td className={delivery.filename ? 'file-txt' : 'file-miss'}>{delivery.filename ?? '- missing -'}</td>
                    <td className="date-txt">{delivery.filename ? `${delivery.rows_loaded} / ${delivery.rows_received}` : '-'}</td>
                    <td><span className={`status-badge s-${delivery.status}-b`}>{delivery.status.toUpperCase()}</span></td>
                    <td>
                      {openReport
                        ? <span className="h-check-counts">
                            {failCount > 0 && <span className="h-fail-ct">{failCount} fail</span>}
                            {warnCount > 0 && <span className="h-warn-ct">{warnCount} warn</span>}
                            {failCount === 0 && warnCount === 0 && <span className="h-all-pass">all clear</span>}
                          </span>
                        : <button className="h-expand-hint" onClick={event => { event.stopPropagation(); toggleReport(delivery.id) }}>▼ checks</button>
                      }
                    </td>
                  </tr>
                  {openReport && (
                    <tr className="checks-row open">
                      <td colSpan={COLUMN_COUNT} className="checks-cell">
                        <div className="checks-inner">
                          <div className="report-summary">
                            {openReport.delivery.rows_received} rows received · {openReport.delivery.rows_loaded} loaded · {openReport.delivery.rows_excluded} excluded
                          </div>
                          {openReport.checks.map(check => (
                            <Fragment key={check.name}>
                              <div className={`check-item ci-${check.outcome}`}>
                                <span className="ci-icon">{OUTCOME_ICONS[check.outcome]}</span>
                                <span className="ci-name">{titleCase(check.name)}</span>
                                <span className="ci-detail" title={check.details.message}>{check.details.message ?? '-'}</span>
                              </div>
                              {check.outcome !== 'pass' && check.details.examples?.map(example => (
                                <div key={example} className="ci-example">{example}</div>
                              ))}
                            </Fragment>
                          ))}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
