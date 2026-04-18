import axios from 'axios';

const API_BASE_URL = process.env.REACT_APP_BACKEND_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  maxRedirects: 5,
  beforeRedirect: (options, responseDetails) => {
    // Preserve Authorization header on redirects
    const token = localStorage.getItem('auth_token');
    if (token) {
      options.headers.Authorization = `Bearer ${token}`;
    }
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
    // Handle auth errors
    if (error.response?.status === 401 || error.response?.status === 403) {
      // Token expired, invalid, or forbidden
      localStorage.removeItem('auth_token');
      localStorage.removeItem('user');
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
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

// Takeoff/AI API
export const takeoffAPI = {
  saveResults: (drawingId, results) => api.post(`/api/takeoff/drawings/${drawingId}/results`, results),
  getResults: (drawingId) => api.get(`/api/takeoff/drawings/${drawingId}/results`),
  getProjectResults: (projectId) => api.get(`/api/takeoff/projects/${projectId}/results`),
};

// Payments API
export const paymentsAPI = {
  createCheckoutSession: (packageId, originUrl) => api.post('/api/payments/checkout/session', null, {
    params: { package_id: packageId, origin_url: originUrl }
  }),
  getCheckoutStatus: (sessionId) => api.get(`/api/payments/checkout/status/${sessionId}`),
  getUserSubscription: () => api.get('/api/payments/subscription'),
};

// Export API
export const exportAPI = {
  exportDrawing: (drawingId, format) => api.get(`/api/export/drawings/${drawingId}/${format}`, {
    responseType: 'blob'
  }),
  exportProject: (projectId, format) => api.get(`/api/export/projects/${projectId}/${format}`, {
    responseType: 'blob'
  }),
};

