import React, { useEffect, useState } from 'react';
import { X, Loader2, Brain, CheckCircle2, Circle, AlertTriangle, FileText } from 'lucide-react';
import { mlAPI } from '../services/api';

// AI / Model dashboard — surfaces the training flywheel that's otherwise
// backend-only: the model registry (eval_routes model-versions with accuracy
// metrics + ACTIVE/CANDIDATE stage) and the active-learning review queue
// (active_learning_routes) that ranks which drawings to label next.

const pct = (n) => (n == null ? '—' : `${(n * 100).toFixed(1)}%`);
const err = (n) => (n == null ? '—' : `${n.toFixed(1)}%`);

export default function AIDashboardModal({ projectId, onSelectDrawing, onClose }) {
  const [models, setModels] = useState(null);
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [m, q] = await Promise.allSettled([
          mlAPI.listModelVersions(),
          mlAPI.reviewQueue(projectId),
        ]);
        if (cancelled) return;
        setModels(m.status === 'fulfilled' ? (m.value.data || []) : []);
        setQueue(q.status === 'fulfilled' ? (q.value.data.queue || []) : []);
      } catch (e) {
        if (!cancelled) setError('Could not load the AI dashboard.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [projectId]);

  const active = (models || []).find((m) => m.stage === 'ACTIVE');

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
          <div className="w-9 h-9 rounded-lg bg-violet-500/10 flex items-center justify-center">
            <Brain className="w-5 h-5 text-violet-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-900">AI &amp; Model Dashboard</h2>
            <p className="text-xs text-slate-500">Model accuracy · what to label next</p>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-6">
          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-400 gap-2">
              <Loader2 className="w-5 h-5 animate-spin" /> Loading…
            </div>
          )}
          {!loading && error && <div className="py-8 text-center text-sm text-rose-600">{error}</div>}

          {!loading && !error && (
            <>
              {/* Model registry */}
              <section>
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">Model registry</h3>
                {(!models || models.length === 0) ? (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-700 flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                    <span>No trained models registered yet. Raster AI stays disabled until weights are trained + promoted — see <code>ml/TRAINING.md</code>.</span>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {models.map((m) => (
                      <div key={m.id} className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2">
                        {m.stage === 'ACTIVE'
                          ? <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                          : <Circle className="w-4 h-4 text-slate-300 flex-shrink-0" />}
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-slate-800 truncate">
                            {m.name} <span className="text-slate-400 font-normal">{m.version_string}</span>
                          </div>
                          <div className="text-[11px] text-slate-500">
                            mIoU {pct(m.miou)} · mAP {pct(m.map_score)} · err {err(m.measurement_error_pct)}
                          </div>
                        </div>
                        <span className={`ml-auto text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full ${
                          m.stage === 'ACTIVE' ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'
                        }`}>{m.stage}</span>
                      </div>
                    ))}
                  </div>
                )}
                {active && (
                  <p className="mt-2 text-[11px] text-slate-400">
                    Serving <b>{active.name} {active.version_string}</b>.
                  </p>
                )}
              </section>

              {/* Active-learning review queue */}
              <section>
                <h3 className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
                  Label next — review queue
                </h3>
                {(!queue || queue.length === 0) ? (
                  <div className="text-xs text-slate-500">
                    Nothing to review yet. As the AI runs and users accept/reject detections, the sheets the model is least sure about (or gets corrected most) surface here.
                  </div>
                ) : (
                  <div className="space-y-1">
                    {queue.map((row) => (
                      <button
                        key={row.drawing_id}
                        onClick={() => onSelectDrawing?.(row.drawing_id)}
                        className="w-full flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-1.5 text-left hover:bg-slate-50"
                      >
                        <FileText className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                        <span className="text-sm text-slate-800 truncate flex-1">
                          {row.sheet_name || `Sheet #${row.drawing_id}`}
                        </span>
                        <span className="text-[11px] text-slate-400 whitespace-nowrap">
                          conf {pct(row.mean_confidence)} · {row.n_rejections}✕
                        </span>
                        <span className="text-[11px] font-mono font-semibold text-violet-600 whitespace-nowrap">
                          {Number(row.priority).toFixed(2)}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </section>
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-400">
          Priority combines model uncertainty with human disagreement. Label high-priority sheets first to improve the model fastest.
        </div>
      </div>
    </div>
  );
}
