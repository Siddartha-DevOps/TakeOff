import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Sparkles, Mail, Lock, User, ArrowRight, Loader2, AlertCircle, ShieldCheck } from 'lucide-react';
import { teamAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';

const ROLE_LABELS = { owner: 'Owner', admin: 'Admin', member: 'Member', viewer: 'Viewer' };

// Public accept-invite landing page — memory/TOGAL_PARITY_REAUDIT.md #17.
// No account/auth required to view this: the invitee doesn't have an
// account yet, that's the whole point of the flow.
export default function AcceptInvite() {
  const { token } = useParams();
  const nav = useNavigate();
  const { loginWithSession } = useAuth();

  const [preview, setPreview] = useState(null);
  const [previewError, setPreviewError] = useState(null);
  const [fullName, setFullName] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');

  useEffect(() => {
    teamAPI.previewInvite(token)
      .then((res) => setPreview(res.data))
      .catch((err) => setPreviewError(err.response?.data?.detail || 'This invite link is invalid.'));
  }, [token]);

  const submit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError('');
    try {
      const res = await teamAPI.acceptInvite(token, fullName, password);
      loginWithSession(res.data.access_token, res.data.user);
      nav('/app');
    } catch (err) {
      setSubmitError(err.response?.data?.detail || 'Failed to accept invite.');
      setSubmitting(false);
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
          {previewError ? (
            <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 flex items-start gap-2">
              <AlertCircle className="w-4 h-4 text-rose-600 mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm text-rose-800">{previewError}</p>
                <Link to="/login" className="mt-2 inline-block text-xs font-medium text-rose-700 underline">Go to sign in</Link>
              </div>
            </div>
          ) : !preview ? (
            <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 className="w-4 h-4 animate-spin" /> Checking invite…</div>
          ) : (
            <>
              <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-700 text-xs font-medium mb-3">
                <ShieldCheck className="w-3.5 h-3.5" /> {ROLE_LABELS[preview.role] || preview.role}
              </div>
              <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Join {preview.organization_name}.</h1>
              <p className="mt-2 text-sm text-slate-600">
                You've been invited as <strong>{preview.email}</strong>. Set a name and password to finish joining.
              </p>

              {submitError && (
                <div className="mt-4 p-3 rounded-lg bg-rose-50 border border-rose-200 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 text-rose-600 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-rose-800">{submitError}</p>
                </div>
              )}

              <form onSubmit={submit} className="mt-8 space-y-4">
                <label className="block">
                  <span className="text-xs font-medium text-slate-700">Full name</span>
                  <div className="mt-1.5 relative">
                    <User className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      type="text" required autoFocus value={fullName} onChange={(e) => setFullName(e.target.value)}
                      placeholder="Alex Rivera"
                      className="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-300 bg-white focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none"
                    />
                  </div>
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-slate-700">Email</span>
                  <div className="mt-1.5 relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input type="email" disabled value={preview.email} className="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-200 bg-slate-50 text-slate-500" />
                  </div>
                </label>
                <label className="block">
                  <span className="text-xs font-medium text-slate-700">Password</span>
                  <div className="mt-1.5 relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                    <input
                      type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)}
                      placeholder="8+ characters"
                      className="w-full pl-9 pr-3 py-2.5 text-sm rounded-lg border border-slate-300 bg-white focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none"
                    />
                  </div>
                </label>
                <button type="submit" disabled={submitting} className="w-full py-2.5 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 flex items-center justify-center gap-2 disabled:opacity-50">
                  {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Join team <ArrowRight className="w-3.5 h-3.5" /></>}
                </button>
              </form>
            </>
          )}
        </div>

        <div className="text-xs text-slate-500">© 2026 TakeOff.ai</div>
      </div>

      <div className="hidden lg:flex relative bg-gradient-to-br from-slate-900 via-slate-900 to-indigo-950 overflow-hidden items-center p-12">
        <div className="absolute inset-0" style={{ backgroundImage: 'radial-gradient(circle at 80% 20%, rgba(99, 102, 241, 0.35), transparent 50%), radial-gradient(circle at 20% 80%, rgba(139, 92, 246, 0.3), transparent 50%)' }} />
        <div className="relative max-w-md text-white">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white/10 border border-white/15 text-xs font-medium backdrop-blur"><Sparkles className="w-3 h-3" /> Team takeoffs</div>
          <h2 className="mt-5 text-4xl font-semibold tracking-tight">Estimating is better together.</h2>
          <p className="mt-4 text-white/70">Shared projects, live cursors, role-based access — your whole team working from the same set of drawings.</p>
        </div>
      </div>
    </div>
  );
}
