const ACTION_PRESENTATION = {
  login: { text: 'Signed in', icon: 'LogIn', color: 'indigo' },
  'share.created': { text: 'Created a project share link', icon: 'Share2', color: 'emerald' },
  'sso.configured': { text: 'Updated single sign-on settings', icon: 'ShieldCheck', color: 'violet' },
};

export function buildDashboardStats(projects = [], usage = null) {
  const safeProjects = Array.isArray(projects) ? projects : [];
  const activeProjects = safeProjects.filter((project) => project.status === 'active').length;
  const drawings = safeProjects.reduce(
    (total, project) => total + (Number(project.sheets_count) || 0),
    0,
  );

  return {
    activeProjects,
    totalProjects: safeProjects.length,
    drawings,
    projectsThisMonth: usage?.projects?.used ?? null,
    aiTakeoffsThisMonth: usage?.ai_takeoffs?.used ?? null,
  };
}

export function relativeTime(value, now = Date.now()) {
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return 'Recently';

  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(timestamp).toLocaleDateString();
}

export function presentActivity(activity, now = Date.now()) {
  const fallbackAction = String(activity?.action || 'activity').replaceAll('.', ' ');
  const presentation = ACTION_PRESENTATION[activity?.action] || {
    text: fallbackAction.charAt(0).toUpperCase() + fallbackAction.slice(1),
    icon: 'Activity',
    color: 'cyan',
  };

  return {
    ...presentation,
    id: activity?.id,
    time: relativeTime(activity?.created_at, now),
  };
}
