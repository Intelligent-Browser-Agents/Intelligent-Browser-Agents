import { Navigate, Outlet } from 'react-router-dom';
import { useState, useEffect } from 'react';

import { api, getToken } from '../lib/api';

/**
 * Route guard.
 *
 * The previous implementation POSTed `{ token }` to the *login* endpoint with no
 * username or password. On a missing or expired token the backend raised a
 * KeyError and returned a 500, so the redirect only happened by accident, and its
 * fallback navigated to `/dashboard` - the very route it guards, which is an
 * infinite redirect. It now asks a real authenticated endpoint whether the token
 * is good, and unauthenticated always means the login page.
 */
const ProtectedRoute = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(null); // null = still checking

  useEffect(() => {
    let cancelled = false;

    const checkAuth = async () => {
      if (!getToken()) {
        if (!cancelled) setIsAuthenticated(false);
        return;
      }
      try {
        await api.me();
        if (!cancelled) setIsAuthenticated(true);
      } catch {
        // apiFetch already cleared the token on a 401.
        if (!cancelled) setIsAuthenticated(false);
      }
    };

    checkAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  if (isAuthenticated === null) {
    return <div className="route-loading">Loading...</div>;
  }

  return isAuthenticated ? <Outlet /> : <Navigate to="/" replace />;
};

export default ProtectedRoute;
