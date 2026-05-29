import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import PatientDetail from './pages/PatientDetail';
import Staff from './pages/Staff';
import Reports from './pages/Reports';
import Settings from './pages/Settings';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Navigate to="/ward" replace />} />
          <Route path="ward" element={<Dashboard />} />
          <Route path="patient/:id" element={<PatientDetail />} />
          
          <Route path="staff" element={<Staff />} />
          <Route path="reports" element={<Reports />} />
          <Route path="settings" element={<Settings />} />
          <Route path="help" element={<div className="p-8 text-white">Help & Documentation (Coming Soon)</div>} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
