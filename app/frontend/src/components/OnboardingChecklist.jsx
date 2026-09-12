import React, { useState } from 'react';
import { X, CheckCircle2, Circle, Rocket } from 'lucide-react';

// First-run getting-started checklist. Shows once per browser (localStorage),
// nudging the estimator through the core flow. Dismissible; reappears never
// after "Got it" unless localStorage is cleared.

const KEY = 'takeoff_onboarding_dismissed_v1';

const STEPS = [
  { label: 'Upload a plan set', hint: 'Drag PDFs into the project' },
  { label: 'Run an AI takeoff', hint: 'Open a sheet → AI / AUTODETECT' },
  { label: 'Search & count elements', hint: 'Search panel → Count-all' },
  { label: 'Build a priced estimate', hint: 'Estimate → cost book → export' },
  { label: 'Share with a teammate', hint: 'Share → create a link' },
];

export function onboardingDismissed() {
  try { return localStorage.getItem(KEY) === '1'; } catch { return true; }
}

export default function OnboardingChecklist({ onOpenHelp }) {
  const [dismissed, setDismissed] = useState(onboardingDismissed());
  if (dismissed) return null;

  function dismiss() {
    try { localStorage.setItem(KEY, '1'); } catch { /* ignore */ }
    setDismissed(true);
  }

  return (
    <div className="fixed bottom-4 right-4 z-40 w-72 bg-white rounded-xl shadow-2xl border border-slate-200">
      <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-100">
        <div className="w-7 h-7 rounded-lg bg-emerald-500/10 flex items-center justify-center">
          <Rocket className="w-4 h-4 text-emerald-600" />
        </div>
        <span className="text-sm font-semibold text-slate-900">Get started</span>
        <button onClick={dismiss} className="ml-auto p-1 rounded hover:bg-slate-100 text-slate-400">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="p-3 space-y-1.5">
        {STEPS.map((s, i) => (
          <div key={s.label} className="flex items-start gap-2">
            {i === 0 ? <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 flex-shrink-0" />
                     : <Circle className="w-4 h-4 text-slate-300 mt-0.5 flex-shrink-0" />}
            <div>
              <div className="text-[13px] text-slate-800 leading-tight">{s.label}</div>
              <div className="text-[11px] text-slate-400">{s.hint}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="px-3 pb-3 flex gap-2">
        <button onClick={onOpenHelp} className="flex-1 py-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 rounded-md hover:bg-indigo-100">
          Open help
        </button>
        <button onClick={dismiss} className="flex-1 py-1.5 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800">
          Got it
        </button>
      </div>
    </div>
  );
}
