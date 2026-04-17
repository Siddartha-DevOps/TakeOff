import React from 'react';
import { AWARDS } from '../../mock/mockData';
import { Award, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

export default function Awards() {
  return (
    <section className="py-24 bg-slate-50/60">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="text-center max-w-2xl mx-auto">
          <h2 className="text-4xl md:text-5xl font-semibold tracking-tight text-slate-900 text-balance">
            Revolutionizing preconstruction.
          </h2>
          <p className="mt-4 text-lg text-slate-600">Recognized around the world for innovation in construction estimating software.</p>
          <Link to="/demo" className="mt-6 inline-flex items-center gap-1.5 text-sm font-medium text-indigo-600 hover:text-indigo-700">
            Take a tour <ArrowRight className="w-3.5 h-3.5" />
          </Link>
        </div>
        <div className="mt-14 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {AWARDS.map((a) => (
            <div key={a.name} className="rounded-2xl bg-white border border-slate-200 p-6 flex flex-col items-center text-center hover:border-slate-300 hover:shadow-sm">
              <div className="w-12 h-12 rounded-full bg-gradient-to-br from-amber-100 to-amber-50 border border-amber-200 flex items-center justify-center">
                <Award className="w-5 h-5 text-amber-600" strokeWidth={2} />
              </div>
              <div className="mt-4 text-sm font-semibold text-slate-900 leading-tight">{a.name}</div>
              <div className="mt-1 text-[11px] text-slate-500 mono">{a.year}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
