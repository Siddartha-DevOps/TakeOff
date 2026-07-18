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

// Object storage (S3/R2) presigned upload — memory/TOGAL_PARITY_REAUDIT.md
// #12 / CLAUDE.md guardrail #1+#3: the file bytes go straight from the
// browser to object storage, never through this app's API server. Falls
// back to the legacy proxied upload below if the server 503s (S3_BUCKET
// unset — see backend/storage.py), so this stays a drop-in replacement:
// nothing else in the app needs to know which path a given deployment uses.
async function uploadDrawingViaPresign(projectId, file, metadata) {
  const presignRes = await api.post(`/api/uploads/project/${projectId}/drawings/presign`, {
    filename: file.name,
    content_type: file.type || 'application/octet-stream',
  });
  const { key, upload_url, fields } = presignRes.data;

  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => form.append(k, v));
  form.append('file', file);
  // Plain axios, not the `api` instance: this goes to the storage
  // provider's own origin, not our backend — it must not carry our
  // Authorization header or /api baseURL, and needs none of that since
  // the presigned form fields are themselves a short-lived credential.
  await axios.post(upload_url, form);

  return api.post(`/api/uploads/project/${projectId}/drawings/confirm`, {
    key,
    original_filename: file.name,
    sheet_name: metadata?.sheet_name,
    scale: metadata?.scale,
  });
}

function uploadDrawingViaProxy(projectId, file, metadata) {
  const formData = new FormData();
  formData.append('file', file);
  if (metadata?.sheet_name) formData.append('sheet_name', metadata.sheet_name);
  if (metadata?.scale) formData.append('scale', metadata.scale);

  return api.post(`/api/uploads/project/${projectId}/drawings`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
}

// Uploads API
export const uploadsAPI = {
  uploadDrawing: async (projectId, file, metadata) => {
    try {
      return await uploadDrawingViaPresign(projectId, file, metadata);
    } catch (err) {
      if (err.response?.status !== 503) throw err; // only fall back on "storage not configured"
    }
    return uploadDrawingViaProxy(projectId, file, metadata);
  },
  listDrawings: (projectId) => api.get(`/api/uploads/project/${projectId}/drawings`),
  getDrawing: (drawingId) => api.get(`/api/uploads/drawings/${drawingId}`),
  // Tiled pyramid rendering (routes/upload_routes.py + tiling.py) — DrawingRenderer
  // polls this while a sheet is still generating, then hands the meta to OpenSeadragon.
  getTileStatus: (drawingId) => api.get(`/api/uploads/drawings/${drawingId}/tiles/status`),
  regenerateTiles: (drawingId) => api.post(`/api/uploads/drawings/${drawingId}/tiles/generate`),
};

// Takeoff/AI API
export const takeoffAPI = {
  saveResults: (drawingId, results) => api.post(`/api/takeoff/drawings/${drawingId}/results`, results),
  getResults: (drawingId) => api.get(`/api/takeoff/drawings/${drawingId}/results`),
  getProjectResults: (projectId) => api.get(`/api/takeoff/projects/${projectId}/results`),
  // Real PostGIS geometry (as GeoJSON) — source data for the Interactive 3D
  // view (memory/TOGAL_PARITY_REAUDIT.md #19).
  getDetections: (drawingId) => api.get(`/api/takeoff/drawings/${drawingId}/detections`),
  // One-click AUTODETECT — exact Area/Line/Count from the PDF's vector geometry,
  // no model weights needed (geometry/ engine). Frontend calls this first and
  // falls back to the raster AI path / mock only when a sheet isn't vector.
  autodetect: (drawingId, scaleRatio) =>
    api.post(`/api/takeoff/drawings/${drawingId}/autodetect`, null, {
      params: scaleRatio ? { scale_ratio: scaleRatio } : {},
    }),
  detectSymbols: (drawingId) => api.post(`/api/takeoff/drawings/${drawingId}/detect_symbols`),
};

// Repeating Groups — master-unit -> many (memory/TOGAL_PARITY_REAUDIT.md #19)
export const repeatingAPI = {
  listMasterUnits: (projectId) => api.get(`/api/repeating/projects/${projectId}/master-units`),
  createMasterUnit: (projectId, payload) => api.post(`/api/repeating/projects/${projectId}/master-units`, payload),
  updateMasterUnit: (masterUnitId, payload) => api.put(`/api/repeating/master-units/${masterUnitId}`, payload),
  deleteMasterUnit: (masterUnitId) => api.delete(`/api/repeating/master-units/${masterUnitId}`),
  preview: (projectId) => api.get(`/api/repeating/projects/${projectId}/preview`),
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
  // Pattern/count search — "find all like this -> N". Reference is text,
  // a detection (detectionId), or a drawn region (drawingId + bbox).
  // Returns { total, per_drawing, matches }.
  count: (projectId, { text, detectionId, drawingId, bbox, minSimilarity = 0.85, maxMatches = 500 } = {}) =>
    api.post(`/api/takeoff/projects/${projectId}/search/count`, {
      text,
      detection_id: detectionId,
      drawing_id: drawingId,
      x1: bbox?.[0], y1: bbox?.[1], x2: bbox?.[2], y2: bbox?.[3],
      min_similarity: minSimilarity,
      max_matches: maxMatches,
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
  // Entitlements + usage metering (entitlements.py, routes/stripe_routes.py)
  getUsage: () => api.get('/api/payments/usage'),
};

// Export API
export const exportAPI = {
  exportDrawing: (drawingId, format) => api.get(`/api/export/drawings/${drawingId}/${format}`, {
    responseType: 'blob'
  }),
  exportProject: (projectId, format) => api.get(`/api/export/projects/${projectId}/${format}`, {
    responseType: 'blob'
  }),
  // Rich export — grouping, filtering, drawing selection, multiplier,
  // inline editable grid (routes/export_routes.py's preview/generate).
  previewProjectExport: (projectId, { drawingIds, trades, multiplier } = {}) => api.get(`/api/export/projects/${projectId}/preview`, {
    params: {
      drawing_ids: drawingIds?.length ? drawingIds.join(',') : undefined,
      trades: trades?.length ? trades.join(',') : undefined,
      multiplier,
    },
  }),
  generateProjectExport: (projectId, payload) => api.post(`/api/export/projects/${projectId}/generate`, payload, {
    responseType: 'blob'
  }),
};

// Estimating handoff — quantities -> UPC/WBS map + audit trail, Procore/
// DESTINI/Ediphi-style (routes/handoff_routes.py)
export const handoffAPI = {
  getMappings: (projectId) => api.get(`/api/handoff/projects/${projectId}/mappings`),
  upsertMapping: (projectId, mapping) => api.put(`/api/handoff/projects/${projectId}/mappings`, mapping),
  bulkUpsertMappings: (projectId, mappings) => api.put(`/api/handoff/projects/${projectId}/mappings/bulk`, { mappings }),
  deleteMapping: (mappingId) => api.delete(`/api/handoff/mappings/${mappingId}`),
  getAuditTrail: (projectId) => api.get(`/api/handoff/projects/${projectId}/audit-trail`),
  exportHandoff: (projectId, targetSystem) => api.get(`/api/handoff/projects/${projectId}/export`, {
    params: { target_system: targetSystem },
    responseType: 'blob',
  }),
};

// Real-time collaboration — presence/cursors (WebSocket, see useCollabSocket
// in pages/Takeoff.jsx) + durable pinned comments (REST, routes/realtime_routes.py)
export const collabAPI = {
  wsUrl: (projectId) => {
    const httpBase = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000';
    const wsBase = httpBase.replace(/^http/, 'ws');
    const token = localStorage.getItem('auth_token');
    return `${wsBase}/api/ws/projects/${projectId}?token=${encodeURIComponent(token || '')}`;
  },
  listComments: (projectId, params) => api.get(`/api/collab/projects/${projectId}/comments`, { params }),
  createComment: (projectId, comment) => api.post(`/api/collab/projects/${projectId}/comments`, comment),
  resolveComment: (commentId, resolved = true) => api.patch(`/api/collab/comments/${commentId}/resolve`, { resolved }),
  deleteComment: (commentId) => api.delete(`/api/collab/comments/${commentId}`),
};

// Teams/roles/permissions + invites — routes/team_routes.py, permissions.py
export const teamAPI = {
  listMembers: () => api.get('/api/team/members'),
  updateMemberRole: (userId, role) => api.patch(`/api/team/members/${userId}/role`, { role }),
  removeMember: (userId) => api.delete(`/api/team/members/${userId}`),
  listInvites: () => api.get('/api/team/invites'),
  createInvite: (email, role) => api.post('/api/team/invites', { email, role }),
  revokeInvite: (inviteId) => api.delete(`/api/team/invites/${inviteId}`),
  // Public — no auth token yet, the invitee doesn't have an account
  previewInvite: (token) => api.get(`/api/team/invites/${token}/preview`),
  acceptInvite: (token, fullName, password) => api.post(`/api/team/invites/${token}/accept`, { full_name: fullName, password }),
};

// Plan-set organizer — discipline-grouped sheet tree + sheet rename/reclassify
// (routes/plan_set_routes.py).
export const planSetAPI = {
  get: (projectId) => api.get(`/api/plan-set/projects/${projectId}`),
  updateSheet: (drawingId, patch) => api.patch(`/api/plan-set/drawings/${drawingId}`, patch),
};

// Trade assemblies estimating — one measured qty -> many priced trade line items
// (routes/assemblies_routes.py). Distinct from the India BOQ layer below.
export const estimatingAPI = {
  drawingAssemblies: (drawingId, costBookId) =>
    api.get(`/api/estimating/drawings/${drawingId}/assemblies`, {
      params: costBookId ? { cost_book_id: costBookId } : {},
    }),
  listCostBooks: () => api.get('/api/estimating/cost-books'),
  createCostBook: (payload) => api.post('/api/estimating/cost-books', payload),
  updateCostBook: (id, payload) => api.put(`/api/estimating/cost-books/${id}`, payload),
  deleteCostBook: (id) => api.delete(`/api/estimating/cost-books/${id}`),
  // Saved estimates
  saveEstimate: (payload) => api.post('/api/estimating/estimates', payload),
  listEstimates: (projectId) =>
    api.get('/api/estimating/estimates', { params: projectId ? { project_id: projectId } : {} }),
  getEstimate: (id) => api.get(`/api/estimating/estimates/${id}`),
  deleteEstimate: (id) => api.delete(`/api/estimating/estimates/${id}`),
  exportEstimate: (id) => api.get(`/api/estimating/estimates/${id}/export.xlsx`, { responseType: 'blob' }),
};

// India estimating — IS 1200 metric quantities -> DSR/SOR-priced BOQ -> GST
// tender total, plus Excel/PDF download (routes/india_routes.py).
// `params` tunes the tender waterfall: overhead_profit_pct, contingency_pct,
// gst_rate (fraction, e.g. 0.18), inter_state (bool).
export const indiaAPI = {
  getBOQ: (drawingId, params = {}) =>
    api.get(`/api/india/drawings/${drawingId}/boq`, { params }),
  // fmt = 'xlsx' | 'pdf'; returns a Blob for download
  exportBOQ: (drawingId, fmt, params = {}) =>
    api.get(`/api/india/drawings/${drawingId}/boq.${fmt}`, {
      params,
      responseType: 'blob',
    }),
};