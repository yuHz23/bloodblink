import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import './theme1.css'
import App from './App'
import HospitalSimulator from './pages/HospitalSimulator'
import DonorSimulator from './pages/DonorSimulator'
import { AuthProvider } from './lib/auth'
import { ThemeProvider } from './lib/theme'

const qc = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } })
const simulatorMode = import.meta.env.VITE_SIMULATOR_MODE
const theme1Mode = import.meta.env.MODE === 'theme1'
const Root = simulatorMode === 'hospital'
  ? HospitalSimulator
  : simulatorMode === 'donor'
    ? DonorSimulator
    : App

if (simulatorMode === 'hospital') document.title = 'BLOODBLINK · Mô phỏng bệnh viện'
if (simulatorMode === 'donor') document.title = 'BLOODBLINK · Mô phỏng người dân'
if (theme1Mode) {
  document.documentElement.classList.add('theme1-mode')
  document.title = 'BLOOD-BLINK SOS · Điều phối'
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <ThemeProvider>
          <AuthProvider>
            <Root />
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
