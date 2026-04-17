import React from 'react';
import { FEATURES } from '../../mock/mockData';
import { Sparkles, Users, GitCompare, MessageSquare, FileDown, FileType2, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

const ICONS = {
  'ai-detection': Sparkles,
  'realtime': Users,
  'compare': GitCompare,
  'chat': MessageSquare,
  'export': FileDown,
  'any-file': FileType2,
};

const ACCENT_BG = {
  indigo: 'bg-indigo-50 text-indigo-600 ring-indigo-100',
  violet: 'bg-violet-50 text-violet-600 ring-violet-100',
  cyan: 'bg-cyan-50 text-cyan-600 ring-cyan-100',
  emerald: 'bg-emerald-50 text-emerald-600 ring-emerald-100',
  amber: 'bg-amber-50 text-amber-600 ring-amber-100',
  rose: 'bg-rose-50 text-rose-600 ring-rose-100',
};

export default function FeaturesGrid() {
  return (
    <section className="relative py-24 bg-slate-50/60">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="max-w-2xl">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700">
            <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
            The #1 takeoff tool
          </div>
          <h2 className="mt-4 text-4xl md:text-5xl font-semibold tracking-tight text-slate-900 text-balance">
            Built by estimators. For estimators.
          </h2>
          <p className="mt-4 text-lg text-slate-600 leading-relaxed">
            Complete more bids in less time with fewer clicks. Every feature you need, nothing you don't.
          </p>
        </div>

        <div className="mt-14 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f) => {
            const Icon = ICONS[f.id] || Sparkles;
            return (
              <div key={f.id} className="group relative rounded-2xl bg-white border border-slate-200 p-7 hover:border-slate-300 hover:shadow-lg hover:shadow-slate-900/5 hover:-translate-y-0.5">
                <div className={`w-11 h-11 rounded-xl flex items-center justify-center ring-8 ${ACCENT_BG[f.accent]}`}>
                  <Icon className="w-5 h-5" strokeWidth={2} />
                </div>
                <div className="mt-5 text-[11px] uppercase tracking-wider text-slate-500 font-semibold">{f.kicker}</div>
                <h3 className="mt-1 text-lg font-semibold text-slate-900 tracking-tight">{f.title}</h3>
                <p className="mt-2 text-sm text-slate-600 leading-relaxed">{f.desc}</p>
                <Link to="/features" className="mt-5 inline-flex items-center gap-1 text-xs font-medium text-slate-900 opacity-0 group-hover:opacity-100">
                  Learn more <ArrowRight className="w-3 h-3" />
                </Link>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
