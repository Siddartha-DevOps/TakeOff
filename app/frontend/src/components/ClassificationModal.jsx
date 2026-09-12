import React, { useEffect, useState } from 'react';
import { X, Loader2, Library, Plus, Trash2, Check } from 'lucide-react';
import { classificationAPI } from '../services/api';

// Classification-library templates — org-level reusable condition sets applied
// to a project in one click (Togal's classification library). Mirrors
// routes/classification_routes.py.

export default function ClassificationModal({ projectId, onClose }) {
  const [templates, setTemplates] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [appliedId, setAppliedId] = useState(null);

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      const res = await classificationAPI.list();
      setTemplates(res.data.templates || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load templates.');
    }
  }

  async function seed() {
    setBusy(true); setError(null);
    try { await classificationAPI.seed(); await load(); }
    catch (err) { setError(err.response?.data?.detail || 'Could not add the standard library.'); }
    finally { setBusy(false); }
  }

  async function apply(t) {
    setBusy(true); setError(null);
    try {
      const res = await classificationAPI.apply(t.id, projectId);
      setAppliedId(t.id);
      setTimeout(() => setAppliedId(null), 2000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not apply to this project.');
    } finally { setBusy(false); }
  }

  async function remove(id) {
    try { await classificationAPI.remove(id); await load(); }
    catch (err) { setError(err.response?.data?.detail || 'Could not delete.'); }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
          <div className="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center">
            <Library className="w-5 h-5 text-amber-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-900">Classification library</h2>
            <p className="text-xs text-slate-500">Reusable condition sets — apply one to this project in a click</p>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-2">
          {error && <div className="text-xs text-rose-600 bg-rose-50 rounded-lg p-3">{error}</div>}

          {templates === null ? (
            <div className="flex items-center gap-2 text-slate-400 text-sm py-6"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
          ) : templates.length === 0 ? (
            <div className="text-center py-8">
              <p className="text-sm text-slate-500 mb-3">No classification templates yet.</p>
              <button onClick={seed} disabled={busy} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50">
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                Add the standard library
              </button>
            </div>
          ) : (
            templates.map((t) => (
              <div key={t.id} className="flex items-center gap-3 rounded-lg border border-slate-200 px-3 py-2">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-slate-800 truncate">
                    {t.name}
                    {t.is_default && <span className="ml-2 text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">default</span>}
                  </div>
                  <div className="text-[11px] text-slate-400">{t.item_count} classifications</div>
                </div>
                <button
                  onClick={() => apply(t)} disabled={busy}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800 disabled:opacity-50"
                >
                  {appliedId === t.id ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : null}
                  {appliedId === t.id ? 'Applied' : 'Apply to project'}
                </button>
                <button onClick={() => remove(t.id)} title="Delete" className="p-1.5 rounded text-rose-500 hover:bg-rose-50">
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))
          )}
          {templates && templates.length > 0 && (
            <button onClick={seed} disabled={busy} className="mt-1 text-xs text-amber-700 hover:underline">+ add another standard library</button>
          )}
        </div>

        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-400">
          Applying a template creates its conditions on this project's takeoff.
        </div>
      </div>
    </div>
  );
}
