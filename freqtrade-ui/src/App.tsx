import type { ReactNode } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell } from './layout/AppShell'
import { BotProvider, useBots } from './state/bots'
import { LiveProvider } from './state/live'
import { SettingsProvider } from './state/settings'
import { SnapshotProvider } from './state/snapshot'
import { ThemeProvider } from './state/theme'

import { Backtest } from './pages/Backtest'
import { Balance } from './pages/Balance'
import { Chart } from './pages/Chart'
import { Dashboard } from './pages/Dashboard'
import { DownloadData } from './pages/DownloadData'
import { Login } from './pages/Login'
import { Logs } from './pages/Logs'
import { LookaheadAnalysis } from './pages/LookaheadAnalysis'
import { NotFound } from './pages/NotFound'
import { OpenTrades } from './pages/OpenTrades'
import { Pairlist } from './pages/Pairlist'
import { PairlistConfig } from './pages/PairlistConfig'
import { RecursiveAnalysis } from './pages/RecursiveAnalysis'
import { Settings } from './pages/Settings'
import { Trade } from './pages/Trade'
import { TradeHistory } from './pages/TradeHistory'

/** Sends unauthenticated visitors to login, remembering where they were headed. */
function RequireBot({ children }: { children: ReactNode }) {
  const { bots } = useBots()
  const location = useLocation()

  if (bots.length === 0) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return <>{children}</>
}

function Shell() {
  return (
    <RequireBot>
      <SnapshotProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/trade" element={<Trade />} />
            <Route path="/open_trades" element={<OpenTrades />} />
            <Route path="/trade_history" element={<TradeHistory />} />
            <Route path="/balance" element={<Balance />} />
            <Route path="/chart" element={<Chart />} />
            <Route path="/pairlist" element={<Pairlist />} />
            <Route path="/pairlist_config" element={<PairlistConfig />} />
            <Route path="/backtest" element={<Backtest />} />
            <Route path="/download_data" element={<DownloadData />} />
            <Route path="/lookahead_analysis" element={<LookaheadAnalysis />} />
            <Route path="/recursive_analysis" element={<RecursiveAnalysis />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </AppShell>
      </SnapshotProvider>
    </RequireBot>
  )
}

export function App() {
  return (
    <ThemeProvider>
      <SettingsProvider>
        <BotProvider>
          <LiveProvider>
            <BrowserRouter>
              <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="/*" element={<Shell />} />
              </Routes>
            </BrowserRouter>
          </LiveProvider>
        </BotProvider>
      </SettingsProvider>
    </ThemeProvider>
  )
}
