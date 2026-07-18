import React, { useEffect, useMemo, useState } from 'react';
import { X, Loader2, Calculator, RefreshCw, Save, DollarSign } from 'lucide-react';
import { estimatingAPI } from '../services/api';

// Trade assemblies estimate for a drawing — one measured quantity (floor area,
// wall LF, door count) expands into priced trade line items. Mirrors
// routes/assemblies_routes.py: GET /estimating/drawings/{id}/assemblies (+ cost
// book) and the cost-book CRUD. This is the generic (non-India) estimating layer.

const money = (n, currency = 'USD') =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 2 })
    .format(Number(n || 0));

const num = (n, d = 2) =>
  new Intl.NumberFormat('en-US', { maximumFractionDigits: d }).format(Number(n || 0));

export default function EstimatePanel({ drawing, onClose }) {
  const [estimate, setEstimate] = useState(null);
  const [costBooks, setCostBooks] = useState([]);
  const [costBookId, setCostBookId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(false);
  const [priceDraft, setPriceDraft] = useState({});   // item -> unit_cost while editing
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    estimatingAPI.listCostBooks().then((r) => setCostBooks(r.data.cost_books || [])).catch(() => {});
  }, []);

  useEffect(() => {
    load(costBookId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawing?.id, costBookId]);

  async function load(bookId) {
    setLoading(true);
    setError(null);
    try {
      const res = await estimatingAPI.drawingAssemblies(drawing.id, bookId);
      setEstimate(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'No takeoff quantities for this drawing yet — run AI/AUTODETECT first.');
      setEstimate(null);
    } finally {
      setLoading(false);
    }
  }

  // Distinct items across the line items — the rows a cost book prices.
  const items = useMemo(() => {
    const map = new Map();
    (estimate?.line_items || []).forEach((l) => {
      if (!map.has(l.item)) map.set(l.item, { item: l.item, unit: l.unit });
    });
    return [...map.values()];
  }, [estimate]);

  function startEditing() {
    const draft = {};
    const active = costBooks.find((b) => b.id === costBookId);
    const existing = new Map((active?.items || []).map((i) => [i.item, i.unit_cost]));
    items.forEach((it) => { draft[it.item] = existing.get(it.item) ?? 0; });
    setPriceDraft(draft);
    setEditing(true);
  }

  async function saveCostBook() {
    setSaving(true);
    try {
      const payload = {
        name: `Cost book — ${new Date().toISOString().slice(0, 10)}`,
        currency: 'USD',
        items: items.map((it) => ({ item: it.item, unit: it.unit, unit_cost: Number(priceDraft[it.item] || 0) })),
      };
      const res = await estimatingAPI.createCostBook(payload);
      setCostBooks((b) => [...b, res.data]);
      setCostBookId(res.data.id);      // triggers a re-priced reload
      setEditing(false);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not save cost book.');
    } finally {
      setSaving(false);
    }
  }

  const byTrade = estimate?.by_trade || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
          <div className="w-9 h-9 rounded-lg bg-indigo-500/10 flex items-center justify-center">
            <Calculator className="w-5 h-5 text-indigo-600" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-900">Estimate — Trade Assemblies</h2>
            <p className="text-xs text-slate-500 truncate">
              {drawing?.sheet_name || drawing?.original_filename || `Drawing ${drawing?.id}`}
            </p>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Controls */}
        <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-600">
            <DollarSign className="w-3.5 h-3.5 text-slate-400" />
            Cost book
            <select
              value={costBookId ?? ''}
              onChange={(e) => setCostBookId(e.target.value ? Number(e.target.value) : null)}
              className="px-2 py-1 text-sm border border-slate-300 rounded-lg bg-white"
            >
              <option value="">None (quantities only)</option>
              {costBooks.map((b) => (
                <option key={b.id} value={b.id}>{b.name}</option>
              ))}
            </select>
          </label>
          <div className="ml-auto flex items-center gap-2">
            {!editing ? (
              <button
                onClick={startEditing}
                disabled={!estimate || items.length === 0}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-slate-300 hover:bg-slate-100 disabled:opacity-40"
              >
                <DollarSign className="w-3.5 h-3.5" /> Set prices
              </button>
            ) : (
              <button
                onClick={saveCostBook}
                disabled={saving}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
              >
                {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                Save cost book
              </button>
            )}
            <button
              onClick={() => load(costBookId)}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Recalculate
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-400 gap-2">
              <Loader2 className="w-5 h-5 animate-spin" /> Building estimate…
            </div>
          )}

          {!loading && error && <div className="py-12 text-center text-sm text-rose-600">{error}</div>}

          {!loading && !error && estimate && (
            <>
              {estimate.drivers && Object.keys(estimate.drivers).length > 0 && (
                <div className="mb-4 flex flex-wrap gap-2">
                  {Object.entries(estimate.drivers).map(([k, v]) => (
                    <span key={k} className="text-[11px] rounded-full bg-slate-100 text-slate-600 px-2.5 py-1">
                      {k.replace(/_/g, ' ')}: <b>{num(v)}</b>
                    </span>
                  ))}
                </div>
              )}

              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-2">Item</th>
                    <th className="py-2 pr-2">Trade</th>
                    <th className="py-2 pr-2 text-right">Qty</th>
                    <th className="py-2 pr-2">Unit</th>
                    <th className="py-2 pr-2 text-right">{editing ? 'Unit price' : 'Rate'}</th>
                    <th className="py-2 pl-2 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {(estimate.line_items || []).map((l, i) => (
                    <tr key={`${l.item}-${i}`} className="border-b border-slate-100">
                      <td className="py-2 pr-2 text-slate-800">{l.item}</td>
                      <td className="py-2 pr-2 text-slate-500">{l.trade}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{num(l.quantity, 2)}</td>
                      <td className="py-2 pr-2 text-slate-500">{l.unit}</td>
                      <td className="py-2 pr-2 text-right tabular-nums text-slate-600">
                        {editing ? (
                          <input
                            type="number" min="0" step="0.01"
                            value={priceDraft[l.item] ?? 0}
                            onChange={(e) => setPriceDraft((d) => ({ ...d, [l.item]: e.target.value }))}
                            className="w-20 px-1.5 py-0.5 text-right border border-slate-300 rounded"
                          />
                        ) : num(l.unit_cost)}
                      </td>
                      <td className="py-2 pl-2 text-right tabular-nums font-medium">{money(l.amount)}</td>
                    </tr>
                  ))}
                  {(estimate.line_items || []).length === 0 && (
                    <tr><td colSpan={6} className="py-8 text-center text-slate-400 text-sm">
                      No assemblies mapped — the takeoff produced no floor area, wall LF, or door count.
                    </td></tr>
                  )}
                </tbody>
              </table>

              {Object.keys(byTrade).length > 0 && (
                <div className="mt-5 ml-auto w-full max-w-xs text-sm space-y-1">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-slate-400">By trade</div>
                  {Object.entries(byTrade).map(([trade, amt]) => (
                    <div key={trade} className="flex justify-between text-slate-600">
                      <span>{trade}</span><span className="tabular-nums">{money(amt)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between pt-2 mt-1 border-t border-slate-300 text-base font-semibold text-slate-900">
                    <span>Total</span><span className="tabular-nums">{money(estimate.total)}</span>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-400">
          Assemblies auto-mapped from this drawing's takeoff. Select or create a cost book to price them.
        </div>
      </div>
    </div>
  );
}
