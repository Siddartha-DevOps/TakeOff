import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Sparkles, LayoutDashboard, FolderOpen, Users, Settings, LogOut, Loader2,
  UserPlus, X, Trash2, Copy, Check, Clock, ShieldAlert,
} from 'lucide-react';
import { teamAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';

// Teams/roles/permissions + invites — memory/TOGAL_PARITY_REAUDIT.md #17.
// No SMTP/mail provider exists in this app (see models.Invite's docstring)
// so invites are shared as a copyable link rather than emailed — a real
// deployment would wire a mail provider here; the accept-token flow itself
// is fully real either way.

const ROLE_LABELS = { owner: 'Owner', admin: 'Admin', member: 'Member', viewer: 'Viewer' };
const ROLE_BADGE = {
  owner: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
  admin: 'bg-violet-50 text-violet-700 ring-violet-200',
  member: 'bg-slate-100 text-slate-700 ring-slate-200',
  viewer: 'bg-amber-50 text-amber-700 ring-amber-200',
};
const ASSIGNABLE_ROLES = ['admin', 'member', 'viewer']; // owner granted separately, only by an existing owner

export default function Team() {
  const nav = useNavigate();
  const { user, logout } = useAuth();
  const isAdmin = user?.role === 'owner' || user?.role === 'admin';
  const isOwner = user?.role === 'owner';

  const [members, setMembers] = useState(null);
  const [invites, setInvites] = useState(null);
  const [error, setError] = useState(null);
  const [showInviteForm, setShowInviteForm] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [inviting, setInviting] = useState(false);
  const [copiedToken, setCopiedToken] = useState(null);
  const [busyId, setBusyId] = useState(null);

  useEffect(() => { load(); }, []);

  async function load() {
    try {
      const [m, i] = await Promise.all([
        teamAPI.listMembers(),
        isAdmin ? teamAPI.listInvites() : Promise.resolve({ data: { invites: [] } }),
      ]);
      setMembers(m.data.members);
      setInvites(i.data.invites);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load team');
    }
  }

  async function submitInvite(e) {
    e.preventDefault();
    setInviting(true);
    try {
      await teamAPI.createInvite(inviteEmail, inviteRole);
      setInviteEmail('');
      setShowInviteForm(false);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to send invite');
    } finally {
      setInviting(false);
    }
  }

  async function changeRole(memberId, role) {
    setBusyId(memberId);
    try {
      await teamAPI.updateMemberRole(memberId, role);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to change role');
    } finally {
      setBusyId(null);
    }
  }

  async function removeMember(memberId) {
    if (!window.confirm('Remove this member? They will immediately lose access.')) return;
    setBusyId(memberId);
    try {
      await teamAPI.removeMember(memberId);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to remove member');
    } finally {
      setBusyId(null);
    }
  }

  async function revokeInvite(inviteId) {
    setBusyId(inviteId);
    try {
      await teamAPI.revokeInvite(inviteId);
      load();
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to revoke invite');
    } finally {
      setBusyId(null);
    }
  }

  function copyInviteLink(invite) {
    const url = `${window.location.origin}/invite/${invite.token}`;
    navigator.clipboard.writeText(url).catch(() => {});
    setCopiedToken(invite.token);
    setTimeout(() => setCopiedToken(null), 2000);
  }

  const handleLogout = () => { logout(); nav('/login'); };
  const pendingInvites = (invites || []).filter((i) => i.status === 'pending');

  return (
    <div className="min-h-screen bg-slate-50/60">
      <AppSidebar user={user} onLogout={handleLogout} />
      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 bg-white/80 backdrop-blur-xl border-b border-slate-200">
          <div className="flex items-center justify-between px-6 h-14">
            <h1 className="text-sm font-semibold text-slate-900">Team</h1>
            {isAdmin && (
              <button
                onClick={() => setShowInviteForm(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-xs font-medium text-white"
              >
                <UserPlus className="w-3.5 h-3.5" /> Invite member
              </button>
            )}
          </div>
        </header>

        <main className="p-6 max-w-4xl space-y-8">
          {error && <div className="p-3 rounded-lg bg-rose-50 border border-rose-200 text-sm text-rose-800">{error}</div>}

          {!isAdmin && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-slate-100 text-xs text-slate-600">
              <ShieldAlert className="w-3.5 h-3.5" /> Only owners and admins can invite members or change roles.
            </div>
          )}

          <section>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
              Members {members ? `(${members.filter((m) => m.is_active).length})` : ''}
            </h2>
            <div className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100">
              {(members || []).filter((m) => m.is_active).map((m) => (
                <div key={m.id} className="flex items-center gap-3 px-4 py-3">
                  <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center text-white text-xs font-semibold flex-shrink-0">
                    {(m.full_name || m.email).slice(0, 2).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-slate-900 truncate">{m.full_name || m.email}{m.id === user?.id ? ' (you)' : ''}</div>
                    <div className="text-xs text-slate-500 truncate">{m.email}</div>
                  </div>
                  {isAdmin && m.id !== user?.id ? (
                    <select
                      value={m.role}
                      onChange={(e) => changeRole(m.id, e.target.value)}
                      disabled={busyId === m.id || (m.role === 'owner' && !isOwner)}
                      className={`text-xs rounded-lg px-2 py-1 ring-1 ring-inset ${ROLE_BADGE[m.role]} disabled:opacity-60`}
                    >
                      {isOwner && <option value="owner">Owner</option>}
                      {ASSIGNABLE_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                    </select>
                  ) : (
                    <span className={`text-[11px] font-medium px-2 py-1 rounded-full ring-1 ring-inset ${ROLE_BADGE[m.role]}`}>{ROLE_LABELS[m.role]}</span>
                  )}
                  {isAdmin && m.id !== user?.id && (
                    <button
                      onClick={() => removeMember(m.id)}
                      disabled={busyId === m.id}
                      title="Remove from team"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 disabled:opacity-40"
                    >
                      {busyId === m.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                    </button>
                  )}
                </div>
              ))}
              {members === null && <div className="px-4 py-6 text-center text-sm text-slate-400">Loading…</div>}
            </div>
          </section>

          {isAdmin && (
            <section>
              <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-3">
                Pending invites {pendingInvites.length ? `(${pendingInvites.length})` : ''}
              </h2>
              <div className="bg-white border border-slate-200 rounded-xl divide-y divide-slate-100">
                {pendingInvites.map((inv) => (
                  <div key={inv.id} className="flex items-center gap-3 px-4 py-3">
                    <Clock className="w-4 h-4 text-amber-500 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-slate-900 truncate">{inv.email}</div>
                      <div className="text-xs text-slate-500">Expires {new Date(inv.expires_at).toLocaleDateString()}</div>
                    </div>
                    <span className={`text-[11px] font-medium px-2 py-1 rounded-full ring-1 ring-inset ${ROLE_BADGE[inv.role]}`}>{ROLE_LABELS[inv.role]}</span>
                    <button
                      onClick={() => copyInviteLink(inv)}
                      className="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-lg text-slate-600 hover:bg-slate-100"
                    >
                      {copiedToken === inv.token ? <><Check className="w-3.5 h-3.5 text-emerald-600" /> Copied</> : <><Copy className="w-3.5 h-3.5" /> Copy link</>}
                    </button>
                    <button
                      onClick={() => revokeInvite(inv.id)}
                      disabled={busyId === inv.id}
                      title="Revoke invite"
                      className="p-1.5 rounded-lg text-slate-400 hover:text-rose-600 hover:bg-rose-50 disabled:opacity-40"
                    >
                      {busyId === inv.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <X className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                ))}
                {invites !== null && pendingInvites.length === 0 && (
                  <div className="px-4 py-6 text-center text-sm text-slate-400">No pending invites.</div>
                )}
              </div>
            </section>
          )}
        </main>
      </div>

      {showInviteForm && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/50" onClick={() => setShowInviteForm(false)}>
          <div className="w-96 rounded-xl bg-white border border-slate-200 shadow-2xl p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-1.5"><UserPlus className="w-4 h-4" /> Invite a member</h3>
              <button onClick={() => setShowInviteForm(false)} className="text-slate-400 hover:text-slate-700"><X className="w-4 h-4" /></button>
            </div>
            <form onSubmit={submitInvite} className="space-y-3">
              <label className="block">
                <span className="text-xs font-medium text-slate-700">Email</span>
                <input
                  type="email" required autoFocus value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@company.com"
                  className="mt-1.5 w-full px-3 py-2 text-sm rounded-lg border border-slate-300 focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none"
                />
              </label>
              <label className="block">
                <span className="text-xs font-medium text-slate-700">Role</span>
                <select
                  value={inviteRole} onChange={(e) => setInviteRole(e.target.value)}
                  className="mt-1.5 w-full px-3 py-2 text-sm rounded-lg border border-slate-300"
                >
                  {ASSIGNABLE_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
                </select>
              </label>
              <button
                type="submit" disabled={inviting}
                className="w-full py-2.5 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800 disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {inviting ? <Loader2 className="w-4 h-4 animate-spin" /> : 'Send invite'}
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function AppSidebar({ user, onLogout }) {
  const items = [
    { icon: LayoutDashboard, label: 'Dashboard', to: '/app' },
    { icon: FolderOpen, label: 'Projects', to: '/app' },
    { icon: Users, label: 'Team', to: '/app/team', active: true },
    { icon: Settings, label: 'Settings', to: '#' },
  ];

  const initials =
    user?.full_name
      ? user.full_name.split(' ').map((x) => x[0]).slice(0, 2).join('')
      : user?.email?.substring(0, 2).toUpperCase() || 'U';

  return (
    <aside className="hidden lg:flex fixed top-0 left-0 h-screen w-64 flex-col border-r border-slate-200 bg-white z-40">
      <div className="h-14 px-5 flex items-center gap-2 border-b border-slate-200">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-blue-500 flex items-center justify-center">
          <Sparkles className="w-3.5 h-3.5 text-white" />
        </div>
        <span className="text-sm font-semibold text-slate-900">
          TakeOff<span className="text-indigo-600">.ai</span>
        </span>
      </div>

      <nav className="p-3 space-y-0.5">
        {items.map((i) => (
          <Link
            key={i.label}
            to={i.to}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium ${i.active ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-100'}`}
          >
            <i.icon className="w-4 h-4" />
            {i.label}
          </Link>
        ))}
      </nav>

      <div className="mt-auto p-3 border-t border-slate-200">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center text-white text-xs font-semibold">
            {initials}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold text-slate-900 truncate">
              {user?.full_name || user?.email}
            </div>
            <div className="text-[10px] text-slate-500 truncate">{user?.email}</div>
          </div>
          <button
            onClick={onLogout}
            className="w-7 h-7 rounded-md hover:bg-slate-100 flex items-center justify-center text-slate-500"
          >
            <LogOut className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </aside>
  );
}
