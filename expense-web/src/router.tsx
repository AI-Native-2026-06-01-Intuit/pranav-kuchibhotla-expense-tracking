import { Navigate, Outlet, createBrowserRouter } from 'react-router-dom';
import LoginPage from './pages/LoginPage';
import MerchantListPage from './pages/MerchantListPage';
import MerchantDetailPage from './pages/MerchantDetailPage';
import MerchantSummaryPage from './pages/MerchantSummaryPage';

// Threat model: JWT in localStorage is XSS-exposed and accepted only
// until HttpOnly cookie auth is added later.
export const ProtectedLayout = () => {
  const token = localStorage.getItem('uc:jwt');
  if (token === null) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
};

export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage /> },
  {
    element: <ProtectedLayout />,
    children: [
      { path: '/', element: <Navigate to="/merchants" replace /> },
      { path: '/merchants', element: <MerchantListPage /> },
      { path: '/merchants/:id', element: <MerchantDetailPage /> },
      { path: '/merchants/:id/summary', element: <MerchantSummaryPage /> },
    ],
  },
]);
