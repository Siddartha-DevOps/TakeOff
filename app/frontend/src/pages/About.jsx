import React from 'react';
import { ArrowRight, Building2, Users, Sparkles, TrendingUp, Lightbulb, Heart } from 'lucide-react';
import { Link } from 'react-router-dom';
import CtaBand from '../components/sections/CtaBand';

const VALUES = [
  { icon: Heart, title: 'Built by builders', desc: 'Our team has spent decades in construction offices, on job sites and with scale rulers. We build what we wish we had.' },
  { icon: Sparkles, title: 'AI that ships', desc: 'Not a demo, not a prototype. Our models run on real plans, in real projects, every single day.' },
  { icon: Users, title: 'Customer-obsessed', desc: '20-minute response SLA during business hours. We answer every ticket and every call personally.' },
  { icon: Lightbulb, title: 'Bi-weekly updates', desc: 'New features every two weeks. Your feedback directly steers the roadmap.' },
];

const TIMELINE = [
  { year: '2021', title: 'Founded in Miami', desc: 'Born from a multi-generational family construction business that couldn’t find a tool that actually worked.' },
  { year: '2022', title: 'First 100 customers', desc: 'Painting and drywall contractors adopt TakeOff. Early signals: 5× faster than existing tools.' },
  { year: '2023', title: 'AI segmentation launches', desc: 'Room detection hits 97% accuracy. TakeOff Chat ships. Seed round closes.' },
  { year: '2024', title: 'Series A & enterprise', desc: 'Clark, DPR and Coastal adopt TakeOff. Revision compare and SSO launched.' },
  { year: '2026', title: 'The new standard', desc: 'Thousands of estimators across every trade rely on TakeOff every day. Just getting started.' },
];

export default function About() {
  return (
    <>
      <section className="relative overflow-hidden gradient-soft-bg py-24">
        <div className="absolute inset-0 grid-pattern opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]" />
        <div className="relative max-w-4xl mx-auto px-6 lg:px-8 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm">
            Company
          </div>
          <h1 className="mt-6 text-5xl md:text-7xl font-semibold tracking-tight text-slate-900 text-balance">
            Built by builders,<br /><span className="gradient-text">for builders.</span>
          </h1>
          <p className="mt-6 text-lg text-slate-600 max-w-2xl mx-auto text-balance">
            TakeOff was born from a family construction business that had been doing takeoffs with printed plans and a scale ruler for three generations. We built the tool we always wished existed — now thousands of estimators use it every day.
          </p>
        </div>
      </section>

      {/* Story */}
      <section className="max-w-5xl mx-auto px-6 lg:px-8 py-24">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-10 items-start">
          <div className="md:col-span-1">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Our story</div>
            <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-900">From a scale ruler to AI.</h2>
          </div>
          <div className="md:col-span-2 text-slate-600 leading-relaxed space-y-4 text-[15px]">
            <p>Our founder grew up watching his grandfather do estimates with printed plans and a scale ruler. A couple decades later, after time running the family construction business, he asked a simple question: why does preconstruction still feel like 1985?</p>
            <p>He assembled a team of computer vision researchers, former estimators and senior engineers from some of the world’s best-known software companies. Their goal: build what construction actually needs — not another markup tool dressed as AI.</p>
            <p>Three years later, TakeOff is used by thousands of professional builders every day, from two-person painting shops to top-10 general contractors. We’re just getting started.</p>
          </div>
        </div>
      </section>

      {/* Values */}
      <section className="bg-slate-50/60 py-24">
        <div className="max-w-7xl mx-auto px-6 lg:px-8">
          <div className="max-w-2xl">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Our values</div>
            <h2 className="mt-2 text-4xl font-semibold tracking-tight text-slate-900">What we care about.</h2>
          </div>
          <div className="mt-12 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
            {VALUES.map((v) => {
              const Icon = v.icon;
              return (
                <div key={v.title} className="rounded-2xl bg-white border border-slate-200 p-7 hover:shadow-lg hover:shadow-slate-900/5">
                  <div className="w-11 h-11 rounded-xl bg-indigo-50 text-indigo-600 ring-8 ring-indigo-100 flex items-center justify-center">
                    <Icon className="w-5 h-5" />
                  </div>
                  <h3 className="mt-5 text-base font-semibold text-slate-900">{v.title}</h3>
                  <p className="mt-2 text-sm text-slate-600 leading-relaxed">{v.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Timeline */}
      <section className="max-w-5xl mx-auto px-6 lg:px-8 py-24">
        <div className="max-w-xl">
          <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Journey</div>
          <h2 className="mt-2 text-4xl font-semibold tracking-tight text-slate-900">A brief timeline.</h2>
        </div>
        <div className="mt-12 space-y-10">
          {TIMELINE.map((t, i) => (
            <div key={t.year} className="grid grid-cols-[80px_1fr] md:grid-cols-[120px_1fr] gap-6 items-start">
              <div className="mono text-sm font-semibold text-indigo-600">{t.year}</div>
              <div className="relative pl-6 pb-10 border-l border-slate-200 last:border-transparent">
                <span className="absolute -left-[5px] top-1 w-2.5 h-2.5 rounded-full bg-white border-2 border-indigo-500" />
                <h3 className="text-lg font-semibold text-slate-900">{t.title}</h3>
                <p className="mt-1 text-sm text-slate-600 leading-relaxed">{t.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Stats */}
      <section className="bg-slate-900 text-white py-20">
        <div className="max-w-7xl mx-auto px-6 lg:px-8 grid grid-cols-2 md:grid-cols-4 gap-8">
          {[['12,000+', 'Estimators'], ['48', 'States covered'], ['$2.4B', 'In bids processed'], ['4.9/5', 'Customer rating']].map(([v, l]) => (
            <div key={l}>
              <div className="text-4xl md:text-5xl font-semibold tracking-tight">{v}</div>
              <div className="mt-1 text-xs uppercase tracking-wider text-slate-400">{l}</div>
            </div>
          ))}
        </div>
      </section>

      <CtaBand />
    </>
  );
}
