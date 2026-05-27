import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import MainLayout from './layouts/MainLayout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import PatientDetail from './pages/PatientDetail';

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        
        <Route path="/" element={<MainLayout />}>
          <Route index element={<Navigate to="/ward" replace />} />
          <Route path="ward" element={<Dashboard />} />
          <Route path="patient/:id" element={<PatientDetail />} />
          
          {/* Placeholders for other routes */}
          <Route path="staff" element={<div className="p-8 text-white">Staff Management (Coming Soon)</div>} />
          <Route path="reports" element={<div className="p-8 text-white">Reports (Coming Soon)</div>} />
          <Route path="settings" element={<div className="p-8 text-white">Settings (Coming Soon)</div>} />
          <Route path="help" element={<div className="p-8 text-white">Help & Documentation (Coming Soon)</div>} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
