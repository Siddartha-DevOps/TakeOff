import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Loader2, FileText, FolderTree, Eye, MessageSquare } from 'lucide-react';
import { sharingAPI } from '../services/api';

// PUBLIC guest view — opened from a share link, no account required.
// Read-only project + sheet list (routes/sharing_routes.py GET /shared/{token}).

export default function SharedView() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    sharingAPI.resolve(token)
      .then((res) => setData(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'This share link is invalid or has expired.'))
      .finally(() => setLoading(false));
  }, [token]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 text-slate-400 gap-2">
        <Loader2 className="w-5 h-5 animate-spin" /> Opening shared project…
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 px-4">
        <div className="text-center">
          <div className="text-lg font-semibold text-slate-800">Link unavailable</div>
          <p className="mt-1 text-sm text-slate-500">{error}</p>
        </div>
      </div>
    );
  }

  const { project, sheets, role } = data;

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="h-14 bg-white border-b border-slate-200 flex items-center px-5 gap-3">
        <div className="w-7 h-7 rounded-lg bg-teal-500/10 flex items-center justify-center">
          <FolderTree className="w-4 h-4 text-teal-600" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-900 truncate">{project.name}</div>
          <div className="text-[11px] text-slate-400">Shared project · {sheets.length} sheet{sheets.length === 1 ? '' : 's'}</div>
        </div>
        <span className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-slate-500 bg-slate-100 px-2 py-1 rounded-full">
          {role === 'commenter' ? <MessageSquare className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
          {role === 'commenter' ? 'Can comment' : 'View only'}
        </span>
      </header>

      <main className="max-w-3xl mx-auto p-5">
        {project.description && <p className="text-sm text-slate-600 mb-4">{project.description}</p>}
        {sheets.length === 0 ? (
          <div className="text-sm text-slate-500">No sheets in this project yet.</div>
        ) : (
          <div className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100">
            {sheets.map((s) => (
              <div key={s.id} className="flex items-center gap-3 px-4 py-2.5">
                <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                {s.sheet_number && <span className="text-xs font-mono text-slate-500">{s.sheet_number}</span>}
                <span className="text-sm text-slate-800 truncate">{s.sheet_name}</span>
                {s.discipline && <span className="ml-auto text-[10px] uppercase font-semibold text-slate-400">{s.discipline}</span>}
              </div>
            ))}
          </div>
        )}
        <p className="mt-6 text-center text-[11px] text-slate-400">Shared via TakeOff.ai — you're viewing without an account.</p>
      </main>
    </div>
  );
}
