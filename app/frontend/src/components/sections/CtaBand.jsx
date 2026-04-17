import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Sparkles } from 'lucide-react';

export default function CtaBand() {
  return (
    <section className="relative py-24 overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950" />
      <div className="absolute inset-0 opacity-40" style={{
        backgroundImage: 'radial-gradient(circle at 20% 20%, rgba(99, 102, 241, 0.3), transparent 40%), radial-gradient(circle at 80% 60%, rgba(139, 92, 246, 0.25), transparent 50%)',
      }} />
      <div className="absolute inset-0" style={{
        backgroundImage: 'linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)',
        backgroundSize: '60px 60px',
      }} />

      <div className="relative max-w-4xl mx-auto px-6 lg:px-8 text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-xs font-medium text-white/80 backdrop-blur">
          <Sparkles className="w-3 h-3" /> Book a personalized demo
        </div>
        <h2 className="mt-6 text-4xl md:text-6xl font-semibold tracking-tight text-white text-balance">
          See how much faster your takeoffs can be.
        </h2>
        <p className="mt-5 text-lg text-white/70 max-w-xl mx-auto">
          30 minutes with a preconstruction expert. No slides, just your plans.
        </p>
        <div className="mt-10 flex flex-col sm:flex-row gap-3 justify-center">
          <Link to="/demo" className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-white text-slate-900 font-medium text-sm hover:bg-slate-100 shadow-lg">
            Book a demo <ArrowRight className="w-4 h-4" />
          </Link>
          <Link to="/app" className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-white/10 border border-white/20 text-white font-medium text-sm hover:bg-white/15 backdrop-blur">
            Open the app
          </Link>
        </div>
      </div>
    </section>
  );
}
