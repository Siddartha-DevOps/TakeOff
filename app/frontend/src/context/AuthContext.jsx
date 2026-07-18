import React, { createContext, useContext, useState, useEffect } from 'react';
import { authAPI } from '../services/api';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  // Load user from localStorage on mount
  useEffect(() => {
    const token = localStorage.getItem('auth_token');
    const savedUser = localStorage.getItem('user');
    
    if (token && savedUser) {
      try {
        const parsedUser = JSON.parse(savedUser);
        setUser(parsedUser);
        setIsAuthenticated(true);
      } catch (e) {
        console.error('Failed to parse saved user', e);
        localStorage.removeItem('auth_token');
        localStorage.removeItem('user');
      }
    }
    setLoading(false);
  }, []);

  // Turn an axios error into an honest, actionable message. A real backend
  // rejection carries error.response (e.g. 401 "Incorrect email or password");
  // no error.response means the request never reached the server — a network /
  // CORS / wrong-backend-URL problem, NOT a bad password.
  const authErrorMessage = (error, action) => {
    if (error.response) {
      return error.response.data?.detail || `${action} failed. Please try again.`;
    }
    return `Can't reach the server. Check that the backend is deployed and reachable ` +
           `(VITE_BACKEND_URL), then try again.`;
  };

  const login = async (email, password) => {
    try {
      const response = await authAPI.login(email, password);
      const { access_token, user: userData } = response.data;
      
      localStorage.setItem('auth_token', access_token);
      localStorage.setItem('user', JSON.stringify(userData));
      
      setUser(userData);
      setIsAuthenticated(true);
      
      return { success: true, user: userData };
    } catch (error) {
      console.error('Login failed:', error);
      return { success: false, error: authErrorMessage(error, 'Login') };
    }
  };

  const signup = async (email, password, fullName) => {
    try {
      const response = await authAPI.signup(email, password, fullName);
      const { access_token, user: userData } = response.data;
      
      localStorage.setItem('auth_token', access_token);
      localStorage.setItem('user', JSON.stringify(userData));
      
      setUser(userData);
      setIsAuthenticated(true);
      
      return { success: true, user: userData };
    } catch (error) {
      console.error('Signup failed:', error);
      return { success: false, error: authErrorMessage(error, 'Signup') };
    }
  };

  const logout = () => {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user');
    setUser(null);
    setIsAuthenticated(false);
  };

  // For flows that already have a token+user from a non-login endpoint —
  // e.g. AcceptInvite.jsx's POST /team/invites/{token}/accept, which
  // returns the same Token shape as login/signup so the newly-created
  // member lands straight in the app instead of having to log in again.
  const loginWithSession = (accessToken, userData) => {
    localStorage.setItem('auth_token', accessToken);
    localStorage.setItem('user', JSON.stringify(userData));
    setUser(userData);
    setIsAuthenticated(true);
  };

  const value = {
    user,
    loading,
    isAuthenticated,
    login,
    signup,
    logout,
    loginWithSession,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};
