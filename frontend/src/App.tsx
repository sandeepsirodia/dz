import { useState } from 'react'
import { OverviewPage } from './components/OverviewPage'
import { MetricsView }  from './components/MetricsView'
import { HealthView }   from './components/HealthView'
import './App.css'

const TAB_LABELS = { overview: 'Overview', metrics: 'Metrics', health: 'Data Health' }
type Tab = keyof typeof TAB_LABELS

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  return (
    <>
      <header>
        <div className="logo">Campaign Data Hub</div>
        <nav>
          {(Object.keys(TAB_LABELS) as Tab[]).map(tab => (
            <button key={tab} className={`nav-btn ${activeTab === tab ? 'active' : ''}`}
                    onClick={() => setActiveTab(tab)}>
              {TAB_LABELS[tab]}
            </button>
          ))}
        </nav>
      </header>
      <main>
        {activeTab === 'overview' && <OverviewPage />}
        {activeTab === 'metrics'  && <MetricsView />}
        {activeTab === 'health'   && <HealthView />}
      </main>
    </>
  )
}
