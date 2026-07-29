import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import GlobalOverview from './pages/GlobalOverview'
import GlobalDry from './pages/GlobalDry'
import GlobalLiquid from './pages/GlobalLiquid'
import Country from './pages/Country'
import Region from './pages/Region'
import CoastalRegion from './pages/CoastalRegion'
import Port from './pages/Port'
import Commodity from './pages/Commodity'
import Voyage from './pages/Voyage'
import Vessel from './pages/Vessel'

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/global" replace />} />
          <Route path="/global" element={<GlobalOverview />} />
          <Route path="/dry" element={<GlobalDry />} />
          <Route path="/liquid" element={<GlobalLiquid />} />
          <Route path="/country" element={<Country />} />
          <Route path="/region" element={<Region />} />
          <Route path="/coastal-region" element={<CoastalRegion />} />
          <Route path="/port" element={<Port />} />
          <Route path="/commodity" element={<Commodity />} />
          <Route path="/voyage" element={<Voyage />} />
          <Route path="/vessel" element={<Vessel />} />
          <Route path="*" element={<Navigate to="/global" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
