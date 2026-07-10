import axios from 'axios';

// Vite uses import.meta.env, not process.env
const API_BASE_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  maxRedirects: 5,
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
    if (error.response?.status === 401 || error.response?.status === 403) {
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

// Scale calibration API
export const scaleAPI = {
  get: (drawingId) => api.get(`/api/uploads/drawings/${drawingId}/scale`),
  calibrate: (drawingId, payload) => api.post(`/api/uploads/drawings/${drawingId}/scale/calibrate`, payload),
  acceptSuggestion: (drawingId) => api.post(`/api/uploads/drawings/${drawingId}/scale/accept-suggestion`),
};

// Conditions API
export const conditionsAPI = {
  list: (projectId) => api.get(`/api/projects/${projectId}/conditions`),
  create: (projectId, data) => api.post(`/api/projects/${projectId}/conditions`, data),
  update: (conditionId, data) => api.put(`/api/conditions/${conditionId}`, data),
  delete: (conditionId) => api.delete(`/api/conditions/${conditionId}`),
};

// Correction events API — the training-data flywheel (CLAUDE.md §2/§5)
export const correctionsAPI = {
  list: (projectId, params) => api.get(`/api/projects/${projectId}/corrections`, { params }),
  create: (projectId, data) => api.post(`/api/projects/${projectId}/corrections`, data),
};

// TakeOff.CHAT — RAG over detections/conditions/corrections/OCR (routes/ai_routes.py)
export const chatAPI = {
  send: (drawingId, message, conversationHistory = []) => api.post(`/api/takeoff/drawings/${drawingId}/chat`, {
    message,
    conversation_history: conversationHistory,
  }),
};

// AI Search — image/text/pattern, pgvector-backed (routes/ai_routes.py, clip_embeddings.py)
export const searchAPI = {
  text: (projectId, query, topK = 10) => api.post(`/api/takeoff/projects/${projectId}/search/text`, { query, top_k: topK }),
  image: (projectId, drawingId, bbox, topK = 10) => api.post(`/api/takeoff/projects/${projectId}/search/image`, {
    drawing_id: drawingId,
    x1: bbox[0], y1: bbox[1], x2: bbox[2], y2: bbox[3],
    top_k: topK,
  }),
};

// Drawing Compare — revision overlay/diff, OpenCV-backed (routes/compare_routes.py)
export const compareAPI = {
  listRevisions: (drawingId) => api.get(`/api/takeoff/drawings/${drawingId}/revisions`),
  compare: (drawingId, compareToDrawingId, manualPoints) => api.post(`/api/takeoff/drawings/${drawingId}/compare`, {
    compare_to_drawing_id: compareToDrawingId,
    ...(manualPoints ? { manual_points_a: manualPoints.a, manual_points_b: manualPoints.b } : {}),
  }),
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