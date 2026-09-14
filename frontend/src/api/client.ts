import type {
  CampaignMetricsResponse,
  CampaignTrace,
  DeliveryListResponse,
  DeliveryReport,
  IngestionResult,
} from '../types'

const API_BASE = '/api'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : response.statusText
    throw new Error(`${response.status} ${detail}`)
  }
  return response.json()
}

function get<T>(path: string, queryParams?: Record<string, string>): Promise<T> {
  const url = new URL(API_BASE + path, window.location.origin)
  if (queryParams) {
    Object.entries(queryParams).forEach(([name, value]) => value && url.searchParams.set(name, value))
  }
  return request<T>(url.toString())
}

export const api = {
  runIngestion: () =>
    request<IngestionResult>(API_BASE + '/ingestions', { method: 'POST' }),

  campaignMetrics: (platform?: string, dateFrom?: string, dateTo?: string) =>
    get<CampaignMetricsResponse>('/metrics/campaigns', {
      ...(platform ? { platform }           : {}),
      ...(dateFrom ? { date_from: dateFrom } : {}),
      ...(dateTo   ? { date_to:   dateTo }   : {}),
    }),

  campaignTrace: (platform: string, campaign: string) =>
    get<CampaignTrace>('/metrics/campaigns/trace', { platform, campaign }),

  deliveries: () =>
    get<DeliveryListResponse>('/deliveries'),

  deliveryReport: (deliveryId: number) =>
    get<DeliveryReport>(`/deliveries/${deliveryId}`),
}
