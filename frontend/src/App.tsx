import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './store/auth';
import ProtectedRoute from './components/ProtectedRoute';
import Layout from './components/Layout';
import Login from './pages/Login';
import KnowledgeBases from './pages/KnowledgeBases';
import KnowledgeBaseDetail from './pages/KnowledgeBaseDetail';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/knowledge-bases"
            element={
              <ProtectedRoute>
                <Layout>
                  <KnowledgeBases />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route
            path="/knowledge-bases/:id"
            element={
              <ProtectedRoute>
                <Layout>
                  <KnowledgeBaseDetail />
                </Layout>
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Navigate to="/knowledge-bases" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
