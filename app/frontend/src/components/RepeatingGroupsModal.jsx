import React, { useEffect, useState } from 'react';
import { X, Loader2, Layers, Plus, Trash2 } from 'lucide-react';
import { repeatingAPI } from '../services/api';

// Repeating Groups — memory/TOGAL_PARITY_REAUDIT.md #19: "take off one
// master unit (hotel room/apartment) -> apply to hundreds of identical
// spaces." Marking a drawing as a master unit here is what makes
// repeating_groups.apply_multiplier() scale its quantities everywhere
// project-wide totals are computed (rich export, estimating handoff).
export default function RepeatingGroupsModal({ projectId, drawings, onClose }) {
  const [units, setUnits] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ drawing_id: '', name: '', instance_count: 2, notes: '' });
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState(null);

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      const [unitsRes, previewRes] = await Promise.all([
        repeatingAPI.listMasterUnits(projectId),
        repeatingAPI.preview(projectId),
      ]);
      setUnits(unitsRes.data.master_units);
      setPreview(previewRes.data.master_units);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load repeating groups');
    }
  }

  const usedDrawingIds = new Set((units || []).map((u) => u.drawing_id));
  const eligibleDrawings = drawings.filter((d) => !usedDrawingIds.has(d.id));

  async function submitForm(e) {
    e.preventDefault();
    if (!form.drawing_id) return;
    setSaving(true);
    try {
      await repeatingAPI.createMasterUnit(projectId, {
        drawing_id: Number(form.drawing_id),
        name: form.name || 'Master unit',
        instance_count: Number(form.instance_count) || 1,
        notes: form.notes || null,
      });
      setForm({ drawing_id: '', name: '', instance_count: 2, notes: '' });
      setShowForm(false);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to create master unit');
    } finally {
      setSaving(false);
    }
  }

  async function updateCount(unit, instance_count) {
    setBusyId(unit.id);
    try {
      await repeatingAPI.updateMasterUnit(unit.id, { instance_count });
      load();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to update');
    } finally {
      setBusyId(null);
    }
  }

  async function remove(unit) {
    if (!window.confirm(`Remove "${unit.name}" as a master unit? Its quantities will revert to a ×1 count.`)) return;
    setBusyId(unit.id);
    try {
      await repeatingAPI.deleteMasterUnit(unit.id);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to delete');
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50" onClick={onClose}>
      <div className="w-[820px] max-w-[95vw] max-h-[88vh] overflow-hidden flex flex-col rounded-xl bg-white border border-slate-200 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5"><Layers className="w-4 h-4" /> Repeating groups</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
        </div>

        <div className="flex-1 overflow-auto px-5 py-4 space-y-5">
          <p className="text-xs text-slate-500">
            Measure one representative unit — a hotel room, an apartment layout — once, then mark its drawing as a master
            unit with an instance count. Its quantities are automatically multiplied everywhere project totals are
            computed (export, estimating handoff), without redrawing it dozens of times.
          </p>

          {error && <div className="text-xs text-rose-600">{error}</div>}

          <div className="border border-slate-200 rounded-lg overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-slate-50">
                <tr>
                  <th className="text-left px-3 py-2 font-medium text-slate-500">Master unit</th>
                  <th className="text-left px-3 py-2 font-medium text-slate-500">Drawing</th>
                  <th className="text-right px-3 py-2 font-medium text-slate-500">Instances</th>
                  <th className="w-10"></th>
                </tr>
              </thead>
              <tbody>
                {(units || []).map((u) => (
                  <tr key={u.id} className="border-t border-slate-100">
                    <td className="px-3 py-2">
                      <div className="font-medium text-slate-800">{u.name}</div>
                      {u.notes && <div className="text-slate-400">{u.notes}</div>}
                    </td>
                    <td className="px-3 py-2 text-slate-500">{u.drawing_name}</td>
                    <td className="px-3 py-2 text-right">
                      <input
                        type="number" min="1" defaultValue={u.instance_count}
                        onBlur={(e) => { const v = Number(e.target.value); if (v && v !== u.instance_count) updateCount(u, v); }}
                        disabled={busyId === u.id}
                        className="w-16 text-right rounded border border-slate-200 px-1.5 py-0.5"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <button onClick={() => remove(u)} disabled={busyId === u.id} className="p-1 text-slate-400 hover:text-rose-600">
                        {busyId === u.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                      </button>
                    </td>
                  </tr>
                ))}
                {units && units.length === 0 && (
                  <tr><td colSpan={4} className="px-3 py-6 text-center text-slate-400">No master units yet — every drawing counts once.</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {!showForm ? (
            <button
              onClick={() => setShowForm(true)}
              disabled={eligibleDrawings.length === 0}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 text-white text-xs font-medium hover:bg-slate-800 disabled:opacity-40"
            >
              <Plus className="w-3.5 h-3.5" /> Mark a drawing as a master unit
            </button>
          ) : (
            <form onSubmit={submitForm} className="border border-slate-200 rounded-lg p-3 space-y-2.5">
              <div className="grid grid-cols-2 gap-2.5">
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Drawing</span>
                  <select
                    required value={form.drawing_id} onChange={(e) => setForm({ ...form, drawing_id: e.target.value })}
                    className="mt-1 w-full text-xs rounded-lg border border-slate-300 px-2 py-1.5"
                  >
                    <option value="">Select a drawing…</option>
                    {eligibleDrawings.map((d) => (
                      <option key={d.id} value={d.id}>{d.sheet_number || d.sheet_name || d.original_filename}</option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Instance count</span>
                  <input
                    type="number" min="1" required value={form.instance_count}
                    onChange={(e) => setForm({ ...form, instance_count: e.target.value })}
                    className="mt-1 w-full text-xs rounded-lg border border-slate-300 px-2 py-1.5"
                  />
                </label>
              </div>
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Name</span>
                <input
                  required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="e.g. King Suite Type A"
                  className="mt-1 w-full text-xs rounded-lg border border-slate-300 px-2 py-1.5"
                />
              </label>
              <label className="block">
                <span className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold">Notes (optional)</span>
                <input
                  value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  placeholder="e.g. Floors 3-30, west wing"
                  className="mt-1 w-full text-xs rounded-lg border border-slate-300 px-2 py-1.5"
                />
              </label>
              <div className="flex items-center gap-2 pt-1">
                <button type="button" onClick={() => setShowForm(false)} className="px-3 py-1.5 text-xs rounded-lg border border-slate-300 text-slate-600">Cancel</button>
                <button type="submit" disabled={saving} className="px-3 py-1.5 text-xs rounded-lg bg-slate-900 text-white font-medium disabled:opacity-50 flex items-center gap-1.5">
                  {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />} Save
                </button>
              </div>
            </form>
          )}

          {preview && preview.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1.5">Preview — base vs. multiplied quantities</div>
              <div className="space-y-3">
                {preview.map((p) => (
                  <div key={p.master_unit.id} className="border border-slate-200 rounded-lg overflow-hidden">
                    <div className="px-3 py-1.5 bg-slate-50 text-xs font-medium text-slate-700">
                      {p.master_unit.name} — {p.master_unit.drawing_name} × {p.master_unit.instance_count}
                    </div>
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-slate-400">
                          <th className="text-left px-3 py-1 font-medium">Item</th>
                          <th className="text-right px-3 py-1 font-medium">1 unit</th>
                          <th className="text-right px-3 py-1 font-medium">× {p.master_unit.instance_count}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {p.base_rows.map((r, i) => (
                          <tr key={i} className="border-t border-slate-100">
                            <td className="px-3 py-1 text-slate-700">{r.item}</td>
                            <td className="px-3 py-1 text-right text-slate-500">{r.quantity} {r.unit}</td>
                            <td className="px-3 py-1 text-right font-medium text-slate-900">{p.multiplied_rows[i]?.quantity} {r.unit}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
