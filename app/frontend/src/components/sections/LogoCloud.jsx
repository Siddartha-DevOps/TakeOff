import React from 'react';
import { PARTNER_LOGOS } from '../../mock/mockData';

function LogoBadge({ name }) {
  // Generate a unique monochrome "logo" per partner name.
  const letters = name.split(' ').map((w) => w[0]).slice(0, 2).join('');
  const hues = ['from-slate-700 to-slate-900', 'from-slate-600 to-slate-800', 'from-slate-800 to-black'];
  const hue = hues[name.length % hues.length];
  return (
    <div className="flex-shrink-0 flex items-center gap-2 px-5 py-3 opacity-60 hover:opacity-100 transition-opacity">
      <div className={`w-7 h-7 rounded-md bg-gradient-to-br ${hue} flex items-center justify-center text-[10px] font-bold text-white tracking-tight`}>{letters}</div>
      <span className="text-sm font-semibold text-slate-700 whitespace-nowrap tracking-tight">{name}</span>
    </div>
  );
}

export default function LogoCloud({ title = 'Trusted every day by thousands of professional builders' }) {
  const logos = [...PARTNER_LOGOS, ...PARTNER_LOGOS];
  return (
    <section className="py-16 bg-white border-t border-slate-200/70">
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <p className="text-center text-sm text-slate-500 mb-10">{title}</p>
        <div className="relative overflow-hidden" style={{ maskImage: 'linear-gradient(to right, transparent, black 10%, black 90%, transparent)', WebkitMaskImage: 'linear-gradient(to right, transparent, black 10%, black 90%, transparent)' }}>
          <div className="flex animate-scroll-x" style={{ width: 'max-content' }}>
            {logos.map((name, i) => (<LogoBadge key={`${name}-${i}`} name={name} />))}
          </div>
        </div>
      </div>
    </section>
  );
}
