import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8001';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to add auth token
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid
      localStorage.removeItem('auth_token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;

// Auth API
export const authAPI = {
  login: (email, password) => api.post('/api/auth/login', { email, password }),
  signup: (email, password, full_name) => api.post('/api/auth/signup', { email, password, full_name }),
  getCurrentUser: () => api.get('/api/auth/me'),
};

// Projects API
export const projectsAPI = {
  list: () => api.get('/api/projects'),
  get: (id) => api.get(`/api/projects/${id}`),
  create: (data) => api.post('/api/projects', data),
  update: (id, data) => api.put(`/api/projects/${id}`, data),
  delete: (id) => api.delete(`/api/projects/${id}`),
};

// Uploads API
export const uploadsAPI = {
  uploadDrawing: (projectId, file, metadata) => {
    const formData = new FormData();
    formData.append('file', file);
    if (metadata?.sheet_name) formData.append('sheet_name', metadata.sheet_name);
    if (metadata?.scale) formData.append('scale', metadata.scale);
    
    return api.post(`/api/uploads/project/${projectId}/drawings`, formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
  },
  listDrawings: (projectId) => api.get(`/api/uploads/project/${projectId}/drawings`),
  getDrawing: (drawingId) => api.get(`/api/uploads/drawings/${drawingId}`),
};
