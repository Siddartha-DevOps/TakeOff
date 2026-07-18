import React, { useEffect, useState } from 'react';
import { X, Loader2, FolderTree, Pencil, Check, FileText } from 'lucide-react';
import { planSetAPI } from '../services/api';

// Plan-set organizer — Togal's "auto-name & organize hundreds of sheets".
// Shows the project's sheets grouped by discipline (Architectural, Structural,
// MEP…) and ordered by sheet number, with inline rename/reclassify. Mirrors
// routes/plan_set_routes.py.

export default function PlanSetModal({ projectId, selectedDrawingId, onSelectSheet, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState({ sheet_number: '', sheet_name: '' });
  const [savingId, setSavingId] = useState(null);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await planSetAPI.get(projectId);
      setData(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not load the plan set.');
    } finally {
      setLoading(false);
    }
  }

  function startEdit(sheet) {
    setEditingId(sheet.id);
    setDraft({ sheet_number: sheet.sheet_number || '', sheet_name: sheet.sheet_name || '' });
  }

  async function saveEdit(sheet) {
    setSavingId(sheet.id);
    try {
      await planSetAPI.updateSheet(sheet.id, {
        sheet_number: draft.sheet_number || null,
        sheet_name: draft.sheet_name || null,
      });
      setEditingId(null);
      await load();   // regroups if the discipline changed
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save the sheet.');
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col">
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
          <div className="w-9 h-9 rounded-lg bg-sky-500/10 flex items-center justify-center">
            <FolderTree className="w-5 h-5 text-sky-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-900">Plan Set</h2>
            <p className="text-xs text-slate-500">
              {data ? `${data.sheet_count} sheets · ${data.disciplines.length} disciplines` : 'Organizing…'}
            </p>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-400 gap-2">
              <Loader2 className="w-5 h-5 animate-spin" /> Loading plan set…
            </div>
          )}
          {!loading && error && <div className="py-12 text-center text-sm text-rose-600">{error}</div>}

          {!loading && !error && data && data.sheet_count === 0 && (
            <div className="py-12 text-center text-sm text-slate-500">No sheets uploaded yet.</div>
          )}

          {!loading && !error && data && data.disciplines.map((group) => (
            <div key={group.discipline} className="mb-5">
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-[11px] font-mono font-semibold text-slate-500 bg-slate-100 rounded px-1.5 py-0.5">
                  {group.discipline}
                </span>
                <span className="text-sm font-medium text-slate-800">{group.name}</span>
                <span className="text-[11px] text-slate-400">({group.count})</span>
              </div>
              <div className="space-y-1">
                {group.sheets.map((sheet) => {
                  const isEditing = editingId === sheet.id;
                  const isSelected = sheet.id === selectedDrawingId;
                  return (
                    <div
                      key={sheet.id}
                      className={`flex items-center gap-2 rounded-lg border px-3 py-1.5 ${
                        isSelected ? 'border-sky-400 bg-sky-50' : 'border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <FileText className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                      {isEditing ? (
                        <>
                          <input
                            value={draft.sheet_number}
                            onChange={(e) => setDraft((d) => ({ ...d, sheet_number: e.target.value }))}
                            placeholder="A-101"
                            className="w-20 px-1.5 py-0.5 text-xs font-mono border border-slate-300 rounded"
                          />
                          <input
                            value={draft.sheet_name}
                            onChange={(e) => setDraft((d) => ({ ...d, sheet_name: e.target.value }))}
                            placeholder="Sheet name"
                            className="flex-1 px-1.5 py-0.5 text-sm border border-slate-300 rounded"
                          />
                          <button
                            onClick={() => saveEdit(sheet)}
                            disabled={savingId === sheet.id}
                            className="p-1 rounded bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50"
                          >
                            {savingId === sheet.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                          </button>
                        </>
                      ) : (
                        <>
                          <button
                            onClick={() => onSelectSheet?.(sheet.id)}
                            className="flex-1 flex items-center gap-2 text-left min-w-0"
                          >
                            {sheet.sheet_number && (
                              <span className="text-xs font-mono text-slate-500 flex-shrink-0">{sheet.sheet_number}</span>
                            )}
                            <span className="text-sm text-slate-800 truncate">{sheet.sheet_name}</span>
                          </button>
                          <button
                            onClick={() => startEdit(sheet)}
                            title="Rename / reclassify"
                            className="p-1 rounded text-slate-400 hover:text-slate-700 hover:bg-slate-100"
                          >
                            <Pencil className="w-3.5 h-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-400">
          Grouped by discipline from OCR-read sheet numbers. Click a sheet to open it; use the pencil to fix its number/name.
        </div>
      </div>
    </div>
  );
}
