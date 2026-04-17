import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sparkles, LayoutDashboard, FolderOpen, Users, Settings, LogOut, Search, Plus, MoreVertical, Upload, Bell, HelpCircle, ArrowUpRight } from 'lucide-react';
import * as LIcons from 'lucide-react';
import { SAMPLE_PROJECTS, DASHBOARD_ACTIVITY } from '../mock/mockData';

const STATUS_STYLES = {
  Active: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  Review: 'bg-amber-50 text-amber-700 ring-amber-200',
  Draft: 'bg-slate-100 text-slate-700 ring-slate-200',
  Archived: 'bg-slate-50 text-slate-500 ring-slate-200',
};

const ACTIVITY_COLORS = {
  indigo: 'bg-indigo-50 text-indigo-600',
  violet: 'bg-violet-50 text-violet-600',
  cyan: 'bg-cyan-50 text-cyan-600',
  emerald: 'bg-emerald-50 text-emerald-600',
  amber: 'bg-amber-50 text-amber-600',
};

function StatCard({ label, value, delta, color, icon: Icon }) {
  const colorClasses = {
    indigo: 'bg-indigo-50 text-indigo-600',
    violet: 'bg-violet-50 text-violet-600',
    cyan: 'bg-cyan-50 text-cyan-600',
    emerald: 'bg-emerald-50 text-emerald-600',
  };
  

export default function Dashboard() {
  const nav = useNavigate();
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('All');
  const [showNewProject, setShowNewProject] = useState(false);
  const user = JSON.parse(localStorage.getItem('takeoff_user') || '{"name":"Alex Rivera","email":"alex@acme.com"}');

  const filtered = SAMPLE_PROJECTS.filter((p) => {
    if (filter !== 'All' && p.status !== filter) return false;
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="min-h-screen bg-slate-50/60">
      <AppSidebar user={user} />
      <div className="lg:pl-64">
        {/* Top bar */}
        <header className="sticky top-0 z-30 bg-white/80 backdrop-blur-xl border-b border-slate-200">
          <div className="flex items-center gap-4 px-6 h-14">
            <div className="relative flex-1 max-w-xl">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search projects, sheets or detections..." className="w-full pl-9 pr-3 py-2 text-sm rounded-lg bg-slate-100 border border-transparent focus:bg-white focus:border-slate-300 focus:ring-2 focus:ring-slate-200 outline-none" />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] mono text-slate-500 border border-slate-300 rounded px-1.5 py-0.5">⌘K</span>
            </div>
            <div className="flex items-center gap-1">
              <button className="w-9 h-9 rounded-lg hover:bg-slate-100 flex items-center justify-center text-slate-600"><HelpCircle className="w-4 h-4" /></button>
              <button className="w-9 h-9 rounded-lg hover:bg-slate-100 flex items-center justify-center text-slate-600 relative">
                <Bell className="w-4 h-4" />
                <span className="absolute top-1.5 right-2 w-1.5 h-1.5 rounded-full bg-rose-500" />
              </button>
              <button onClick={() => setShowNewProject(true)} className="ml-2 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800">
                <Plus className="w-3.5 h-3.5" /> New project
              </button>
            </div>
          </div>
        </header>

        <main className="px-6 py-8">
          {/* Welcome + stats */}
          <div className="flex items-end justify-between">
            <div>
              <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Welcome back, {(user.name || user.email).split(' ')[0]}.</h1>
              <p className="mt-1 text-sm text-slate-500">You have 3 active projects and 2 review items today.</p>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard label="Active projects" value="3" delta="+1 this week" color="indigo" icon={FolderOpen} />
            <StatCard label="AI detections (30d)" value="2,418" delta="+18% vs last month" color="violet" icon={Sparkles} />
            <StatCard label="Hours saved (est.)" value="142h" delta="Team total" color="cyan" icon={LIcons.Clock} />
            <StatCard label="Bids submitted" value="9" delta="3 in review" color="emerald" icon={LIcons.FileCheck} />
          </div>

          {/* Content grid */}
          <div className="mt-10 grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-6">
            <section>
              <div className="flex items-center justify-between">
                <h2 className="text-base font-semibold text-slate-900">Projects</h2>
                <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
                  {['All', 'Active', 'Review', 'Draft', 'Archived'].map((f) => (
                    <button key={f} onClick={() => setFilter(f)} className={`px-3 py-1 text-xs font-medium rounded-md ${filter === f ? 'bg-slate-900 text-white' : 'text-slate-600 hover:text-slate-900'}`}>{f}</button>
                  ))}
                </div>
              </div>
              <div className="mt-4 rounded-2xl border border-slate-200 bg-white overflow-hidden">
                <div className="hidden md:grid grid-cols-[1fr_120px_130px_100px_60px] gap-4 px-5 py-3 text-[11px] uppercase tracking-wider text-slate-500 font-semibold border-b border-slate-200 bg-slate-50/60">
                  <div>Project</div><div>Status</div><div>Updated</div><div>Progress</div><div />
                </div>
                {filtered.length === 0 ? (
                  <div className="p-10 text-center text-sm text-slate-500">No projects match.</div>
                ) : filtered.map((p) => (
                  <div key={p.id} onClick={() => nav(`/app/projects/${p.id}`)} className="grid grid-cols-[1fr_auto] md:grid-cols-[1fr_120px_130px_100px_60px] gap-4 px-5 py-4 items-center border-b border-slate-100 last:border-0 hover:bg-slate-50 cursor-pointer group">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold text-slate-900 truncate">{p.name}</span>
                        <ArrowUpRight className="w-3.5 h-3.5 text-slate-400 opacity-0 group-hover:opacity-100" />
                      </div>
                      <div className="mt-0.5 text-xs text-slate-500 truncate">{p.type} · {p.sheets} sheets · {p.owner}</div>
                    </div>
                    <div className="hidden md:block"><span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ring-1 ${STATUS_STYLES[p.status]}`}>{p.status}</span></div>
                    <div className="hidden md:block text-xs text-slate-500">{p.updated}</div>
                    <div className="hidden md:flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-slate-100 overflow-hidden">
                        <div className="h-full rounded-full bg-gradient-to-r from-indigo-500 to-violet-500" style={{ width: `${p.progress}%` }} />
                      </div>
                      <span className="mono text-[10px] text-slate-600 w-7 text-right">{p.progress}%</span>
                    </div>
                    <div className="hidden md:flex justify-end"><button onClick={(e) => e.stopPropagation()} className="w-7 h-7 rounded-md hover:bg-slate-200 flex items-center justify-center text-slate-500"><MoreVertical className="w-3.5 h-3.5" /></button></div>
                  </div>
                ))}
              </div>
            </section>

            {/* Right column */}
            <aside className="space-y-6">
              <section className="rounded-2xl border border-slate-200 bg-white p-5">
                <h3 className="text-sm font-semibold text-slate-900">Recent activity</h3>
                <div className="mt-4 space-y-4">
                  {DASHBOARD_ACTIVITY.map((a, i) => {
                    const Icon = LIcons[a.icon] || Sparkles;
                    return (
                      <div key={i} className="flex items-start gap-3">
                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${ACTIVITY_COLORS[a.color]}`}>
                          <Icon className="w-4 h-4" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm text-slate-800 leading-snug">{a.text}</div>
                          <div className="text-xs text-slate-500 mt-0.5">{a.time}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
              <section className="rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-900 to-indigo-950 p-5 text-white relative overflow-hidden">
                <div className="absolute inset-0 opacity-40" style={{ backgroundImage: 'radial-gradient(circle at 80% 20%, rgba(99, 102, 241, 0.4), transparent 50%)' }} />
                <div className="relative">
                  <Sparkles className="w-6 h-6 text-indigo-300" />
                  <h3 className="mt-3 text-base font-semibold">Upgrade to Business</h3>
                  <p className="mt-1 text-xs text-white/70 leading-relaxed">Unlock SSO, dedicated support and custom libraries.</p>
                  <button className="mt-4 w-full py-2 rounded-lg bg-white text-slate-900 text-xs font-semibold">Talk to sales</button>
                </div>
              </section>
            </aside>
          </div>
        </main>
      </div>

      {showNewProject && <NewProjectModal onClose={() => setShowNewProject(false)} onCreate={(p) => { setShowNewProject(false); nav(`/app/projects/${p || SAMPLE_PROJECTS[0].id}`); }} />}
    </div>
  );
}

function StatCard({ label, value, delta, color, icon: Icon }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-500">{label}</span> 
       <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${colorClasses[color]}`}><Icon className=\"w-3.5 h-3.5\" /></div>
      </div>
      <div className="mt-3 text-2xl font-semibold tracking-tight text-slate-900">{value}</div>
      <div className="mt-0.5 text-xs text-slate-500">{delta}</div>
    </div>
  );
}

function AppSidebar({ user }) {
  const items = [
    { icon: LayoutDashboard, label: 'Dashboard', to: '/app', active: true },
    { icon: FolderOpen, label: 'Projects', to: '/app' },
    { icon: Users, label: 'Team', to: '#' },
    { icon: Settings, label: 'Settings', to: '#' },
  ];
  return (
    <aside className="hidden lg:flex fixed top-0 left-0 h-screen w-64 flex-col border-r border-slate-200 bg-white z-40">
      <div className="h-14 px-5 flex items-center gap-2 border-b border-slate-200">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 via-violet-500 to-blue-500 flex items-center justify-center">
          <Sparkles className="w-3.5 h-3.5 text-white" strokeWidth={2.5} />
        </div>
        <span className="text-sm font-semibold text-slate-900 tracking-tight">TakeOff<span className="text-indigo-600">.ai</span></span>
        <span className="ml-auto text-[10px] mono text-slate-500 border border-slate-200 rounded px-1.5 py-0.5">Pro</span>
      </div>
      <nav className="p-3 space-y-0.5">
        {items.map((i) => (
          <Link key={i.label} to={i.to} className={`flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium ${i.active ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-100'}`}>
            <i.icon className="w-4 h-4" /> {i.label}
          </Link>
        ))}
      </nav>
      <div className="p-3">
        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-semibold px-3 py-2">Recent projects</div>
        {SAMPLE_PROJECTS.slice(0, 4).map((p) => (
          <Link key={p.id} to={`/app/projects/${p.id}`} className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs text-slate-600 hover:bg-slate-100 truncate">
            <span className="w-1.5 h-1.5 rounded-full bg-slate-300 flex-shrink-0" /> <span className="truncate">{p.name}</span>
          </Link>
        ))}
      </div>
      <div className="mt-auto p-3 border-t border-slate-200">
        <div className="flex items-center gap-2.5 px-2 py-2">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center text-white text-xs font-semibold">
            {(user.name || 'U').split(' ').map((x) => x[0]).slice(0, 2).join('')}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-semibold text-slate-900 truncate">{user.name || user.email}</div>
            <div className="text-[10px] text-slate-500 truncate">{user.email}</div>
          </div>
          <Link to="/" className="w-7 h-7 rounded-md hover:bg-slate-100 flex items-center justify-center text-slate-500"><LogOut className="w-3.5 h-3.5" /></Link>
        </div>
      </div>
    </aside>
  );
}

function NewProjectModal({ onClose, onCreate }) {
  const [name, setName] = useState('');
  const [dragging, setDragging] = useState(false);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" onClick={onClose}>
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" />
      <div onClick={(e) => e.stopPropagation()} className="relative w-full max-w-lg rounded-2xl bg-white border border-slate-200 shadow-2xl p-7 animate-fade-up">
        <h3 className="text-lg font-semibold text-slate-900">New project</h3>
        <p className="mt-1 text-sm text-slate-500">Drop your plans to kick off an AI takeoff.</p>
        <div className="mt-5 space-y-3">
          <label className="block">
            <span className="text-xs font-medium text-slate-700">Project name</span>
            <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Waterford Tower L12" className="mt-1.5 w-full px-3 py-2.5 text-sm rounded-lg border border-slate-300 focus:border-slate-500 focus:ring-2 focus:ring-slate-200 outline-none" />
          </label>
          <div onDragOver={(e) => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); }} className={`rounded-xl border-2 border-dashed p-8 text-center ${dragging ? 'border-indigo-400 bg-indigo-50/40' : 'border-slate-300 bg-slate-50/60'}`}>
            <Upload className="w-6 h-6 text-slate-400 mx-auto" />
            <p className="mt-2 text-sm font-medium text-slate-900">Drop your plans here</p>
            <p className="mt-0.5 text-xs text-slate-500">PDF, TIFF, PNG up to 500MB</p>
          </div>
        </div>
        <div className="mt-6 flex items-center justify-end gap-2">
          <button onClick={onClose} className="px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg">Cancel</button>
          <button onClick={() => onCreate()} className="px-4 py-2 text-sm font-medium text-white bg-slate-900 rounded-lg hover:bg-slate-800">Create project</button>
        </div>
      </div>
    </div>
  );
}
