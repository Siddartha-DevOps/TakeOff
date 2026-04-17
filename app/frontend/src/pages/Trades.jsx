import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { TRADES } from '../mock/mockData';
import * as Icons from 'lucide-react';
import { ArrowRight } from 'lucide-react';
import CtaBand from '../components/sections/CtaBand';

const TRADE_ACCENTS = ['indigo', 'violet', 'cyan', 'emerald', 'amber', 'rose', 'blue', 'fuchsia', 'teal', 'slate'];

export default function Trades() {
  const [params] = useSearchParams();
  const active = params.get('t');
  return (
    <>
      <section className="relative overflow-hidden gradient-soft-bg py-24">
        <div className="absolute inset-0 grid-pattern opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]" />
        <div className="relative max-w-4xl mx-auto px-6 lg:px-8 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm">
            Trades
          </div>
          <h1 className="mt-6 text-5xl md:text-6xl font-semibold tracking-tight text-slate-900 text-balance">
            Built for every <span className="gradient-text">trade.</span>
          </h1>
          <p className="mt-5 text-lg text-slate-600 max-w-2xl mx-auto">
            Pre-loaded libraries, measurement patterns and export groupings tailored to your discipline.
          </p>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-6 lg:px-8 pb-24">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {TRADES.map((t, i) => {
            const Icon = Icons[t.icon] || Icons.Hammer;
            const accent = TRADE_ACCENTS[i % TRADE_ACCENTS.length];
            const isActive = active === t.slug;
            return (
              <div key={t.slug} className={`group relative rounded-2xl bg-white border p-7 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-slate-900/5 ${isActive ? 'border-indigo-400 ring-2 ring-indigo-100' : 'border-slate-200 hover:border-slate-300'}`}>
                <div className={`w-11 h-11 rounded-xl bg-${accent}-50 text-${accent}-600 ring-8 ring-${accent}-100 flex items-center justify-center`}>
                  <Icon className="w-5 h-5" strokeWidth={2} />
                </div>
                <h3 className="mt-5 text-lg font-semibold tracking-tight text-slate-900">{t.name}</h3>
                <p className="mt-2 text-sm text-slate-600 leading-relaxed">{t.desc}</p>
                <Link to="/demo" className="mt-5 inline-flex items-center gap-1 text-xs font-medium text-slate-900 group-hover:text-indigo-600">
                  Explore workflow <ArrowRight className="w-3 h-3" />
                </Link>
              </div>
            );
          })}
        </div>
      </section>

      <CtaBand />
    </>
  );
}
