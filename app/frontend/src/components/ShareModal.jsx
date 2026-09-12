import React, { useEffect, useState } from 'react';
import { X, Loader2, Share2, Copy, Trash2, Check, Plus } from 'lucide-react';
import { sharingAPI } from '../services/api';

// External collaboration — create account-free share links to a project
// (Togal's "collaborate with users outside your account"). Mirrors
// routes/sharing_routes.py.

export default function ShareModal({ projectId, projectName, onClose }) {
  const [shares, setShares] = useState(null);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [copiedId, setCopiedId] = useState(null);
  const [form, setForm] = useState({ email: '', role: 'viewer', expires_in_days: '' });

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [projectId]);

  async function load() {
    try {
      const res = await sharingAPI.list(projectId);
      setShares(res.data.shares || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load shares.');
    }
  }

  function linkFor(share) {
    return `${window.location.origin}${share.path}`;
  }

  async function createShare(e) {
    e?.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await sharingAPI.create(projectId, {
        email: form.email.trim() || null,
        role: form.role,
        expires_in_days: form.expires_in_days ? Number(form.expires_in_days) : null,
      });
      setForm({ email: '', role: 'viewer', expires_in_days: '' });
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not create the link.');
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id) {
    try {
      await sharingAPI.revoke(id);
      await load();
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not revoke.');
    }
  }

  async function copy(share) {
    try {
      await navigator.clipboard.writeText(linkFor(share));
      setCopiedId(share.id);
      setTimeout(() => setCopiedId(null), 1500);
    } catch { /* clipboard unavailable */ }
  }

  const active = (shares || []).filter((s) => !s.revoked);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
          <div className="w-9 h-9 rounded-lg bg-teal-500/10 flex items-center justify-center">
            <Share2 className="w-5 h-5 text-teal-600" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-900">Share project</h2>
            <p className="text-xs text-slate-500 truncate">{projectName} · people outside your team can open the link, no account needed</p>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
          {error && <div className="text-xs text-rose-600 bg-rose-50 rounded-lg p-3">{error}</div>}

          <form onSubmit={createShare} className="flex flex-wrap items-end gap-2 bg-slate-50 rounded-lg p-3">
            <label className="flex flex-col gap-1 flex-1 min-w-[160px]">
              <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Email (optional)</span>
              <input
                type="email" value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                placeholder="sub@partner.com"
                className="px-2 py-1.5 text-sm border border-slate-300 rounded-lg"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Access</span>
              <select
                value={form.role}
                onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
                className="px-2 py-1.5 text-sm border border-slate-300 rounded-lg bg-white"
              >
                <option value="viewer">Can view</option>
                <option value="commenter">Can comment</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">Expires (days)</span>
              <input
                type="number" min="1" value={form.expires_in_days}
                onChange={(e) => setForm((f) => ({ ...f, expires_in_days: e.target.value }))}
                placeholder="never"
                className="w-24 px-2 py-1.5 text-sm border border-slate-300 rounded-lg"
              />
            </label>
            <button
              type="submit" disabled={creating}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-teal-600 text-white hover:bg-teal-700 disabled:opacity-50"
            >
              {creating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              Create link
            </button>
          </form>

          <div>
            <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400 mb-2">Active links</div>
            {shares === null ? (
              <div className="flex items-center gap-2 text-slate-400 text-sm py-4"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
            ) : active.length === 0 ? (
              <div className="text-sm text-slate-500">No active share links yet.</div>
            ) : (
              <div className="space-y-1.5">
                {active.map((s) => (
                  <div key={s.id} className="flex items-center gap-2 rounded-lg border border-slate-200 px-3 py-2">
                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-slate-800 truncate">
                        {s.email || 'Anyone with the link'}
                        <span className="ml-2 text-[10px] uppercase font-semibold px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500">{s.role}</span>
                      </div>
                      <div className="text-[11px] text-slate-400 truncate font-mono">{linkFor(s)}</div>
                    </div>
                    <button onClick={() => copy(s)} title="Copy link" className="p-1.5 rounded text-slate-500 hover:bg-slate-100">
                      {copiedId === s.id ? <Check className="w-4 h-4 text-emerald-500" /> : <Copy className="w-4 h-4" />}
                    </button>
                    <button onClick={() => revoke(s.id)} title="Revoke" className="p-1.5 rounded text-rose-500 hover:bg-rose-50">
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-400">
          Guests open the link with no login. Revoke any time to cut access instantly.
        </div>
      </div>
    </div>
  );
}
