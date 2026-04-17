import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sparkles, Mail, Lock, User, Building2, ArrowRight, Loader2, Check } from 'lucide-react';

export default function Signup() {
  const [form, setForm] = useState({ name: '', email: '', company: '', pw: '' });
  const [loading, setLoading] = useState(false);
  const nav = useNavigate();

  const submit = (e) => {
    e.preventDefault();
    setLoading(true);
    setTimeout(() => {
      localStorage.setItem('takeoff_user', JSON.stringify({ email: form.email, name: form.name, company: form.company }));
      nav('/app');
    }, 900);
  };

  const upd = (k) => (e) => setForm({ ...form, [k]: e.target.value });

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2 bg-white">
      <div className="flex flex-col justify-between p-8 lg:p-12 order-2 lg:order-1">
        <Link to="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-blue-500 flex items-center justify-center shadow-lg shadow-indigo-500/30">
            <Sparkles className="w-4 h-4 text-white" strokeWidth={2.5} />
          </div>
          <span className="text-[17px] font-semibold tracking-tight text-slate-900">TakeOff<span className="text-indigo-600">.ai</span></span>
        </Link>

        <div className="max-w-sm mx-auto w-full">
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Start free for 14 days.</h1>
          <p className="mt-2 text-sm text-slate-600">No credit card required. Full Growth plan access.</p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Full name" icon={User} value={form.name} onChange={upd('name')} placeholder="Alex Rivera" required />
              <Field label="Company" icon={Building2} value={form.company} onChange={upd('company')} placeholder="Acme Construction" />
            </div>
            <Field label="Work email" type="email" icon={Mail} value={form.email} onChange={upd('email')} placeholder="you@company.com" required />
            <Field label="Password" type="password" icon={Lock} value={form.pw} onChange={upd('pw')} placeholder="8+ characters" required />

            <button type="submit" disabled={loading} className="w-full py-2.5 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 flex items-center justify-center gap-2 disabled:opacity-50">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Create account <ArrowRight className="w-3.5 h-3.5" /></>}
            </button>

            <p className="text-xs text-slate-500 text-center leading-relaxed">
              By creating an account you agree to our <a href="#" className="text-slate-700 underline">Terms</a> and <a href="#" className="text-slate-700 underline">Privacy</a>.
            </p>
          </form>

          <p className="mt-6 text-sm text-slate-600 text-center">
            Already have an account? <Link to="/login" className="font-medium text-slate-900 hover:text-indigo-600">Sign in</Link>
          </p>
        </div>

        <div className="text-xs text-slate-500">© 2026 TakeOff.ai</div>
      </div>

      <div className="hidden lg:flex order-1 lg:order-2 relative bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950 overflow-hidden items-center p-12">
        <div className="absolute inset-0" style={{ backgroundImage: 'radial-gradient(circle at 80% 20%, rgba(99, 102, 241, 0.35), transparent 50%), radial-gradient(circle at 20% 80%, rgba(139, 92, 246, 0.3), transparent 50%)' }} />
        <div className="relative max-w-md text-white">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-xs font-medium backdrop-blur"><Sparkles className="w-3 h-3" /> What you get</div>
          <h2 className="mt-5 text-4xl font-semibold tracking-tight">Everything you need to win more bids.</h2>
          <ul className="mt-8 space-y-3">
            {['Unlimited AI-powered takeoffs', 'Real-time cloud collaboration', 'Revision compare on one click', 'TakeOff Chat — ask your plans anything', 'Export to Excel, CSV or JSON', '20-minute support SLA'].map((f) => (
              <li key={f} className="flex items-start gap-2.5 text-sm text-white/90"><Check className="w-4 h-4 text-emerald-400 mt-0.5" /> {f}</li>
            ))}
          </ul>
          <div className="mt-10 p-5 rounded-xl bg-white/5 border border-white/10 backdrop-blur">
            <p className="text-sm text-white/90 leading-relaxed">“Paid for itself in a week. 30-story high-rise takeoff went from 2 weeks to 48 hours.”</p>
            <div className="mt-3 text-xs text-white/60">— Brad Preston, Total Flooring Contractors</div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, icon: Icon, type = 'text', ...props }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-slate-700">{label}</span>
      <div className="mt-1.5 relative">
        {Icon && <Icon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />}
        <input type={type} {...props} className={`w-full ${Icon ? 'pl-9' : 'pl-3'} pr-3 py-2.5 text-sm rounded-lg border border-slate-300 bg-white focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none`} />
      </div>
    </label>
  );
}
