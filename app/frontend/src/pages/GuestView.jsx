import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import OpenSeadragon from 'openseadragon';
import { Sparkles, MessageSquare, Loader2, AlertCircle, X, Send } from 'lucide-react';
import { guestAPI } from '../services/api';

// External collaboration without a TakeOff account (Togal parity:
// "External collaboration — unlimited, no account needed"). This page
// never imports the authenticated `api` client, never reads/writes
// `auth_token`, and never renders anything behind ProtectedRoute (see
// App.jsx — this route sits alongside /invite/:token, the other
// deliberately-public page). Everything here goes through guestAPI,
// which hits routes/share_routes.py's guest_router — token-gated, no
// login step anywhere in this flow.
//
// Deliberately a standalone, lighter viewer rather than reusing
// DrawingRenderer.jsx: that component is tightly coupled to the
// authenticated Bearer-header tile-loading path (loadTilesWithAjax +
// ajaxHeaders) and calibration/annotation-editing concerns a guest link
// has no business exposing. A share link's token is itself the
// shareable credential, so tile/file URLs embed it directly (see
// services/api.js's guestAPI.tileUrl/fileUrl) — no header gymnastics needed.

const TILE_POLL_MS = 2000;
const TILE_POLL_MAX_ATTEMPTS = 30;

function GuestDrawingViewer({ token, drawing, onPinClick, pins, placingPin, onPlacePin }) {
  const containerRef = useRef(null);
  const viewerRef = useRef(null);
  const [tileMeta, setTileMeta] = useState(null);
  // setTick's value is never read directly -- calling it just forces a
  // re-render on pan/zoom, which is what makes the pins.map() below
  // recompute each pin's screen position on every frame.
  const [, setTick] = useState(0);
  const placingRef = useRef(placingPin);
  placingRef.current = placingPin;

  useEffect(() => {
    setTileMeta(null);
    let cancelled = false;
    let attempts = 0;
    let timeoutId;
    async function poll() {
      try {
        const res = await guestAPI.getTileStatus(token, drawing.id);
        if (cancelled) return;
        if (res.data?.ready) { setTileMeta(res.data); return; }
      } catch { /* keep polling / fall back below */ }
      attempts += 1;
      if (!cancelled && attempts < TILE_POLL_MAX_ATTEMPTS) timeoutId = setTimeout(poll, TILE_POLL_MS);
    }
    poll();
    return () => { cancelled = true; clearTimeout(timeoutId); };
  }, [token, drawing.id]);

  useEffect(() => {
    if (!tileMeta || !containerRef.current) return undefined;
    const viewer = OpenSeadragon({
      element: containerRef.current,
      tileSources: {
        width: tileMeta.width,
        height: tileMeta.height,
        tileSize: tileMeta.tile_size,
        tileOverlap: tileMeta.overlap,
        minLevel: 0,
        maxLevel: tileMeta.max_level,
        // Plain URL, token embedded — no ajax/header dance needed for a
        // share-link credential the way a session JWT would.
        getTileUrl: (level, x, y) => guestAPI.tileUrl(token, drawing.id, level, x, y),
      },
      showNavigationControl: false,
      visibilityRatio: 1,
      constrainDuringPan: true,
      minZoomLevel: 0.8,
      maxZoomPixelRatio: 4,
      gestureSettingsMouse: { clickToZoom: false },
      gestureSettingsTouch: { clickToZoom: false },
    });
    viewerRef.current = viewer;

    viewer.addHandler('canvas-click', (event) => {
      if (!placingRef.current) return;
      const viewportPoint = viewer.viewport.pointFromPixel(event.position);
      const imagePoint = viewer.viewport.viewportToImageCoordinates(viewportPoint);
      onPlacePin([imagePoint.x, imagePoint.y]);
    });
    viewer.addHandler('animation', () => setTick((t) => t + 1));
    viewer.addHandler('update-viewport', () => setTick((t) => t + 1));

    return () => { viewer.destroy(); viewerRef.current = null; };
  }, [tileMeta, token, drawing.id, onPlacePin]);

  function pinPixel(x, y) {
    const viewer = viewerRef.current;
    if (!viewer) return null;
    const viewportPoint = viewer.viewport.imageToViewportCoordinates(x, y);
    return viewer.viewport.pixelFromPoint(viewportPoint, true);
  }

  return (
    <div className="relative w-full h-full bg-slate-800">
      {!tileMeta && (
        <div className="absolute inset-0 flex items-center justify-center text-slate-400 text-sm gap-2">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading drawing…
        </div>
      )}
      <div ref={containerRef} className="w-full h-full" style={{ cursor: placingPin ? 'crosshair' : undefined }} />
      {tileMeta && pins.map((pin) => {
        const px = pinPixel(pin.x, pin.y);
        if (!px) return null;
        return (
          <button
            key={pin.id}
            onClick={() => onPinClick(pin)}
            className={`absolute w-6 h-6 -translate-x-1/2 -translate-y-full rounded-full flex items-center justify-center text-white text-[10px] font-bold shadow-lg ${pin.resolved ? 'bg-slate-400' : 'bg-amber-500'}`}
            style={{ left: px.x, top: px.y }}
            title={pin.body}
          >
            <MessageSquare className="w-3 h-3" />
          </button>
        );
      })}
    </div>
  );
}

export default function GuestView() {
  const { token } = useParams();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [selectedDrawingId, setSelectedDrawingId] = useState(null);
  const [comments, setComments] = useState([]);
  const [placingPin, setPlacingPin] = useState(false);
  const [draftPin, setDraftPin] = useState(null); // {x, y} awaiting name+body
  const [guestName, setGuestName] = useState(() => localStorage.getItem('guest_name') || '');
  const [draftBody, setDraftBody] = useState('');
  const [openPin, setOpenPin] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');

  useEffect(() => {
    guestAPI.resolve(token)
      .then((res) => {
        setInfo(res.data);
        if (res.data.drawings.length > 0) setSelectedDrawingId(res.data.drawings[0].id);
      })
      .catch((err) => setError(err.response?.data?.detail || 'This share link is invalid or has expired.'));
  }, [token]);

  useEffect(() => {
    if (!selectedDrawingId) return;
    guestAPI.listComments(token, selectedDrawingId)
      .then((res) => setComments(res.data.comments || []))
      .catch(() => setComments([]));
  }, [token, selectedDrawingId]);

  const drawing = useMemo(() => info?.drawings.find((d) => d.id === selectedDrawingId), [info, selectedDrawingId]);
  const canComment = info?.permission === 'comment';

  async function submitComment() {
    if (!draftPin || !guestName.trim() || !draftBody.trim() || submitting) return;
    setSubmitting(true);
    setSubmitError('');
    try {
      localStorage.setItem('guest_name', guestName.trim());
      const res = await guestAPI.createComment(token, {
        drawing_id: selectedDrawingId, x: draftPin[0], y: draftPin[1],
        body: draftBody.trim(), guest_name: guestName.trim(),
      });
      setComments((prev) => [...prev, res.data]);
      setDraftPin(null);
      setDraftBody('');
      setPlacingPin(false);
    } catch (err) {
      setSubmitError(err.response?.data?.detail || 'Failed to post comment.');
    } finally {
      setSubmitting(false);
    }
  }

  if (error) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
        <div className="max-w-sm text-center">
          <AlertCircle className="w-10 h-10 text-rose-400 mx-auto mb-3" />
          <h1 className="text-lg font-semibold text-white">Link unavailable</h1>
          <p className="text-sm text-slate-400 mt-1">{error}</p>
        </div>
      </div>
    );
  }

  if (!info) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-400 gap-2 text-sm">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <header className="flex items-center justify-between px-5 py-3 border-b border-slate-800 bg-slate-900">
        <div className="flex items-center gap-2 text-white">
          <Sparkles className="w-4 h-4 text-indigo-400" />
          <span className="font-semibold text-sm">{info.project_name}</span>
          <span className="text-[10px] uppercase tracking-wider text-slate-500 border border-slate-700 rounded px-1.5 py-0.5 ml-2">
            {canComment ? 'View & comment' : 'View only'} · shared link
          </span>
        </div>
        {canComment && (
          <button
            onClick={() => setPlacingPin((v) => !v)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 ${placingPin ? 'bg-amber-500 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'}`}
          >
            <MessageSquare className="w-3.5 h-3.5" /> {placingPin ? 'Click the drawing to pin…' : 'Add comment'}
          </button>
        )}
      </header>

      <div className="flex-1 grid grid-cols-[200px_1fr] min-h-0">
        <aside className="bg-slate-900 border-r border-slate-800 p-3 overflow-auto">
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-2">Sheets</div>
          <div className="space-y-0.5">
            {info.drawings.map((d) => (
              <button
                key={d.id}
                onClick={() => setSelectedDrawingId(d.id)}
                className={`w-full text-left px-2 py-1.5 rounded text-xs ${d.id === selectedDrawingId ? 'bg-indigo-500/20 text-indigo-300' : 'text-slate-400 hover:bg-slate-800'}`}
              >
                {d.sheet_number ? <span className="mono mr-1">{d.sheet_number}</span> : null}
                {d.sheet_name || `Sheet ${d.page_number + 1}`}
              </button>
            ))}
            {info.drawings.length === 0 && <div className="text-xs text-slate-600 px-2">No sheets yet</div>}
          </div>
        </aside>

        <main className="relative min-h-0">
          {drawing ? (
            <GuestDrawingViewer
              token={token}
              drawing={drawing}
              pins={comments.filter((c) => !c.parent_id)}
              placingPin={placingPin}
              onPlacePin={(point) => { setDraftPin(point); setPlacingPin(false); }}
              onPinClick={(pin) => setOpenPin(pin)}
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-slate-500 text-sm">No sheet selected</div>
          )}

          {draftPin && (
            <div className="absolute inset-0 bg-slate-900/60 flex items-center justify-center z-20" onClick={() => setDraftPin(null)}>
              <div className="w-80 bg-white rounded-xl shadow-2xl p-4" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-slate-900">New comment</h3>
                  <button onClick={() => setDraftPin(null)}><X className="w-4 h-4 text-slate-400" /></button>
                </div>
                <input
                  value={guestName}
                  onChange={(e) => setGuestName(e.target.value)}
                  placeholder="Your name"
                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 mb-2 outline-none focus:border-indigo-500"
                />
                <textarea
                  value={draftBody}
                  onChange={(e) => setDraftBody(e.target.value)}
                  placeholder="Comment…"
                  rows={3}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-slate-300 outline-none focus:border-indigo-500 resize-none"
                />
                {submitError && <p className="text-xs text-rose-600 mt-1.5">{submitError}</p>}
                <button
                  onClick={submitComment}
                  disabled={submitting || !guestName.trim() || !draftBody.trim()}
                  className="mt-3 w-full py-2 rounded-lg bg-slate-900 text-white text-sm font-medium disabled:opacity-50 flex items-center justify-center gap-1.5"
                >
                  {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />} Post comment
                </button>
              </div>
            </div>
          )}

          {openPin && (
            <div className="absolute inset-0 bg-slate-900/60 flex items-center justify-center z-20" onClick={() => setOpenPin(null)}>
              <div className="w-80 bg-white rounded-xl shadow-2xl p-4" onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-slate-900">{openPin.display_name || 'Comment'}</span>
                  <button onClick={() => setOpenPin(null)}><X className="w-4 h-4 text-slate-400" /></button>
                </div>
                <p className="text-sm text-slate-700">{openPin.body}</p>
                {openPin.is_guest && <p className="text-[10px] text-slate-400 mt-2">Posted by a guest via this share link</p>}
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
