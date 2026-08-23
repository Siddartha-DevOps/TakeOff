import React, { createContext, useContext, useState, useEffect } from 'react';
import { authAPI } from '../services/api';
import { clearSession, getAuthToken, getSessionUser, storeSession } from '../services/session.js';

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

  // Session-scoped storage avoids leaving a seven-day bearer token on disk.
  useEffect(() => {
    const token = getAuthToken();
    const savedUser = getSessionUser();
    
    if (token && savedUser) {
      try {
        const parsedUser = JSON.parse(savedUser);
        setUser(parsedUser);
        setIsAuthenticated(true);
      } catch (e) {
        console.error('Failed to parse saved user', e);
        clearSession();
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
      
      storeSession(access_token, userData);
      
      setUser(userData);
      setIsAuthenticated(true);
      
      return { success: true, user: userData };
    } catch (error) {
      console.error('Login failed:', error);
      return { success: false, error: authErrorMessage(error, 'Login') };
    }
  };

  const signup = async (email, password, fullName, organizationName) => {
    try {
      const response = await authAPI.signup(email, password, fullName, organizationName);
      const { access_token, user: userData } = response.data;
      
      storeSession(access_token, userData);
      
      setUser(userData);
      setIsAuthenticated(true);
      
      return { success: true, user: userData };
    } catch (error) {
      console.error('Signup failed:', error);
      return { success: false, error: authErrorMessage(error, 'Signup') };
    }
  };

  const logout = () => {
    clearSession();
    setUser(null);
    setIsAuthenticated(false);
  };

  // For flows that already have a token+user from a non-login endpoint —
  // e.g. AcceptInvite.jsx's POST /team/invites/{token}/accept, which
  // returns the same Token shape as login/signup so the newly-created
  // member lands straight in the app instead of having to log in again.
  const loginWithSession = (accessToken, userData) => {
    storeSession(accessToken, userData);
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
