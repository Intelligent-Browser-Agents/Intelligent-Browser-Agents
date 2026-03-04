import { Navigate, Outlet } from 'react-router-dom';
import { useState, useEffect } from 'react';

const check_login = async () => {
    const token = localStorage.getItem('token');
    const headers = {
      'Content-Type': 'application/json' // Include the token in the Authorization header
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch('http://localhost:8000/api/users/login/', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ username, password }), // Sending raw JSON
    });

    const data = await response.json();
    console.log("check_login: response data =", data);
    if (data.error === '') {
        return true;
    } else {
        return false;
    }
}

const ProtectedRoute = () => {
  const [isAuthenticated, setIsAuthenticated] = useState(null); // null = loading, true/false = loaded
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const checkAuth = async () => {
        try {
            const token = localStorage.getItem('token');
            const headers = {
            'Content-Type': 'application/json' // Include the token in the Authorization header
            };

            if (token) {
            headers['Authorization'] = `Bearer ${token}`;
            }

            const response = await fetch('http://localhost:8000/api/users/login/', {
            method: 'POST',
            headers: headers,
            body: JSON.stringify({ token }), // Sending raw JSON
            });

            const data = await response.json();
            console.log("check_login: response data =", data);
            if (data.error === '') {
                setIsAuthenticated(true);
            } else {
                setIsAuthenticated(false);
            }
        }
        catch (error) {
            setIsAuthenticated(false);
        } finally {
        setLoading(false);
        }
    };
        checkAuth();
    }, []);

  if (loading) {
    return <div>Loading...</div>;
  }

  if (isAuthenticated === false) {
    return <Navigate to="/" />;
  }

  return isAuthenticated ? <Outlet /> : <Navigate to="/dashboard" />;
}

export default ProtectedRoute;