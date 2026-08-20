import React, { useEffect, useState } from 'react';
import { X, Loader2, FileSpreadsheet, FileText, RefreshCw, IndianRupee } from 'lucide-react';
import { indiaAPI } from '../services/api';

// India BOQ panel — turns a drawing's AI detection into an IS 1200 metric
// takeoff, prices it against the DSR/SOR rate book, and finalizes the tender
// waterfall (overheads & profit -> contingency -> GST). Mirrors
// routes/india_routes.py: GET /api/india/drawings/{id}/boq (+ .xlsx / .pdf).
// This is the India-specific estimating layer Togal has no equivalent for.

const inr = (n) =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(Number(n || 0));

const num = (n, d = 2) =>
  new Intl.NumberFormat('en-IN', { maximumFractionDigits: d }).format(Number(n || 0));

// Backend wants gst_rate as a fraction (0.18); the UI collects a percent (18).
const DEFAULTS = { overhead_profit_pct: 15, contingency_pct: 3, gst_pct: 18, inter_state: false };

export default function IndiaBOQPanel({ drawing, onClose }) {
  const [estimate, setEstimate] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(null); // 'xlsx' | 'pdf' | null
  const [form, setForm] = useState(DEFAULTS);

  const params = {
    overhead_profit_pct: Number(form.overhead_profit_pct),
    contingency_pct: Number(form.contingency_pct),
    gst_rate: Number(form.gst_pct) / 100,
    inter_state: form.inter_state,
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drawing?.id]);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res = await indiaAPI.getBOQ(drawing.id, params);
      setEstimate(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || 'Could not build the BOQ for this drawing.');
      setEstimate(null);
    } finally {
      setLoading(false);
    }
  }

  async function download(fmt) {
    setDownloading(fmt);
    try {
      const res = await indiaAPI.exportBOQ(drawing.id, fmt, params);
      const url = window.URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement('a');
      a.href = url;
      const base = (drawing.sheet_name || drawing.original_filename || `drawing_${drawing.id}`)
        .replace(/\.[^.]+$/, '');
      a.download = `BOQ_${base}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.response?.data?.detail || `Could not export ${fmt.toUpperCase()}.`);
    } finally {
      setDownloading(null);
    }
  }

  const boq = estimate?.boq || [];
  const summary = estimate?.summary;
  const gst = summary?.gst;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
          <div className="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
            <IndianRupee className="w-5 h-5 text-emerald-600" />
          </div>
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-slate-900">Bill of Quantities (India)</h2>
            <p className="text-xs text-slate-500 truncate">
              {drawing?.sheet_name || drawing?.original_filename || `Drawing ${drawing?.id}`}
              {estimate?.edition ? ` · ${estimate.edition}` : ''}
            </p>
          </div>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tender controls */}
        <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex flex-wrap items-end gap-3">
          {[
            { key: 'overhead_profit_pct', label: 'Overheads & Profit %' },
            { key: 'contingency_pct', label: 'Contingency %' },
            { key: 'gst_pct', label: 'GST %' },
          ].map(({ key, label }) => (
            <label key={key} className="flex flex-col gap-1">
              <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">{label}</span>
              <input
                type="number"
                min="0"
                step="0.5"
                value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
                className="w-24 px-2 py-1.5 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-emerald-500/30"
              />
            </label>
          ))}
          <label className="flex items-center gap-1.5 text-xs text-slate-600 pb-2">
            <input
              type="checkbox"
              checked={form.inter_state}
              onChange={(e) => setForm((f) => ({ ...f, inter_state: e.target.checked }))}
              className="rounded border-slate-300"
            />
            Inter-state (IGST)
          </label>
          <button
            onClick={load}
            disabled={loading}
            className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            Recalculate
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto px-5 py-4">
          {loading && (
            <div className="flex items-center justify-center py-16 text-slate-400 gap-2">
              <Loader2 className="w-5 h-5 animate-spin" /> Building priced BOQ…
            </div>
          )}

          {!loading && error && (
            <div className="py-12 text-center">
              <p className="text-sm text-rose-600">{error}</p>
              <p className="text-xs text-slate-400 mt-2">
                A BOQ needs an AI detection on this drawing. Run the AI takeoff first.
              </p>
            </div>
          )}

          {!loading && !error && estimate && (
            <>
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500 border-b border-slate-200">
                    <th className="py-2 pr-2">Code</th>
                    <th className="py-2 pr-2">Description</th>
                    <th className="py-2 pr-2 text-right">Qty</th>
                    <th className="py-2 pr-2">Unit</th>
                    <th className="py-2 pr-2 text-right">Rate</th>
                    <th className="py-2 pl-2 text-right">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {boq.map((row, i) => (
                    <tr key={`${row.code}-${i}`} className="border-b border-slate-100">
                      <td className="py-2 pr-2 font-mono text-xs text-slate-500">{row.code}</td>
                      <td className="py-2 pr-2 text-slate-800">{row.description}</td>
                      <td className="py-2 pr-2 text-right tabular-nums">{num(row.quantity, 3)}</td>
                      <td className="py-2 pr-2 text-slate-500">{row.unit}</td>
                      <td className="py-2 pr-2 text-right tabular-nums text-slate-600">{num(row.rate)}</td>
                      <td className="py-2 pl-2 text-right tabular-nums font-medium">{inr(row.amount)}</td>
                    </tr>
                  ))}
                  {boq.length === 0 && (
                    <tr>
                      <td colSpan={6} className="py-8 text-center text-slate-400 text-sm">
                        No priced items — the detection produced no measurable quantities.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>

              {/* Tender waterfall */}
              {summary && (
                <div className="mt-5 ml-auto w-full max-w-sm text-sm space-y-1.5">
                  <Row label="Subtotal (works)" value={inr(summary.subtotal)} />
                  <Row
                    label={`Overheads & profit (${num(summary.overhead_profit_pct)}%)`}
                    value={inr(summary.overhead_profit)}
                  />
                  <Row label={`Contingency (${num(summary.contingency_pct)}%)`} value={inr(summary.contingency)} />
                  <Row label="Taxable value" value={inr(summary.taxable_value)} bold />
                  {gst && gst.igst > 0 && <Row label={`IGST (${num(gst.rate * 100)}%)`} value={inr(gst.igst)} />}
                  {gst && gst.cgst > 0 && (
                    <>
                      <Row label={`CGST (${num((gst.rate * 100) / 2)}%)`} value={inr(gst.cgst)} />
                      <Row label={`SGST (${num((gst.rate * 100) / 2)}%)`} value={inr(gst.sgst)} />
                    </>
                  )}
                  <div className="flex justify-between pt-2 mt-1 border-t border-slate-300 text-base font-semibold text-slate-900">
                    <span>Grand total</span>
                    <span className="tabular-nums">{inr(summary.grand_total)}</span>
                  </div>
                </div>
              )}

              {estimate?.rate_book_note && (
                <p className="mt-4 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                  {estimate.rate_book_note}
                </p>
              )}
            </>
          )}
        </div>

        {/* Footer — downloads */}
        <div className="px-5 py-3 border-t border-slate-200 flex items-center gap-2">
          <span className="text-xs text-slate-400">Amounts in INR</span>
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => download('xlsx')}
              disabled={!estimate || !!downloading}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium border border-emerald-600 text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
            >
              {downloading === 'xlsx' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <FileSpreadsheet className="w-4 h-4" />
              )}
              Excel
            </button>
            <button
              onClick={() => download('pdf')}
              disabled={!estimate || !!downloading}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            >
              {downloading === 'pdf' ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileText className="w-4 h-4" />}
              PDF
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, bold }) {
  return (
    <div className={`flex justify-between ${bold ? 'font-medium text-slate-900' : 'text-slate-600'}`}>
      <span>{label}</span>
      <span className="tabular-nums">{value}</span>
    </div>
  );
}
