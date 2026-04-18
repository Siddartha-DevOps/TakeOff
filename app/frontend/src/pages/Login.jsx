import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sparkles, Mail, Lock, ArrowRight, Loader2, AlertCircle } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const [email, setEmail] = useState('');
  const [pw, setPw] = useState('');
  const [loading, setLoading] = useState(false);
   const [error, setError] = useState('');
  const nav = useNavigate();
  const { login } = useAuth();

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
  etError('');
    
    const result = await login(email, pw);
    
    if (result.success) {
      nav('/app');
    } else {
      setError(result.error);
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen grid grid-cols-1 lg:grid-cols-2 bg-white">
      <div className="flex flex-col justify-between p-8 lg:p-12">
        <Link to="/" className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-blue-500 flex items-center justify-center shadow-lg shadow-indigo-500/30">
            <Sparkles className="w-4 h-4 text-white" strokeWidth={2.5} />
          </div>
          <span className="text-[17px] font-semibold tracking-tight text-slate-900">TakeOff<span className="text-indigo-600">.ai</span></span>
        </Link>

        <div className="max-w-sm mx-auto w-full">
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Welcome back.</h1>
          <p className="mt-2 text-sm text-slate-600">Sign in to open your dashboard and continue estimating.</p>

   {error && (
            <div className="mt-4 p-3 rounded-lg bg-rose-50 border border-rose-200 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-rose-600 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-rose-800">{error}</p>
            </div>
          )}
          <form onSubmit={submit} className="mt-8 space-y-4">
            <button type="button" className="w-full py-2.5 rounded-lg border border-slate-300 text-sm font-medium text-slate-800 hover:bg-slate-50 flex items-center justify-center gap-2">
              <GoogleIcon /> Continue with Google
            </button>
            <button type="button" className="w-full py-2.5 rounded-lg border border-slate-300 text-sm font-medium text-slate-800 hover:bg-slate-50 flex items-center justify-center gap-2">
              <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path d="M10 2C5.58 2 2 5.58 2 10c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38l-.01-1.49c-2.22.48-2.69-1.07-2.69-1.07-.36-.93-.89-1.17-.89-1.17-.73-.5.05-.49.05-.49.8.06 1.22.82 1.22.82.72 1.23 1.88.87 2.34.67.07-.52.28-.87.5-1.07-1.77-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.13 0 0 .67-.22 2.2.82a7.6 7.6 0 014-.01c1.53-1.04 2.2-.82 2.2-.82.44 1.11.16 1.93.08 2.13.51.56.82 1.28.82 2.15 0 3.07-1.87 3.75-3.65 3.94.29.25.54.73.54 1.48l-.01 2.19c0 .21.15.46.55.38C15.71 16.53 18 13.54 18 10c0-4.42-3.58-8-8-8z"/></svg>
              Continue with GitHub
            </button>
            <div className="relative py-2"><div className="absolute inset-0 flex items-center"><div className="w-full border-t border-slate-200" /></div><div className="relative flex justify-center"><span className="bg-white px-2 text-xs text-slate-500">or</span></div></div>
            <label className="block">
              <span className="text-xs font-medium text-slate-700">Work email</span>
              <div className="mt-1.5 relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" className="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-300 bg-white focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none" />
              </div>
            </label>
            <label className="block">
              <div className="flex items-center justify-between"><span className="text-xs font-medium text-slate-700">Password</span><a href="#" className="text-xs text-slate-500 hover:text-slate-800">Forgot?</a></div>
              <div className="mt-1.5 relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input type="password" required value={pw} onChange={(e) => setPw(e.target.value)} placeholder="••••••••" className="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-300 bg-white focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none" />
              </div>
               <p className="mt-1 text-xs text-slate-500">Try: alex@acme.com / password123</p>
            </label>
            <button type="submit" disabled={loading} className="w-full py-2.5 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 flex items-center justify-center gap-2 disabled:opacity-50">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Sign in <ArrowRight className="w-3.5 h-3.5" /></>}
            </button>
          </form>

          <p className="mt-6 text-sm text-slate-600 text-center">
            New to TakeOff? <Link to="/signup" className="font-medium text-slate-900 hover:text-indigo-600">Create an account</Link>
          </p>
        </div>

        <div className="text-xs text-slate-500">© 2026 TakeOff.ai</div>
      </div>

      {/* Visual panel */}
      <div className="hidden lg:block relative bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950 overflow-hidden">
        <div className="absolute inset-0" style={{ backgroundImage: 'radial-gradient(circle at 20% 30%, rgba(99, 102, 241, 0.35), transparent 50%), radial-gradient(circle at 80% 70%, rgba(139, 92, 246, 0.3), transparent 50%)' }} />
        <div className="absolute inset-0" style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
        <div className="relative h-full flex flex-col justify-end p-12 text-white">
          <div className="max-w-md">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-xs font-medium backdrop-blur">
              <Sparkles className="w-3 h-3" /> AI takeoffs, from day one
            </div>
            <h2 className="mt-5 text-4xl font-semibold tracking-tight">The best estimators in the world start their day here.</h2>
            <p className="mt-4 text-white/70">Sign in to pick up where you left off — all your projects, collaborators and exports, in one place.</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg className="w-4 h-4" viewBox="0 0 48 48"><path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.9 29.3 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.3-.4-3.5z"/><path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.5 15.6 18.9 12 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.4 6.3 14.7z"/><path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.5-5.2l-6.2-5.3C29.2 34.8 26.7 36 24 36c-5.3 0-9.7-3.1-11.3-7.5l-6.5 5C9.5 39.7 16.2 44 24 44z"/><path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.3 5.6l6.2 5.3c-.4.4 6.8-5 6.8-14.9 0-1.3-.1-2.3-.4-3.5z"/></svg>
  );
}

