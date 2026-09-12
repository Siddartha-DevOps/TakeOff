import React from 'react';
import { X, HelpCircle, Upload, Sparkles, Search, Calculator, FolderTree, Share2, MessageSquare, GitCompare } from 'lucide-react';

// In-app help — a slide-over with the core how-tos, mapped to the real toolbar
// actions. Static content (no backend); opened from the "?" button.

const TOPICS = [
  { icon: Upload, title: 'Upload & organize plans', body: 'Drag PDFs/images into a project. Multi-page sets split into sheets automatically; the Sheets panel groups them by discipline and lets you rename.' },
  { icon: Sparkles, title: 'Run an AI takeoff', body: 'Open a sheet and hit AI/AUTODETECT. Vector PDFs measure geometrically; scanned sheets use the trained model. Accept, reject, or edit any detection — your corrections train the model.' },
  { icon: Search, title: 'Search & count', body: 'Use the Search panel: type "outlets" (text), or switch to Count-all to get a total plus a per-sheet breakdown. "Highlight on this sheet" drops matches onto the drawing.' },
  { icon: Calculator, title: 'Estimate', body: 'The Estimate button turns a sheet\'s takeoff into priced trade line items (assemblies). Pick or create a cost book, then Save & export .xlsx.' },
  { icon: FolderTree, title: 'Plan set', body: 'The Sheets button shows every sheet grouped by discipline (Architectural, Structural, MEP…). Click to open; use the pencil to fix a sheet number/name.' },
  { icon: GitCompare, title: 'Compare revisions', body: 'Compare two versions of a drawing to see what changed between issues.' },
  { icon: MessageSquare, title: 'Chat with the plans', body: 'Ask the chat questions about rooms, quantities, or scope — or have it draft an RFP/RFI.' },
  { icon: Share2, title: 'Share with anyone', body: 'The Share button creates a link for people outside your team — no account needed. Choose view or comment access, set an expiry, revoke anytime.' },
];

export default function HelpPanel({ onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="w-full max-w-md h-full bg-white shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-200">
          <div className="w-9 h-9 rounded-lg bg-indigo-500/10 flex items-center justify-center">
            <HelpCircle className="w-5 h-5 text-indigo-600" />
          </div>
          <h2 className="text-base font-semibold text-slate-900">Help &amp; how-tos</h2>
          <button onClick={onClose} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-500">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex-1 overflow-auto p-5 space-y-4">
          {TOPICS.map((t) => (
            <div key={t.title} className="flex gap-3">
              <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center flex-shrink-0">
                <t.icon className="w-4 h-4 text-slate-500" />
              </div>
              <div>
                <div className="text-sm font-medium text-slate-900">{t.title}</div>
                <p className="text-[13px] text-slate-500 mt-0.5">{t.body}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="px-5 py-3 border-t border-slate-200 text-[11px] text-slate-400">
          Need more? Email support or open the docs — this panel covers the essentials to get a takeoff done.
        </div>
      </div>
    </div>
  );
}
