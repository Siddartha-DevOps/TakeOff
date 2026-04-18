import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Sparkles, Play } from 'lucide-react';
import { motion } from 'framer-motion';
import FloorPlanCanvas from '../FloorPlanCanvas';
import { HERO_STATS } from '../../mock/mockData';

export default function Hero() {
  return (
    <section className="relative overflow-hidden gradient-soft-bg">
      <div className="absolute inset-0 grid-pattern opacity-60 [mask-image:radial-gradient(ellipse_at_center,black_40%,transparent_70%)]" />

      <div className="relative max-w-7xl mx-auto px-6 lg:px-8 pt-24 pb-20">
        {/* Eyebrow */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="flex justify-center"
        >
          <Link to="/features" className="inline-flex items-center gap-2 pl-1.5 pr-3.5 py-1.5 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 shadow-sm hover:border-slate-300 transition-colors">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-gradient-to-r from-indigo-500 to-violet-500 text-white text-[10px] font-semibold uppercase tracking-wide">
              <Sparkles className="w-3 h-3" /> New
            </span>
            TakeOff Chat · ask your plans anything
            <ArrowRight className="w-3 h-3 opacity-60" />
          </Link>
        </motion.div>

        {/* Headline */}
        <motion.h1
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mt-8 text-center text-5xl md:text-6xl lg:text-7xl font-semibold tracking-tight text-slate-900 text-balance"
        >
          Takeoff in minutes.<br />
          <span className="gradient-text">Not days.</span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.2 }}
          className="mt-6 max-w-2xl mx-auto text-center text-lg md:text-xl text-slate-600 leading-relaxed text-balance"
        >
          The AI takeoff tool built by estimators. Upload any drawing and TakeOff detects rooms, measures quantities and compares revisions — with 98% accuracy.
        </motion.p>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mt-10 flex flex-col sm:flex-row gap-3 justify-center"
        >
          <Link to="/demo" className="group inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-slate-900 text-white font-medium text-sm shadow-lg shadow-slate-900/20 hover:bg-slate-800">
            Book a demo <ArrowRight className="w-4 h-4 group-hover:translate-x-0.5" />
          </Link>
          <Link to="/app" className="group inline-flex items-center justify-center gap-2 px-6 py-3 rounded-lg bg-white border border-slate-300 text-slate-900 font-medium text-sm hover:border-slate-400 hover:bg-slate-50 transition-colors">
            <Play className="w-3.5 h-3.5" fill="currentColor" /> Take a tour
          </Link>
        </motion.div>

        {/* Product screenshot */}
        <motion.div
          initial={{ opacity: 0, y: 40, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.7, delay: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="relative mt-16"
        >
          <div className="absolute -inset-8 bg-gradient-to-b from-indigo-100/40 via-violet-100/30 to-transparent rounded-[2rem] blur-2xl pointer-events-none" />
          <div className="relative rounded-2xl bg-white border border-slate-200 shadow-2xl shadow-slate-900/10 overflow-hidden">
            {/* Browser chrome */}
            <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-200 bg-slate-50/80">
              <div className="flex gap-1.5"><span className="w-3 h-3 rounded-full bg-rose-400" /><span className="w-3 h-3 rounded-full bg-amber-400" /><span className="w-3 h-3 rounded-full bg-emerald-400" /></div>
              <div className="ml-4 flex-1 text-xs text-slate-500 font-mono">app.takeoff.ai / projects / waterford-tower / level-12</div>
              <div className="flex items-center gap-1 text-[10px] text-emerald-600 font-semibold">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" /> LIVE
              </div>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr_260px]">
              {/* left rail */}
              <div className="hidden lg:block border-r border-slate-200 bg-slate-50/50 p-3 text-xs">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-2 py-1">Sheets</div>
                {['A-001 Cover', 'A-101 Level 12', 'A-102 Level 13', 'A-201 Elevations', 'M-101 HVAC', 'E-101 Power'].map((s, i) => (
                  <div key={s} className={`px-2 py-1.5 rounded mb-0.5 ${i === 1 ? 'bg-indigo-50 text-indigo-900 font-medium' : 'text-slate-600 hover:bg-white'}`}>{s}</div>
                ))}
                <div className="mt-4 text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-2 py-1">Detections</div>
                {[['Rooms', 9, '#a78bfa'], ['Doors', 14, '#10b981'], ['Windows', 18, '#3b82f6'], ['Walls', 42, '#eab308']].map(([n, c, col]) => (
                  <div key={n} className="flex items-center justify-between px-2 py-1.5 text-slate-700">
                    <div className="flex items-center gap-2"><span className="w-2 h-2 rounded-sm" style={{ background: col }} />{n}</div>
                    <span className="mono text-[11px] text-slate-500">{c}</span>
                  </div>
                ))}
              </div>
              {/* canvas */}
              <div className="relative aspect-[4/3] lg:aspect-auto bg-slate-50">
                <FloorPlanCanvas />
                <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-white/90 backdrop-blur border border-slate-200 text-[11px] font-medium text-slate-700 shadow-sm">
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                  AI processing — 98% confidence
                </div>
                <div className="absolute bottom-3 right-3 flex items-center gap-1.5 px-2.5 py-1.5 rounded-md bg-slate-900 text-white text-[11px] font-medium">
                  1/8" = 1'-0"
                </div>
              </div>
              {/* right quantities */}
              <div className="hidden lg:block border-l border-slate-200 p-3">
                <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-1 mb-2">Live Quantities</div>
                {[
                  ['Drywall LF', '312', 'indigo'],
                  ['Paint area', '2,140 sf', 'violet'],
                  ['Flooring', '2,060 sf', 'cyan'],
                  ['Doors', '14 ea', 'emerald'],
                  ['Windows', '18 ea', 'amber'],
                  ['Outlets', '46 ea', 'rose'],
                ].map(([k, v, c]) => (
                  <div key={k} className="flex items-center justify-between px-1 py-2 border-b border-slate-100 last:border-0">
                    <span className="text-xs text-slate-600">{k}</span>
                    <span className="mono text-xs font-semibold text-slate-900">{v}</span>
                  </div>
                ))}
                <button className="mt-3 w-full py-2 text-xs font-medium text-white bg-slate-900 rounded-md hover:bg-slate-800">Export to Excel</button>
              </div>
            </div>
          </div>
        </motion.div>

        {/* Stats */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.6 }}
          className="mt-16 grid grid-cols-2 lg:grid-cols-4 gap-8"
        >
          {HERO_STATS.map((s, i) => (
            <motion.div
              key={s.label}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.7 + i * 0.1 }}
              className="text-center"
            >
              <div className="text-3xl md:text-4xl font-semibold tracking-tight text-slate-900">{s.value}</div>
              <div className="text-xs text-slate-500 uppercase tracking-wider mt-1">{s.label}</div>
            </motion.div>
          ))}
        </motion.div>
      </div>
    </section>
  );
}