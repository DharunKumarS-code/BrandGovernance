import { BrowserRouter, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import { DemoProvider } from './context/DemoContext';
import { AuthProvider } from './context/AuthContext';
import Dashboard from './pages/Dashboard';
import Analytics from './pages/Analytics';
import Guidelines from './pages/Guidelines';
import Facts from './pages/Facts';
import Terminology from './pages/Terminology';
import ClaimPolicies from './pages/ClaimPolicies';
import Assets from './pages/Assets';
import Submissions from './pages/Submissions';
import SubmissionCreate from './pages/SubmissionCreate';
import SubmissionDetail from './pages/SubmissionDetail';
import Login from './pages/Login';

function App() {
  return (
    <AuthProvider>
      <DemoProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<Layout />}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/guidelines" element={<Guidelines />} />
              <Route path="/facts" element={<Facts />} />
              <Route path="/terminology" element={<Terminology />} />
              <Route path="/claim-policies" element={<ClaimPolicies />} />
              <Route path="/assets" element={<Assets />} />
              <Route path="/submissions" element={<Submissions />} />
              <Route path="/submissions/new" element={<SubmissionCreate />} />
              <Route path="/submissions/:id" element={<SubmissionDetail />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </DemoProvider>
    </AuthProvider>
  );
}

export default App;
