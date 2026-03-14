import { BrowserRouter, Routes, Route } from 'react-router-dom';
import ProjectList from './pages/ProjectList';
import ProjectDetail from './pages/ProjectDetail';
import AuditLogsPage from './pages/AuditLogsPage';
import SettingsPage from './pages/SettingsPage';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<ProjectList />} />
        <Route path="/projects/:id" element={<ProjectDetail />} />
        <Route path="/projects/:id/audit-logs" element={<AuditLogsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
