import React from 'react';
import { useParams, Link, NavLink } from 'react-router-dom';
import { COMPARISON_FEATURES, COMPETITORS } from '../mock/mockData';
import { Check, X, ArrowRight, Sparkles } from 'lucide-react';
import LogoCloud from '../components/sections/LogoCloud';
import CtaBand from '../components/sections/CtaBand';

const KEY_MAP = { bluebeam: 'blueBeam', ost: 'ost', planswift: 'planSwift' };

export default function Comparison() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <h1 className="text-2xl font-bold">Comparison Coming Soon</h1>
    </div>
  );
}

  const { competitor = 'bluebeam' } = useParams();
  const key = KEY_MAP[competitor] || 'blueBeam';
  const comp = COMPETITORS[competitor] || COMPETITORS.bluebeam;

  return (
    <>
      <section className="relative overflow-hidden gradient-soft-bg pt-24 pb-12">
        <div className="absolute inset-0 grid-pattern opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]" />
        <div className="relative max-w-5xl mx-auto px-6 lg:px-8 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm">
            Compare takeoff software
          </div>
          <h1 className="mt-6 text-5xl md:text-6xl font-semibold tracking-tight text-slate-900 text-balance">
            TakeOff.ai <span className="gradient-text">vs {comp.name}</span>
          </h1>
          <p className="mt-5 text-lg text-slate-600 max-w-2xl mx-auto">
            An honest, feature-by-feature breakdown. {comp.tagline}.
          </p>
          <div className="mt-8 flex justify-center">
            <div className="inline-flex p-1 rounded-lg bg-white border border-slate-200">
              {Object.keys(COMPETITORS).map((slug) => (
                <NavLink
                  key={slug}
                  to={`/compare/${slug}`}
                  className={({ isActive }) => `px-4 py-1.5 text-sm font-medium rounded-md capitalize ${isActive || slug === competitor ? 'bg-slate-900 text-white' : 'text-slate-600 hover:text-slate-900'}`}
                >
                  vs {COMPETITORS[slug].name.replace('Onscreen Takeoff (OST)', 'OST')}
                </NavLink>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Header table */}
      <section className="max-w-6xl mx-auto px-6 lg:px-8 py-16">
        <div className="rounded-2xl border border-slate-200 overflow-hidden bg-white">
          <div className="grid grid-cols-3 border-b border-slate-200 bg-slate-50">
            <div className="p-5 text-xs font-semibold uppercase tracking-wider text-slate-500">Feature</div>
            <div className="p-5 border-l border-slate-200 bg-gradient-to-b from-indigo-50/80 to-transparent">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-md bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center">
                  <Sparkles className="w-3.5 h-3.5 text-white" />
                </div>
                <span className="text-sm font-semibold text-slate-900">TakeOff.ai</span>
              </div>
            </div>
            <div className="p-5 border-l border-slate-200">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-md bg-slate-200 flex items-center justify-center text-[10px] font-bold text-slate-600">
                  {comp.name.split(' ').map((w) => w[0]).slice(0, 2).join('')}
                </div>
                <span className="text-sm font-semibold text-slate-900">{comp.name}</span>
              </div>
            </div>
          </div>
          {COMPARISON_FEATURES.map((group) => (
            <React.Fragment key={group.group}>
              <div className="px-5 py-3 bg-slate-50 border-b border-slate-200 text-xs font-semibold uppercase tracking-wider text-slate-500">{group.group}</div>
              {group.items.map((item, idx) => (
                <div key={item.name} className={`grid grid-cols-3 ${idx !== group.items.length - 1 ? 'border-b border-slate-100' : 'border-b border-slate-200'}`}>
                  <div className="p-5 text-sm text-slate-800">{item.name}</div>
                  <div className="p-5 border-l border-slate-200 flex items-center">
                    {item.us ? <Check className="w-5 h-5 text-emerald-600" strokeWidth={2.5} /> : <X className="w-5 h-5 text-slate-300" />}
                  </div>
                  <div className="p-5 border-l border-slate-200 flex items-center">
                    {item[key] ? <Check className="w-5 h-5 text-slate-500" strokeWidth={2.5} /> : <X className="w-5 h-5 text-slate-300" />}
                  </div>
                </div>
              ))}
            </React.Fragment>
          ))}
        </div>
      </section>

      {/* Pros / Cons */}
      <section className="max-w-6xl mx-auto px-6 lg:px-8 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div className="rounded-2xl border border-slate-200 bg-white p-7">
            <h3 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-indigo-600" /> TakeOff.ai
            </h3>
            <div className="mt-5">
              <div className="text-xs font-semibold uppercase tracking-wider text-emerald-700">Top pros</div>
              <ul className="mt-3 space-y-2 text-sm text-slate-700">
                {['Complete AI takeoff + manual tool suite', 'Every file type accepted — even hand-drawn', 'Real-time internal + external collaboration', '20-minute customer support SLA', 'Cloud-native, zero install'].map((p) => (
                  <li key={p} className="flex items-start gap-2"><Check className="w-4 h-4 text-emerald-600 mt-0.5" /> {p}</li>
                ))}
              </ul>
              <div className="mt-6 text-xs font-semibold uppercase tracking-wider text-rose-700">Top cons</div>
              <ul className="mt-3 space-y-2 text-sm text-slate-700">
                {['Newer software — ongoing rapid iteration', 'Small learning curve for AI prompts'].map((p) => (
                  <li key={p} className="flex items-start gap-2"><X className="w-4 h-4 text-rose-500 mt-0.5" /> {p}</li>
                ))}
              </ul>
              <Link to="/demo" className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-white bg-slate-900 px-4 py-2 rounded-lg hover:bg-slate-800">
                Talk to sales <ArrowRight className="w-3.5 h-3.5" />
              </Link>
            </div>
          </div>
          <div className="rounded-2xl border border-slate-200 bg-slate-50/60 p-7">
            <h3 className="text-lg font-semibold text-slate-900">{comp.name}</h3>
            <div className="mt-5">
              <div className="text-xs font-semibold uppercase tracking-wider text-slate-600">Top pros</div>
              <ul className="mt-3 space-y-2 text-sm text-slate-700">
                {comp.pros.map((p) => (<li key={p} className="flex items-start gap-2"><Check className="w-4 h-4 text-slate-500 mt-0.5" /> {p}</li>))}
              </ul>
              <div className="mt-6 text-xs font-semibold uppercase tracking-wider text-slate-600">Top cons</div>
              <ul className="mt-3 space-y-2 text-sm text-slate-700">
                {comp.cons.map((p) => (<li key={p} className="flex items-start gap-2"><X className="w-4 h-4 text-rose-500 mt-0.5" /> {p}</li>))}
              </ul>
            </div>
          </div>
        </div>
      </section>

      <LogoCloud />
      <CtaBand />
    </>
  );
}
