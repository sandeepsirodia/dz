export type HealthStatus = 'pass' | 'warn' | 'fail'

// ── Metrics ──────────────────────────────────────────────────

export interface MetricTotals {
  spend_usd:   number
  impressions: number
  clicks:      number
  ctr:         number | null
  cpc:         number | null
}

export interface CampaignMetrics extends MetricTotals {
  platform: string
  campaign: string
}

export interface CampaignMetricsResponse {
  campaigns: CampaignMetrics[]
  totals:    MetricTotals
}

export interface TraceWeek {
  delivery_id:     number
  week_start:      string
  filename:        string | null
  delivery_status: HealthStatus
  spend_usd:       number
  impressions:     number
  clicks:          number
  transformations: string[]
  quality_notes:   string[]
}

export interface CampaignTrace {
  platform: string
  campaign: string
  weeks:    TraceWeek[]
}

// ── Deliveries (data health) ─────────────────────────────────

export interface DeliverySummary {
  id:            number
  platform:      string
  week_start:    string
  filename:      string | null
  status:        HealthStatus
  rows_received: number
  rows_loaded:   number
  rows_excluded: number
  ingested_at:   string
}

export interface DeliveryListResponse {
  deliveries: DeliverySummary[]
}

export interface QualityCheckResult {
  name:    string
  outcome: HealthStatus
  details: { message?: string; examples?: string[]; [key: string]: unknown }
}

export interface DeliveryReport {
  delivery:        DeliverySummary
  transformations: string[]
  checks:          QualityCheckResult[]
}

// ── Ingestion ────────────────────────────────────────────────

export interface IngestionResult {
  files_processed: number
  rows_written:    number
  rows_excluded:   number
  ignored_files:   string[]
  errors:          string[]
}
