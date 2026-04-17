import React from 'react';
import { Link } from 'react-router-dom';
import { Sparkles, Twitter, Linkedin, Youtube } from 'lucide-react';

export default function Footer() {
  return (
    <footer className="border-t border-slate-200 bg-white">
      <div className="max-w-7xl mx-auto px-6 lg:px-8 py-16">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-8">
          <div className="col-span-2">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-blue-500 flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-white" strokeWidth={2.5} />
              </div>
              <span className="text-[17px] font-semibold tracking-tight text-slate-900">TakeOff<span className="text-indigo-600">.ai</span></span>
            </div>
            <p className="mt-4 text-sm text-slate-600 max-w-xs leading-relaxed">
              AI-powered preconstruction software built by estimators, for estimators. Takeoff in minutes, not days.
            </p>
            <address className="not-italic mt-6 text-xs text-slate-500 leading-relaxed">
              5959 Waterford District Drive, Ste 200<br />
              Miami, Florida 33126<br />
              <a href="tel:+18778642524" className="hover:text-slate-900">877-TAKEOFF (877-864-2524)</a>
            </address>
            <div className="mt-5 flex items-center gap-3">
              <a href="#" className="w-9 h-9 rounded-lg border border-slate-200 flex items-center justify-center text-slate-500 hover:text-slate-900 hover:border-slate-300"><Twitter className="w-4 h-4" /></a>
              <a href="#" className="w-9 h-9 rounded-lg border border-slate-200 flex items-center justify-center text-slate-500 hover:text-slate-900 hover:border-slate-300"><Linkedin className="w-4 h-4" /></a>
              <a href="#" className="w-9 h-9 rounded-lg border border-slate-200 flex items-center justify-center text-slate-500 hover:text-slate-900 hover:border-slate-300"><Youtube className="w-4 h-4" /></a>
            </div>
          </div>
          <div>
            <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">Product</h4>
            <ul className="mt-4 space-y-3 text-sm text-slate-600">
              <li><Link to="/features" className="hover:text-slate-900">Features</Link></li>
              <li><Link to="/pricing" className="hover:text-slate-900">Pricing</Link></li>
              <li><Link to="/demo" className="hover:text-slate-900">Demo</Link></li>
              <li><Link to="/app" className="hover:text-slate-900">Dashboard</Link></li>
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">Trades</h4>
            <ul className="mt-4 space-y-3 text-sm text-slate-600">
              <li><Link to="/trades" className="hover:text-slate-900">Drywall</Link></li>
              <li><Link to="/trades" className="hover:text-slate-900">Electrical</Link></li>
              <li><Link to="/trades" className="hover:text-slate-900">Mechanical</Link></li>
              <li><Link to="/trades" className="hover:text-slate-900">Plumbing</Link></li>
              <li><Link to="/trades" className="hover:text-slate-900">Painting</Link></li>
              <li><Link to="/trades" className="hover:text-slate-900">All trades →</Link></li>
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">Company</h4>
            <ul className="mt-4 space-y-3 text-sm text-slate-600">
              <li><Link to="/about" className="hover:text-slate-900">About</Link></li>
              <li><a href="#" className="hover:text-slate-900">Careers</a></li>
              <li><a href="#" className="hover:text-slate-900">Blog</a></li>
              <li><a href="#" className="hover:text-slate-900">News</a></li>
              <li><a href="#" className="hover:text-slate-900">FAQs</a></li>
            </ul>
          </div>
          <div>
            <h4 className="text-xs font-semibold text-slate-900 uppercase tracking-wider">Compare</h4>
            <ul className="mt-4 space-y-3 text-sm text-slate-600">
              <li><Link to="/compare/bluebeam" className="hover:text-slate-900">vs Bluebeam</Link></li>
              <li><Link to="/compare/ost" className="hover:text-slate-900">vs OST</Link></li>
              <li><Link to="/compare/planswift" className="hover:text-slate-900">vs PlanSwift</Link></li>
            </ul>
          </div>
        </div>
        <div className="mt-12 pt-8 border-t border-slate-200 flex flex-col md:flex-row items-start md:items-center justify-between gap-3">
          <p className="text-xs text-slate-500">© 2026 TakeOff.ai. All rights reserved.</p>
          <div className="flex items-center gap-6 text-xs text-slate-500">
            <a href="#" className="hover:text-slate-900">Privacy Policy</a>
            <a href="#" className="hover:text-slate-900">Terms & Conditions</a>
            <a href="#" className="hover:text-slate-900">Security</a>
          </div>
        </div>
      </div>
    </footer>
  );
}
