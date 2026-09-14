const PLATFORM_FINDINGS = [
  {
    name: 'Meta Ads', fileFormat: 'CSV', cardClass: 'ov-plat-meta',
    schema: 'campaign_name · date (MM/DD/YYYY) · spend_usd · impressions · clicks',
    defects: [
      '06-08 spend reported in cents (CPM ~100x normal) - divided by 100',
      '06-01: impossible date 06/31, one ISO-format date, a campaign-day gap',
      '06-15: 3 blank clicks (null); 06-22: negative spend excluded; names normalized',
    ],
  },
  {
    name: 'Google Ads', fileFormat: 'CSV', cardClass: 'ov-plat-google',
    schema: 'Campaign · Day (YYYY-MM-DD) · Cost (micros) · Currency · Impr. · Clicks',
    defects: [
      'Cost in micros - divided by 1,000,000',
      '06-01: 8 exact duplicate rows dropped',
      '06-15 resend is byte-identical to the original - loaded once',
    ],
  },
  {
    name: 'LinkedIn Ads', fileFormat: 'JSON', cardClass: 'ov-plat-li',
    schema: 'campaign · date_ts (Unix ms) · spend {amount, currency} · impressions · clicks?',
    defects: [
      'Spend in EUR - converted at 1 EUR = 1.08 USD',
      '06-08: 5 rows without clicks - stored as null, left out of CTR/CPC',
      '06-22 delivery never arrived',
    ],
  },
]

const PIPELINE_STEPS = [
  { icon: '📥', label: 'Discover', caption: 'platform × week slots' },
  { icon: '⚙️', label: 'Parse',    caption: 'raw rows, nothing dropped' },
  { icon: '🔍', label: 'Check',    caption: 'record, then clean' },
  { icon: '🗄️', label: 'SQLite',   caption: 'idempotent per delivery' },
  { icon: '🔌', label: 'FastAPI',  caption: 'metrics · health · trace' },
  { icon: '📊', label: 'This UI',  caption: 'Metrics + Data Health' },
]

const HEALTH_RULES = [
  { status: 'pass', label: 'Pass', cardClass: 'ov-hc-pass', rule: 'Loaded exactly as delivered. No check found anything.' },
  { status: 'warn', label: 'Warn', cardClass: 'ov-hc-warn', rule: 'Loaded, but rows were excluded, normalized or corrected, or a value needs review. The check detail lists each affected line.' },
  { status: 'fail', label: 'Fail', cardClass: 'ov-hc-fail', rule: 'Nothing usable: file missing, unreadable, or no valid rows.' },
]

export function OverviewPage() {
  return (
    <div className="view-content overview">
      <div className="ov-hero">
        <div className="ov-eyebrow">Campaign Data Hub</div>
        <h1 className="ov-title">
          One pipeline.<br />
          <span className="ov-title-grad">Numbers you can trust.</span>
        </h1>
        <p className="ov-sub">
          Normalizes three ad-platform delivery formats into one dataset. Every defect is
          recorded before it is fixed, so each number on the Metrics tab links back to a
          file and a quality report on the Data Health tab.
        </p>
      </div>

      <div className="ov-section-label">The problem</div>
      <div className="ov-grid">
        <div className="ov-card ov-card-problem">
          <div className="ov-card-num">01</div>
          <div className="ov-card-title">Nobody trusts the numbers</div>
          <div className="ov-card-body">Each platform delivers in its own schema, date format, currency, and unit. Comparing Meta spend to Google spend requires knowing that Google reports in micros and LinkedIn in EUR - knowledge that lives in people's heads, not the system.</div>
        </div>
        <div className="ov-card ov-card-problem">
          <div className="ov-card-num">02</div>
          <div className="ov-card-title">Broken deliveries go unnoticed</div>
          <div className="ov-card-body">A single delivery in the wrong unit made June's total spend look 10x higher than it was. Without checks, that shows up weeks later as "the dashboard looks wrong".</div>
        </div>
      </div>

      <div className="ov-section-label">What we found in June's deliveries</div>
      <div className="ov-grid">
        {PLATFORM_FINDINGS.map(platform => (
          <div key={platform.name} className={`ov-card ov-plat-card ${platform.cardClass}`}>
            <div className="ov-plat-header">
              <span className="ov-plat-name">{platform.name}</span>
              <span className="badge">{platform.fileFormat}</span>
            </div>
            <div className="ov-plat-schema">{platform.schema}</div>
            <div className="ov-plat-defects-label">Defects found</div>
            {platform.defects.map(defect => (
              <div key={defect} className="ov-plat-defect">· {defect}</div>
            ))}
          </div>
        ))}
      </div>

      <div className="ov-section-label">How it works</div>
      <div className="ov-pipeline">
        {PIPELINE_STEPS.map((step, index) => (
          <div key={step.label} className="ov-pipe-wrap">
            <div className="ov-pipe-node">
              <span className="ov-pipe-icon">{step.icon}</span>
              <span className="ov-pipe-label">{step.label}</span>
              <span className="ov-pipe-sub">{step.caption}</span>
            </div>
            {index < PIPELINE_STEPS.length - 1 && <div className="ov-pipe-arrow">→</div>}
          </div>
        ))}
      </div>

      <div className="ov-section-label">Health classification</div>
      <div className="ov-grid ov-hc-grid">
        {HEALTH_RULES.map(healthRule => (
          <div key={healthRule.status} className={`ov-card ov-hc-card ${healthRule.cardClass}`}>
            <span className={`status-badge s-${healthRule.status}-b`}>{healthRule.label}</span>
            <div className="ov-hc-rule">{healthRule.rule}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
