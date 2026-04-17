import React from 'react';
import { Link } from 'react-router-dom';
import { FEATURES } from '../mock/mockData';
import { Sparkles, Users, GitCompare, MessageSquare, FileDown, FileType2, ArrowRight, Check } from 'lucide-react';
import FloorPlanCanvas from '../components/FloorPlanCanvas';
import LogoCloud from '../components/sections/LogoCloud';
import CtaBand from '../components/sections/CtaBand';

const ICONS = { 'ai-detection': Sparkles, realtime: Users, compare: GitCompare, chat: MessageSquare, export: FileDown, 'any-file': FileType2 };
const ACCENTS = {
  indigo: { bg: 'bg-indigo-50', ring: 'ring-indigo-100', text: 'text-indigo-600' },
  violet: { bg: 'bg-violet-50', ring: 'ring-violet-100', text: 'text-violet-600' },
  cyan: { bg: 'bg-cyan-50', ring: 'ring-cyan-100', text: 'text-cyan-600' },
  emerald: { bg: 'bg-emerald-50', ring: 'ring-emerald-100', text: 'text-emerald-600' },
  amber: { bg: 'bg-amber-50', ring: 'ring-amber-100', text: 'text-amber-600' },
  rose: { bg: 'bg-rose-50', ring: 'ring-rose-100', text: 'text-rose-600' },
};

export default function Features() {
  return (
    <>
      <section className="relative overflow-hidden gradient-soft-bg py-24">
        <div className="absolute inset-0 grid-pattern opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]" />
        <div className="relative max-w-4xl mx-auto px-6 lg:px-8 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm">
            <Sparkles className="w-3 h-3 text-indigo-500" /> Features
          </div>
          <h1 className="mt-6 text-5xl md:text-6xl font-semibold tracking-tight text-slate-900 text-balance">
            Every tool an estimator <span className="gradient-text">actually</span> needs.
          </h1>
          <p className="mt-5 text-lg text-slate-600 max-w-2xl mx-auto text-balance">
            From automated takeoffs to real-time collaboration and semantic plan search, TakeOff replaces half a dozen tools with one.
          </p>
        </div>
      </section>

      {/* Feature spotlight sections */}
      <section className="max-w-7xl mx-auto px-6 lg:px-8 py-24 space-y-32">
        {FEATURES.map((f, idx) => {
          const Icon = ICONS[f.id] || Sparkles;
          const a = ACCENTS[f.accent];
          const reverse = idx % 2 === 1;
          return (
            <div key={f.id} className={`grid grid-cols-1 lg:grid-cols-2 gap-16 items-center ${reverse ? 'lg:[&>div:first-child]:order-2' : ''}`}>
              <div>
                <div className={`w-11 h-11 rounded-xl flex items-center justify-center ring-8 ${a.bg} ${a.text} ${a.ring}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <div className="mt-5 text-[11px] uppercase tracking-wider text-slate-500 font-semibold">{f.kicker}</div>
                <h2 className="mt-2 text-3xl md:text-4xl font-semibold tracking-tight text-slate-900">{f.title}</h2>
                <p className="mt-4 text-lg text-slate-600 leading-relaxed">{f.desc}</p>
                <ul className="mt-6 space-y-2">
                  {['Auto-scale detection on every drawing', 'Works with PDF, TIFF, PNG, JPG', 'Confidence scores on every detection', 'One-click export to Excel & CSV'].map((b) => (
                    <li key={b} className="flex items-start gap-2 text-sm text-slate-700"><Check className="w-4 h-4 text-emerald-600 mt-0.5" /> {b}</li>
                  ))}
                </ul>
                <Link to="/demo" className="mt-7 inline-flex items-center gap-1.5 text-sm font-medium text-slate-900 hover:text-indigo-600">
                  See it in action <ArrowRight className="w-3.5 h-3.5" />
                </Link>
              </div>
              <div className="relative rounded-2xl bg-white border border-slate-200 shadow-xl shadow-slate-900/5 overflow-hidden aspect-[4/3]">
                <FloorPlanCanvas autoplay={idx === 0} />
                <div className={`absolute top-3 left-3 px-2.5 py-1 rounded-md text-[11px] font-medium ${a.bg} ${a.text} border border-current/10`}>
                  {f.kicker}
                </div>
              </div>
            </div>
          );
        })}
      </section>

      <LogoCloud title="Loved by the best estimating teams in the industry" />
      <CtaBand />
    </>
  );
}
