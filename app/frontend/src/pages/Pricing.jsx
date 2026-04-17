import React, { useState } from 'react';
import { PRICING_PLANS, PRICING_FAQ, TESTIMONIALS } from '../mock/mockData';
import { Check, Sparkles, ChevronDown, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import LogoCloud from '../components/sections/LogoCloud';
import CtaBand from '../components/sections/CtaBand';

export default function Pricing() {
  const [billing, setBilling] = useState('yearly');
  return (
    <>
      <section className="relative overflow-hidden gradient-soft-bg pt-24 pb-16">
        <div className="absolute inset-0 grid-pattern opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]" />
        <div className="relative max-w-4xl mx-auto px-6 lg:px-8 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm">
            Pricing
          </div>
          <h1 className="mt-6 text-5xl md:text-6xl font-semibold tracking-tight text-slate-900">
            Simple, <span className="gradient-text">transparent</span> pricing.
          </h1>
          <p className="mt-5 text-lg text-slate-600">Try the most innovative takeoff tool on the market. Cancel anytime.</p>
          <div className="mt-8 inline-flex p-1 rounded-lg bg-white border border-slate-200">
            {['monthly', 'yearly'].map((b) => (
              <button key={b} onClick={() => setBilling(b)} className={`px-4 py-1.5 text-sm font-medium rounded-md capitalize ${billing === b ? 'bg-slate-900 text-white' : 'text-slate-600 hover:text-slate-900'}`}>
                {b} {b === 'yearly' && <span className={`ml-1 text-[10px] ${billing === 'yearly' ? 'text-emerald-300' : 'text-emerald-600'}`}>−20%</span>}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="max-w-7xl mx-auto px-6 lg:px-8 pb-24">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          {PRICING_PLANS.map((p) => (
            <div key={p.name} className={`relative rounded-2xl p-8 ${p.highlight ? 'bg-slate-900 text-white shadow-2xl shadow-slate-900/30 ring-1 ring-slate-900' : 'bg-white border border-slate-200'}`}>
              {p.highlight && (
                <div className="absolute -top-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 text-white text-[10px] font-semibold uppercase tracking-wider">
                  <Sparkles className="w-3 h-3" /> Most popular
                </div>
              )}
              <h3 className={`text-lg font-semibold ${p.highlight ? 'text-white' : 'text-slate-900'}`}>{p.name}</h3>
              <p className={`mt-1 text-sm ${p.highlight ? 'text-slate-300' : 'text-slate-600'}`}>{p.tagline}</p>
              <div className="mt-6 flex items-baseline gap-1">
                <span className={`text-5xl font-semibold tracking-tight ${p.highlight ? 'text-white' : 'text-slate-900'}`}>{p.price}</span>
                {p.period && <span className={`text-sm ${p.highlight ? 'text-slate-400' : 'text-slate-500'}`}>{p.period}</span>}
              </div>
              <div className={`text-xs ${p.highlight ? 'text-slate-400' : 'text-slate-500'}`}>{p.billing}</div>
              <Link to="/signup" className={`mt-6 block text-center py-2.5 rounded-lg text-sm font-medium ${p.highlight ? 'bg-white text-slate-900 hover:bg-slate-100' : 'bg-slate-900 text-white hover:bg-slate-800'}`}>
                {p.cta}
              </Link>
              <div className={`mt-7 pt-6 border-t ${p.highlight ? 'border-slate-800' : 'border-slate-200'}`}>
                <ul className="space-y-3">
                  {p.features.map((f) => (
                    <li key={f} className={`flex items-start gap-2.5 text-sm ${p.highlight ? 'text-slate-200' : 'text-slate-700'}`}>
                      <Check className={`w-4 h-4 mt-0.5 flex-shrink-0 ${p.highlight ? 'text-indigo-300' : 'text-emerald-600'}`} />
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </section>

      <LogoCloud title="Trusted every day by thousands of professional builders." />

      {/* FAQ */}
      <section className="max-w-3xl mx-auto px-6 lg:px-8 py-24">
        <h2 className="text-3xl md:text-4xl font-semibold tracking-tight text-slate-900 text-center">Questions & answers.</h2>
        <div className="mt-10 rounded-2xl border border-slate-200 bg-white divide-y divide-slate-200">
          {PRICING_FAQ.map((item, i) => (
            <FAQItem key={i} q={item.q} a={item.a} />
          ))}
        </div>
      </section>

      {/* Testimonial strip */}
      <section className="max-w-7xl mx-auto px-6 lg:px-8 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
          {TESTIMONIALS.slice(0, 3).map((t, i) => (
            <div key={i} className="rounded-2xl bg-slate-50 p-7">
              <p className="text-[15px] text-slate-800 leading-relaxed">“{t.quote}”</p>
              <div className="mt-5 text-sm font-semibold text-slate-900">{t.name}</div>
              <div className="text-xs text-slate-500">{t.role}, {t.company}</div>
            </div>
          ))}
        </div>
      </section>

      <CtaBand />
    </>
  );
}

function FAQItem({ q, a }) {
  const [open, setOpen] = useState(false);
  return (
    <button onClick={() => setOpen(!open)} className="w-full text-left px-6 py-5 hover:bg-slate-50">
      <div className="flex items-center justify-between gap-4">
        <span className="text-[15px] font-medium text-slate-900">{q}</span>
        <ChevronDown className={`w-5 h-5 text-slate-500 flex-shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </div>
      {open && <p className="mt-3 text-sm text-slate-600 leading-relaxed">{a}</p>}
    </button>
  );
}
