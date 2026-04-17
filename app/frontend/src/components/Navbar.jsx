import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { Menu, X, ArrowRight, ChevronDown, Sparkles } from 'lucide-react';

const navGroups = {
  Product: [
    { label: 'Features', href: '/features', desc: 'AI takeoff, compare & chat' },
    { label: 'Demo', href: '/demo', desc: 'See the workflow in action' },
    { label: 'Dashboard', href: '/app', desc: 'Open the live app' },
  ],
  Trades: [
    { label: 'All trades', href: '/trades', desc: 'Every trade we support' },
    { label: 'Drywall', href: '/trades?t=drywall', desc: 'Partitions, gyp, ceiling' },
    { label: 'Electrical', href: '/trades?t=electrical', desc: 'Fixtures, outlets, conduit' },
    { label: 'Mechanical', href: '/trades?t=mechanical', desc: 'Ductwork & HVAC' },
  ],
  Compare: [
    { label: 'vs Bluebeam', href: '/compare/bluebeam', desc: 'Markup tool vs full takeoff' },
    { label: 'vs OST', href: '/compare/ost', desc: 'Legacy desktop comparison' },
    { label: 'vs PlanSwift', href: '/compare/planswift', desc: 'Modern cloud alternative' },
  ],
};

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const [hover, setHover] = useState(null);
  const location = useLocation();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener('scroll', onScroll);
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => { setOpen(false); setHover(null); }, [location.pathname]);

  return (
    <header className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${scrolled ? 'bg-white/80 backdrop-blur-xl border-b border-slate-200/80' : 'bg-transparent'}`}>
      <div className="max-w-7xl mx-auto px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-10">
            <Link to="/" className="flex items-center gap-2 group">
              <div className="relative">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-blue-500 flex items-center justify-center shadow-lg shadow-indigo-500/30">
                  <Sparkles className="w-4 h-4 text-white" strokeWidth={2.5} />
                </div>
                <div className="absolute inset-0 rounded-lg bg-indigo-400/50 blur-xl opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              <span className="text-[17px] font-semibold tracking-tight text-slate-900">TakeOff<span className="text-indigo-600">.ai</span></span>
            </Link>
            <nav className="hidden lg:flex items-center gap-1" onMouseLeave={() => setHover(null)}>
              {Object.keys(navGroups).map((g) => (
                <div key={g} className="relative" onMouseEnter={() => setHover(g)}>
                  <button className={`px-3 py-2 text-sm font-medium flex items-center gap-1 rounded-md transition-colors ${hover === g ? 'text-slate-900 bg-slate-100' : 'text-slate-600 hover:text-slate-900'}`}>
                    {g}<ChevronDown className="w-3.5 h-3.5 opacity-60" />
                  </button>
                  {hover === g && (
                    <div className="absolute top-full left-0 pt-2">
                      <div className="w-72 bg-white rounded-xl shadow-xl shadow-slate-900/10 border border-slate-200 overflow-hidden animate-fade-in">
                        {navGroups[g].map((item) => (
                          <Link key={item.href} to={item.href} className="block px-4 py-3 hover:bg-slate-50">
                            <div className="text-sm font-semibold text-slate-900">{item.label}</div>
                            <div className="text-xs text-slate-500 mt-0.5">{item.desc}</div>
                          </Link>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
              <Link to="/pricing" className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 rounded-md">Pricing</Link>
              <Link to="/about" className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 rounded-md">Company</Link>
            </nav>
          </div>
          <div className="hidden lg:flex items-center gap-2">
            <Link to="/login" className="px-3 py-2 text-sm font-medium text-slate-600 hover:text-slate-900">Sign in</Link>
            <Link to="/signup" className="px-4 py-2 text-sm font-medium text-slate-700 border border-slate-300 rounded-lg hover:bg-slate-50">Start free</Link>
            <Link to="/demo" className="px-4 py-2 text-sm font-medium text-white bg-slate-900 rounded-lg hover:bg-slate-800 inline-flex items-center gap-1.5 shadow-sm">
              Book a demo <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
          <button className="lg:hidden p-2 -mr-2 text-slate-700" onClick={() => setOpen(!open)} aria-label="Menu">
            {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>
      {open && (
        <div className="lg:hidden border-t border-slate-200 bg-white">
          <div className="px-6 py-4 space-y-1">
            <Link to="/features" className="block py-2 text-sm font-medium text-slate-700">Features</Link>
            <Link to="/trades" className="block py-2 text-sm font-medium text-slate-700">Trades</Link>
            <Link to="/compare/bluebeam" className="block py-2 text-sm font-medium text-slate-700">Compare</Link>
            <Link to="/pricing" className="block py-2 text-sm font-medium text-slate-700">Pricing</Link>
            <Link to="/about" className="block py-2 text-sm font-medium text-slate-700">Company</Link>
            <Link to="/demo" className="block py-2 text-sm font-medium text-slate-700">Demo</Link>
            <div className="pt-3 mt-3 border-t border-slate-200 space-y-2">
              <Link to="/login" className="block text-center py-2 text-sm font-medium text-slate-700 border border-slate-300 rounded-lg">Sign in</Link>
              <Link to="/demo" className="block text-center py-2.5 text-sm font-medium text-white bg-slate-900 rounded-lg">Book a demo</Link>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
