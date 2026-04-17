import React from 'react';
import { TESTIMONIALS } from '../../mock/mockData';
import { Quote } from 'lucide-react';

const ACCENT = {
  indigo: 'from-indigo-500 to-violet-500',
  violet: 'from-violet-500 to-fuchsia-500',
  cyan: 'from-cyan-500 to-blue-500',
  emerald: 'from-emerald-500 to-teal-500',
  amber: 'from-amber-500 to-orange-500',
  rose: 'from-rose-500 to-pink-500',
};

export default function Testimonials() {
  return (
    <section className="py-24 bg-white">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="flex flex-col md:flex-row items-start md:items-end justify-between gap-6 mb-12">
          <div className="max-w-xl">
            <h2 className="text-4xl md:text-5xl font-semibold tracking-tight text-slate-900">
              See what our customers say.
            </h2>
            <p className="mt-4 text-lg text-slate-600">Real estimators, real results. No paid actors.</p>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <div className="flex items-center gap-1">{'★★★★★'.split('').map((s, i) => <span key={i} className="text-amber-400">{s}</span>)}</div>
            <span className="font-semibold text-slate-700">4.9 / 5</span>
            <span>· 2,400+ reviews</span>
          </div>
        </div>

        <div className="columns-1 md:columns-2 lg:columns-3 gap-5 space-y-5">
          {TESTIMONIALS.map((t, i) => (
            <figure key={i} className="break-inside-avoid rounded-2xl bg-white border border-slate-200 p-7 hover:shadow-lg hover:shadow-slate-900/5 hover:-translate-y-0.5">
              <Quote className="w-6 h-6 text-slate-300" strokeWidth={1.5} />
              <blockquote className="mt-4 text-[15px] text-slate-800 leading-relaxed">“{t.quote}”</blockquote>
              <figcaption className="mt-6 flex items-center gap-3">
                <div className={`w-10 h-10 rounded-full bg-gradient-to-br ${ACCENT[t.accent]} flex items-center justify-center text-white font-semibold text-sm`}>
                  {t.name.split(' ').map((x) => x[0]).slice(0, 2).join('')}
                </div>
                <div>
                  <div className="text-sm font-semibold text-slate-900">{t.name}</div>
                  <div className="text-xs text-slate-500">{t.role}, {t.company}</div>
                </div>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
    </section>
  );
}
