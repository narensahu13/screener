import { NavLink, Route, Routes } from 'react-router-dom'
import { LivePage } from './pages/LivePage'
import { BacktestPage } from './pages/BacktestPage'

export default function App() {
  return (
    <div className="app">
      <nav className="nav">
        <NavLink to="/" end>
          Live
        </NavLink>
        <NavLink to="/backtest">Backtest</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<LivePage />} />
        <Route path="/backtest" element={<BacktestPage />} />
      </Routes>
    </div>
  )
}
