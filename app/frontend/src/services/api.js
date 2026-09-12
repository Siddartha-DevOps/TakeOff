import axios from 'axios';
import { clearSession, getAuthToken } from './session.js';

// Vite uses import.meta.env, not process.env
// In production VITE_BACKEND_URL MUST be set (Vercel env). Only fall back to
// localhost during local `vite dev` — never ship localhost to a deployed build
// (that's what made every deployed API call, including login, silently fail).
const API_BASE_URL =
  import.meta.env.VITE_BACKEND_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '');

if (!import.meta.env.VITE_BACKEND_URL && !import.meta.env.DEV) {
  // Same-origin '' only works if a proxy/rewrite forwards /api to the backend.
  console.error('[api] VITE_BACKEND_URL is not set — API requests will fail. Set it in your host env.');
}

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
    // The instance defaults to JSON for ordinary API requests. FormData must
    // not inherit that header: the browser supplies multipart/form-data plus
    // its generated boundary, which FastAPI needs to parse UploadFile fields.
    if (typeof FormData !== 'undefined' && config.data instanceof FormData) {
      if (typeof config.headers?.delete === 'function') {
        config.headers.delete('Content-Type');
      } else if (config.headers) {
        delete config.headers['Content-Type'];
      }
    }

    const token = getAuthToken();
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
      clearSession();
      if (window.location.pathname !== '/login') {
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;

// Guest client — deliberately separate from `api` above: no auth-token
// interceptor (a guest viewing a share link has no account, and must
// never have a logged-in user's token silently attached to their
// requests) and no 401/403 -> redirect-to-/login interceptor (a guest
// hitting a 403 on a view-only link trying to comment should see an
// inline message, not get bounced to a login page they have no account
// for). See routes/share_routes.py's guest_router.
const guestApi = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
});

// Auth API
export const authAPI = {
  login: (email, password) => api.post('/api/auth/login', { email, password }),
  signup: (email, password, full_name, organization_name) => api.post('/api/auth/signup', {
    email,
    password,
    full_name,
    organization_name: organization_name || undefined,
  }),
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

  // Do not set Content-Type manually. The browser must add the multipart
  // boundary; forcing the bare media type can make FastAPI report a missing
  // `file` field (422) even though FormData contains it.
  return api.post(`/api/uploads/project/${projectId}/drawings`, formData);
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

// Drawing folders — Togal parity "Project folders & organization" (color-coded, folders, sets)
export const foldersAPI = {
  list: (projectId) => api.get(`/api/projects/${projectId}/folders`),
  create: (projectId, data) => api.post(`/api/projects/${projectId}/folders`, data),
  update: (folderId, data) => api.put(`/api/folders/${folderId}`, data),
  delete: (folderId) => api.delete(`/api/folders/${folderId}`),
  assignDrawing: (drawingId, folderId) => api.put(`/api/drawings/${drawingId}/folder`, { folder_id: folderId }),
};

// Takeoff/AI API
export const takeoffAPI = {
  saveResults: (drawingId, results) => api.post(`/api/takeoff/drawings/${drawingId}/results`, results),
  getResults: (drawingId) => api.get(`/api/takeoff/drawings/${drawingId}/results`),
  getJob: (jobId) => api.get(`/api/jobs/${jobId}`),
  getDrawingJobs: (drawingId) => api.get(`/api/jobs/drawing/${drawingId}/latest`),
  getAnnotations: (drawingId) => api.get(`/api/takeoff/drawings/${drawingId}/annotations`),
  saveAnnotations: (drawingId, annotations) => api.put(
    `/api/takeoff/drawings/${drawingId}/annotations`, { annotations },
  ),
  getAnnotationHistory: (drawingId) => api.get(`/api/takeoff/drawings/${drawingId}/annotations/history`),
  restoreAnnotationHistory: (drawingId, revisionId) => api.post(`/api/takeoff/drawings/${drawingId}/annotations/history/${revisionId}/restore`),
  // Real raster AI takeoff — triggers YOLOv8-seg in the background
  // (routes/takeoff_routes.py _run_ai_analysis). Poll getResults for the result;
  // marks the drawing FAILED (no fabricated data) when no model is installed.
  analyze: (drawingId) => api.post(`/api/takeoff/drawings/${drawingId}/analyze`),
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

// Classification libraries — Togal parity "reusable templates, import/export"
export const templatesAPI = {
  list: () => api.get('/api/condition-templates'),
  saveFromProject: (projectId, data) => api.post(`/api/projects/${projectId}/conditions/save-as-template`, data),
  apply: (projectId, templateId) => api.post(`/api/projects/${projectId}/conditions/apply-template/${templateId}`),
  rename: (templateId, data) => api.put(`/api/condition-templates/${templateId}`, data),
  delete: (templateId) => api.delete(`/api/condition-templates/${templateId}`),
  exportProject: (projectId) => api.get(`/api/projects/${projectId}/conditions/export`),
  importJson: (projectId, payload) => api.post(`/api/projects/${projectId}/conditions/import`, payload),
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
  reindex: (projectId) => api.post(`/api/takeoff/projects/${projectId}/search/reindex`),
  review: (projectId, payload) => api.post(`/api/takeoff/projects/${projectId}/search/review`, payload),
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

// Organization-scoped audit feed (routes/audit_routes.py).
export const activityAPI = {
  list: (limit = 10) => api.get('/api/activity', { params: { limit } }),
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
  // Breakdowns — Togal parity "phase/floor/unit breakdowns". groupBy is an
  // ordered array of up to 3: 'folder' | 'trade' | 'item' | 'drawing'.
  getBreakdown: (projectId, { groupBy, drawingIds, trades } = {}) => api.get(`/api/export/projects/${projectId}/breakdown`, {
    params: {
      group_by: (groupBy?.length ? groupBy : ['folder', 'trade']).join(','),
      drawing_ids: drawingIds?.length ? drawingIds.join(',') : undefined,
      trades: trades?.length ? trades.join(',') : undefined,
    },
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
  wsConnection: (projectId) => {
    const httpBase =
      import.meta.env.VITE_BACKEND_URL || (import.meta.env.DEV ? 'http://localhost:8000' : window.location.origin);
    const wsBase = httpBase.replace(/^http/, 'ws');
    const token = getAuthToken();
    return {
      url: `${wsBase}/api/ws/projects/${projectId}`,
      protocols: token ? ['takeoff-auth', token] : ['takeoff-auth'],
    };
  },
  listComments: (projectId, params) => api.get(`/api/collab/projects/${projectId}/comments`, { params }),
  createComment: (projectId, comment) => api.post(`/api/collab/projects/${projectId}/comments`, comment),
  resolveComment: (commentId, resolved = true) => api.patch(`/api/collab/comments/${commentId}/resolve`, { resolved }),
  deleteComment: (commentId) => api.delete(`/api/collab/comments/${commentId}`),
};

// External collaboration without an account — Togal parity. Authenticated
// side (create/list/revoke a project's share links) uses the normal `api`
// client; guestAPI below is what the /share/:token page itself uses.
export const shareAPI = {
  list: (projectId) => api.get(`/api/projects/${projectId}/share-links`),
  create: (projectId, data) => api.post(`/api/projects/${projectId}/share-links`, data),
  revoke: (linkId) => api.delete(`/api/share-links/${linkId}`),
  guestUrl: (token) => `${window.location.origin}/share/${token}`,
};

// The guest-facing surface itself — no Authorization header, ever (see
// guestApi's definition above). token is a path segment, not a header, so
// these also work as plain <img src>/tile-source URLs for the drawing viewer.
export const guestAPI = {
  fileUrl: (token, drawingId) => `${API_BASE_URL}/api/guest/${token}/drawings/${drawingId}/file`,
  tileUrl: (token, drawingId, level, x, y) => `${API_BASE_URL}/api/guest/${token}/drawings/${drawingId}/tiles/${level}/${x}_${y}.jpg`,
  resolve: (token) => guestApi.get(`/api/guest/${token}`),
  getTileStatus: (token, drawingId) => guestApi.get(`/api/guest/${token}/drawings/${drawingId}/tiles/status`),
  getResults: (token, drawingId) => guestApi.get(`/api/guest/${token}/drawings/${drawingId}/results`),
  listComments: (token, drawingId) => guestApi.get(`/api/guest/${token}/comments`, { params: { drawing_id: drawingId } }),
  createComment: (token, comment) => guestApi.post(`/api/guest/${token}/comments`, comment),
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

// Classification-library templates — reusable org-level condition sets
// (routes/classification_routes.py).
export const classificationAPI = {
  list: () => api.get('/api/classifications/templates'),
  seed: () => api.post('/api/classifications/templates/seed'),
  create: (payload) => api.post('/api/classifications/templates', payload),
  remove: (id) => api.delete(`/api/classifications/templates/${id}`),
  apply: (templateId, projectId) => api.post(`/api/classifications/templates/${templateId}/apply/${projectId}`),
};

// External collaboration — share a project with people who have no account
// (routes/sharing_routes.py). resolve() is the PUBLIC guest endpoint.
export const sharingAPI = {
  list: (projectId) => api.get(`/api/projects/${projectId}/shares`),
  create: (projectId, payload) => api.post(`/api/projects/${projectId}/shares`, payload),
  revoke: (shareId) => api.delete(`/api/shares/${shareId}`),
  resolve: (token) => api.get(`/api/shared/${token}`),
};

// ML ops — model registry (eval_routes) + active-learning review queue
// (active_learning_routes). Surfaces the training flywheel in the UI.
export const mlAPI = {
  listModelVersions: () => api.get('/api/eval/model-versions'),
  reviewQueue: (projectId, limit = 20) =>
    api.get(`/api/active-learning/projects/${projectId}/review-queue`, { params: { limit } }),
  uncertainDetections: (projectId, limit = 50) =>
    api.get(`/api/active-learning/projects/${projectId}/uncertain-detections`, { params: { limit } }),
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
