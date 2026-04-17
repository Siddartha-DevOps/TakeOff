import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { DEMO_STEPS } from '../mock/mockData';
import { Upload, Sparkles, Eye, FileDown, ArrowRight, Play, Calendar, Clock, User } from 'lucide-react';
import FloorPlanCanvas from '../components/FloorPlanCanvas';
import CtaBand from '../components/sections/CtaBand';

const STEP_ICONS = [Upload, Sparkles, Eye, FileDown];

export default function Demo() {
  const [activeStep, setActiveStep] = useState(0);
  const [form, setForm] = useState({ name: '', email: '', company: '', teamSize: '2-10' });
  const [submitted, setSubmitted] = useState(false);

  return (
    <>
      <section className="relative overflow-hidden gradient-soft-bg py-20">
        <div className="absolute inset-0 grid-pattern opacity-50 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]" />
        <div className="relative max-w-5xl mx-auto px-6 lg:px-8 text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm">
            <Play className="w-3 h-3 text-indigo-500" fill="currentColor" /> Product tour
          </div>
          <h1 className="mt-6 text-5xl md:text-6xl font-semibold tracking-tight text-slate-900 text-balance">
            See TakeOff <span className="gradient-text">work end-to-end.</span>
          </h1>
          <p className="mt-5 text-lg text-slate-600 max-w-2xl mx-auto">
            30 minutes with a preconstruction expert. No slides, just your plans. Or browse the interactive walkthrough below.
          </p>
        </div>
      </section>

      {/* Interactive walkthrough */}
      <section className="max-w-7xl mx-auto px-6 lg:px-8 py-20">
        <div className="grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-8">
          {/* Steps */}
          <div className="space-y-3">
            {DEMO_STEPS.map((s, i) => {
              const Icon = STEP_ICONS[i];
              const active = activeStep === i;
              return (
                <button key={s.step} onClick={() => setActiveStep(i)} className={`w-full text-left p-5 rounded-xl border transition-all ${active ? 'bg-white border-slate-300 shadow-lg shadow-slate-900/5' : 'bg-white/60 border-slate-200 hover:border-slate-300'}`}>
                  <div className="flex items-start gap-3">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${active ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className={`mono text-[11px] font-semibold ${active ? 'text-indigo-600' : 'text-slate-400'}`}>STEP {s.step}</span>
                      </div>
                      <h3 className="mt-1 text-[15px] font-semibold text-slate-900">{s.title}</h3>
                      <p className="mt-1 text-sm text-slate-600 leading-relaxed">{s.desc}</p>
                    </div>
                  </div>
                </button>
              );
            })}
            <Link to="/app" className="flex items-center justify-center gap-2 w-full py-3 rounded-xl bg-slate-900 text-white text-sm font-medium hover:bg-slate-800">
              Try it live <ArrowRight className="w-4 h-4" />
            </Link>
          </div>

          {/* Visual */}
          <div className="relative rounded-2xl bg-white border border-slate-200 shadow-2xl shadow-slate-900/10 overflow-hidden min-h-[500px]">
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-200 bg-slate-50/80">
              <div className="flex gap-1.5"><span className="w-3 h-3 rounded-full bg-rose-400" /><span className="w-3 h-3 rounded-full bg-amber-400" /><span className="w-3 h-3 rounded-full bg-emerald-400" /></div>
              <div className="ml-4 text-xs text-slate-500 mono">Step {activeStep + 1} of 4 — {DEMO_STEPS[activeStep].title}</div>
            </div>
            <div className="p-2 h-[500px]">
              <DemoStageView step={activeStep} />
            </div>
          </div>
        </div>
      </section>

      {/* Book a demo form */}
      <section className="max-w-6xl mx-auto px-6 lg:px-8 pb-24">
        <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-8 md:p-12 grid grid-cols-1 md:grid-cols-2 gap-10">
          <div>
            <h2 className="text-3xl md:text-4xl font-semibold tracking-tight text-slate-900">Rather talk to a human?</h2>
            <p className="mt-3 text-slate-600">Book a 30-minute personalized demo. Bring your actual plans — we’ll run them live.</p>
            <ul className="mt-6 space-y-3 text-sm text-slate-700">
              <li className="flex items-start gap-2"><Clock className="w-4 h-4 text-indigo-600 mt-0.5" /> 30 minutes, no slides</li>
              <li className="flex items-start gap-2"><User className="w-4 h-4 text-indigo-600 mt-0.5" /> 1:1 with a former estimator</li>
              <li className="flex items-start gap-2"><Calendar className="w-4 h-4 text-indigo-600 mt-0.5" /> Usually available within 24 hours</li>
            </ul>
          </div>
          {submitted ? (
            <div className="rounded-2xl bg-white border border-slate-200 p-8 text-center flex flex-col items-center justify-center">
              <div className="w-14 h-14 rounded-full bg-emerald-50 flex items-center justify-center">
                <Sparkles className="w-6 h-6 text-emerald-600" />
              </div>
              <h3 className="mt-4 text-xl font-semibold text-slate-900">You're booked in.</h3>
              <p className="mt-2 text-sm text-slate-600">We'll reach out to {form.email} within 24 hours with a calendar invite.</p>
            </div>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); setSubmitted(true); }} className="rounded-2xl bg-white border border-slate-200 p-7 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <Input placeholder="Full name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                <Input placeholder="Work email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              </div>
              <Input placeholder="Company" value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} />
              <label className="block">
                <span className="text-xs font-medium text-slate-700">Team size</span>
                <select value={form.teamSize} onChange={(e) => setForm({ ...form, teamSize: e.target.value })} className="mt-1.5 w-full px-3 py-2.5 text-sm rounded-lg border border-slate-300 bg-white focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none">
                  <option>Just me</option><option>2-10</option><option>11-50</option><option>50+</option>
                </select>
              </label>
              <button type="submit" className="w-full py-2.5 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 flex items-center justify-center gap-2">
                Book my demo <ArrowRight className="w-3.5 h-3.5" />
              </button>
            </form>
          )}
        </div>
      </section>

      <CtaBand />
    </>
  );
}

function Input(props) {
  return (
    <label className="block">
      <input {...props} className="w-full px-3 py-2.5 text-sm rounded-lg border border-slate-300 bg-white focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none" />
    </label>
  );
}

function DemoStageView({ step }) {
  if (step === 0) return <UploadStage />;
  if (step === 1) return <AnalyzeStage />;
  if (step === 2) return <CanvasStage />;
  return <ExportStage />;
}

function UploadStage() {
  return (
    <div className="h-full rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 flex flex-col items-center justify-center text-center px-8">
      <div className="w-16 h-16 rounded-2xl bg-white border border-slate-200 flex items-center justify-center shadow-sm">
        <Upload className="w-7 h-7 text-indigo-500" />
      </div>
      <h3 className="mt-5 text-lg font-semibold text-slate-900">Drop your plans here</h3>
      <p className="mt-2 text-sm text-slate-600 max-w-xs">PDF, TIFF, PNG or JPG. Up to 500 MB. Even hand-drawn.</p>
      <div className="mt-6 flex flex-wrap gap-2 justify-center">
        {['sample.pdf', 'waterford-L12.pdf', 'hand-sketch.jpg'].map((n) => (
          <span key={n} className="px-3 py-1.5 rounded-full bg-white border border-slate-200 text-xs text-slate-700 mono">{n}</span>
        ))}
      </div>
      <button className="mt-6 px-5 py-2 rounded-lg bg-slate-900 text-white text-sm font-medium">Browse files</button>
    </div>
  );
}

function AnalyzeStage() {
  const stages = [
    { msg: 'Parsing drawing geometry', pct: 20, done: true },
    { msg: 'Detecting auto-scale reference', pct: 35, done: true },
    { msg: 'Running room segmentation (AI)', pct: 60, done: true },
    { msg: 'Classifying doors, windows & fixtures', pct: 82, done: false },
    { msg: 'Computing quantities per trade', pct: 95, done: false },
  ];
  return (
    <div className="h-full grid grid-cols-[1fr_280px] gap-3">
      <div className="rounded-xl bg-slate-50 border border-slate-200 overflow-hidden">
        <FloorPlanCanvas />
      </div>
      <div className="rounded-xl bg-white border border-slate-200 p-5 flex flex-col">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-indigo-500 animate-pulse" />
          <span className="text-xs font-semibold text-slate-900">AI pipeline</span>
        </div>
        <div className="mt-5 space-y-3 flex-1">
          {stages.map((s, i) => (
            <div key={i}>
              <div className="flex items-center justify-between text-xs">
                <span className={`${s.done ? 'text-slate-900' : 'text-slate-500'}`}>{s.msg}</span>
                <span className="mono text-slate-500">{s.pct}%</span>
              </div>
              <div className="mt-1.5 h-1 bg-slate-100 rounded-full overflow-hidden">
                <div className={`h-full rounded-full ${s.done ? 'bg-emerald-500' : 'bg-gradient-to-r from-indigo-500 to-violet-500 animate-pulse'}`} style={{ width: `${s.pct}%` }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function CanvasStage() {
  return (
    <div className="h-full rounded-xl bg-slate-50 border border-slate-200 overflow-hidden relative">
      <FloorPlanCanvas />
      <div className="absolute top-3 left-3 px-2.5 py-1.5 rounded-md bg-white border border-slate-200 text-[11px] font-medium shadow-sm">
        9 rooms · 14 doors · 18 windows
      </div>
      <div className="absolute bottom-3 right-3 flex gap-1.5">
        {[['Rooms', '#818cf8'], ['Doors', '#06b6d4'], ['Windows', '#fbbf24']].map(([n, c]) => (
          <div key={n} className="px-2.5 py-1.5 rounded-md bg-white border border-slate-200 text-[11px] font-medium flex items-center gap-1.5 shadow-sm">
            <span className="w-2 h-2 rounded-sm" style={{ background: c }} /> {n}
          </div>
        ))}
      </div>
    </div>
  );
}

function ExportStage() {
  return (
    <div className="h-full rounded-xl bg-white border border-slate-200 p-4 overflow-auto">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">Quantities — Waterford Tower L12</h3>
          <p className="text-xs text-slate-500">14 line items · ready for export</p>
        </div>
        <button className="px-3 py-1.5 rounded-md bg-slate-900 text-white text-xs font-medium flex items-center gap-1.5"><FileDown className="w-3.5 h-3.5" /> Export .xlsx</button>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wider text-slate-500 border-b border-slate-200">
            <th className="py-2 font-semibold">Trade</th><th className="py-2 font-semibold">Item</th><th className="py-2 text-right font-semibold">Qty</th><th className="py-2 text-right font-semibold">Unit</th>
          </tr>
        </thead>
        <tbody className="text-slate-800">
          {[['Drywall', 'Interior partition LF', '312', 'lf'], ['Drywall', 'Gypsum surface', '2,180', 'sf'], ['Painting', 'Wall paint area', '2,140', 'sf'], ['Flooring', 'Carpet — bedrooms', '800', 'sf'], ['Flooring', 'Tile — wet areas', '210', 'sf'], ['Doors', 'Interior 3\'-0"', '12', 'ea'], ['Windows', 'Double-hung', '14', 'ea'], ['Electrical', 'Duplex outlets', '46', 'ea']].map((r, i) => (
            <tr key={i} className="border-b border-slate-100">
              <td className="py-2.5 text-xs font-medium text-slate-500">{r[0]}</td>
              <td className="py-2.5">{r[1]}</td>
              <td className="py-2.5 text-right mono font-semibold">{r[2]}</td>
              <td className="py-2.5 text-right text-xs text-slate-500">{r[3]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
