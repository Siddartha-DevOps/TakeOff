import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sparkles, LayoutDashboard, FolderOpen, Users, Settings, LogOut, Search, Plus, MoreVertical, Upload, Bell, HelpCircle, ArrowUpRight, Loader2 } from 'lucide-react';
import * as LIcons from 'lucide-react';
import { DASHBOARD_ACTIVITY } from '../mock/mockData';
import { projectsAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import CreateProjectModal from '../components/CreateProjectModal';

const STATUS_STYLES = {
active: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
review: 'bg-amber-50 text-amber-700 ring-amber-200',
draft: 'bg-slate-100 text-slate-700 ring-slate-200',
archived: 'bg-slate-50 text-slate-500 ring-slate-200',
};

const ACTIVITY_COLORS = {
indigo: 'bg-indigo-50 text-indigo-600',
violet: 'bg-violet-50 text-violet-600',
cyan: 'bg-cyan-50 text-cyan-600',
emerald: 'bg-emerald-50 text-emerald-600',
amber: 'bg-amber-50 text-amber-600',
};

export default function Dashboard() {
const nav = useNavigate();
const { user, logout } = useAuth();

const [search, setSearch] = useState('');
const [filter, setFilter] = useState('All');
const [projects, setProjects] = useState([]);
const [loading, setLoading] = useState(true);
const [showNewProject, setShowNewProject] = useState(false);

useEffect(() => {
fetchProjects();
}, []);

const fetchProjects = async () => {
try {
setLoading(true);
const response = await projectsAPI.list();
const projectData = response.data || [];
setProjects(Array.isArray(projectData) ? projectData : []);
} catch (error) {
console.error('Failed to fetch projects:', error);
setProjects([]);
} finally {
setLoading(false);
}
};

const filtered = Array.isArray(projects)
? projects.filter((p) => {
if (filter !== 'All' && p.status !== filter.toLowerCase()) return false;
if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
return true;
})
: [];

const handleLogout = () => {
logout();
nav('/login');
};

const handleProjectCreated = (newProject) => {
setProjects([newProject, ...projects]);
setShowNewProject(false);
};

return ( <div className="min-h-screen bg-slate-50/60"> <AppSidebar user={user} onLogout={handleLogout} />

```
  <div className="lg:pl-64">
    <header className="sticky top-0 z-30 bg-white/80 backdrop-blur-xl border-b border-slate-200">
      <div className="flex items-center gap-4 px-6 h-14">
        <div className="relative flex-1 max-w-xl">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search projects, sheets or detections..."
            className="w-full pl-9 pr-3 py-2 text-sm rounded-lg bg-slate-100 border border-transparent focus:bg-white focus:border-slate-300 focus:ring-2 focus:ring-slate-200 outline-none"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] mono text-slate-500 border border-slate-300 rounded px-1.5 py-0.5">
            ⌘K
          </span>
        </div>

        <div className="flex items-center gap-1">
          <button className="w-9 h-9 rounded-lg hover:bg-slate-100 flex items-center justify-center text-slate-600">
            <HelpCircle className="w-4 h-4" />
          </button>

          <button className="w-9 h-9 rounded-lg hover:bg-slate-100 flex items-center justify-center text-slate-600 relative">
            <Bell className="w-4 h-4" />
            <span className="absolute top-1.5 right-2 w-1.5 h-1.5 rounded-full bg-rose-500" />
          </button>

          <button
            onClick={() => setShowNewProject(true)}
            className="ml-2 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-900 text-white text-sm font-medium hover:bg-slate-800"
          >
            <Plus className="w-3.5 h-3.5" /> New project
          </button>
        </div>
      </div>
    </header>

    <main className="px-6 py-8">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
            Welcome back, {user?.full_name?.split(' ')[0] || user?.email?.split('@')[0] || 'User'}.
          </h1>

          <p className="mt-1 text-sm text-slate-500">
            You have {projects.filter(p => p.status === 'active').length} active projects and {projects.filter(p => p.status === 'review').length} review items today.
          </p>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Active projects" value={projects.filter(p => p.status === 'active').length.toString()} delta="+1 this week" color="indigo" icon={FolderOpen} />
        <StatCard label="AI detections (30d)" value="2,418" delta="+18% vs last month" color="violet" icon={Sparkles} />
        <StatCard label="Hours saved (est.)" value="142h" delta="Team total" color="cyan" icon={LIcons.Clock} />
        <StatCard label="Bids submitted" value="9" delta="3 in review" color="emerald" icon={LIcons.FileCheck} />
      </div>

      <div className="mt-10 grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-6">
        <section>
          <div className="flex items-center justify-between">
            <h2 className="text-base font-semibold text-slate-900">Projects</h2>
          </div>

          <div className="mt-4 rounded-2xl border border-slate-200 bg-white overflow-hidden">
            {loading ? (
              <div className="p-10 text-center">
                <Loader2 className="w-6 h-6 animate-spin mx-auto text-indigo-600" />
                <p className="mt-2 text-sm text-slate-500">Loading projects...</p>
              </div>
            ) : filtered.length === 0 ? (
              <div className="p-10 text-center text-sm text-slate-500">
                No projects match.
              </div>
            ) : (
              filtered.map((p) => (
                <div
                  key={p.id}
                  onClick={() => nav(`/app/projects/${p.id}`)}
                  className="grid grid-cols-[1fr_auto] gap-4 px-5 py-4 items-center border-b border-slate-100 hover:bg-slate-50 cursor-pointer"
                >
                  <div className="text-sm font-semibold text-slate-900">
                    {p.name}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        <aside className="space-y-6">
          <section className="rounded-2xl border border-slate-200 bg-white p-5">
            <h3 className="text-sm font-semibold text-slate-900">
              Recent activity
            </h3>

            <div className="mt-4 space-y-4">
              {DASHBOARD_ACTIVITY.map((a, i) => {
                const Icon = LIcons[a.icon] || Sparkles;

                return (
                  <div key={i} className="flex items-start gap-3">
                    <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${ACTIVITY_COLORS[a.color]}`}>
                      <Icon className="w-4 h-4" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="text-sm text-slate-800">
                        {a.text}
                      </div>

                      <div className="text-xs text-slate-500">
                        {a.time}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="rounded-2xl border border-slate-200 bg-gradient-to-br from-slate-900 to-indigo-950 p-5 text-white relative overflow-hidden">
            <div className="absolute inset-0 opacity-40" style={{ backgroundImage: 'radial-gradient(circle at 80% 20%, rgba(99,102,241,0.4), transparent 50%)' }} />

            <div className="relative">
              <Sparkles className="w-6 h-6 text-indigo-300" />

              <h3 className="mt-3 text-base font-semibold">
                Upgrade to Business
              </h3>

              <p className="mt-1 text-xs text-white/70 leading-relaxed">
                Unlock SSO, dedicated support and custom libraries.
              </p>

              <button className="mt-4 w-full py-2 rounded-lg bg-white text-slate-900 text-xs font-semibold">
                Talk to sales
              </button>
            </div>
          </section>
        </aside>
      </div>
    </main>
  </div>

  <CreateProjectModal
    isOpen={showNewProject}
    onClose={() => setShowNewProject(false)}
    onSuccess={handleProjectCreated}
  />
</div>
);
}

function StatCard({ label, value, delta, color, icon: Icon }) {

const colorClasses = {
indigo: 'bg-indigo-50 text-indigo-600',
violet: 'bg-violet-50 text-violet-600',
cyan: 'bg-cyan-50 text-cyan-600',
emerald: 'bg-emerald-50 text-emerald-600',
};

return ( <div className="rounded-2xl border border-slate-200 bg-white p-5"> <div className="flex items-center justify-between"> <span className="text-xs font-medium text-slate-500">
{label} </span>

```
    <div className={`w-7 h-7 rounded-lg flex items-center justify-center ${colorClasses[color]}`}>
      <Icon className="w-3.5 h-3.5" />
    </div>
  </div>

  <div className="mt-3 text-2xl font-semibold text-slate-900">
    {value}
  </div>

  <div className="mt-0.5 text-xs text-slate-500">
    {delta}
  </div>
</div>
```

);
}

function AppSidebar({ user, onLogout }) {

const items = [
{ icon: LayoutDashboard, label: 'Dashboard', to: '/app', active: true },
{ icon: FolderOpen, label: 'Projects', to: '/app' },
{ icon: Users, label: 'Team', to: '#' },
{ icon: Settings, label: 'Settings', to: '#' },
];

const initials =
user?.full_name
? user.full_name.split(' ').map(x => x[0]).slice(0, 2).join('')
: user?.email?.substring(0,2).toUpperCase() || 'U';

return ( <aside className="hidden lg:flex fixed top-0 left-0 h-screen w-64 flex-col border-r border-slate-200 bg-white z-40">

```
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

        <div className="text-[10px] text-slate-500 truncate">
          {user?.email}
        </div>
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
```

);
}
