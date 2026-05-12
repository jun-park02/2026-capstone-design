import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { MainLayout } from './layouts/MainLayout';
import { Dashboard } from './pages/Dashboard';
import { MapPage } from './pages/MapPage';
import { AlertsPage } from './pages/AlertsPage';
import { FiresPage } from './pages/FiresPage';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="map" element={<MapPage />} />
          <Route path="alerts" element={<AlertsPage />} />
          <Route path="fires" element={<FiresPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
