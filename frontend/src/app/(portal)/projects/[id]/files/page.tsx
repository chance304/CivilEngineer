'use client';

import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { designApi } from '@/lib/api';
import { Download, FileType, Layers, Box, FileText } from 'lucide-react';
import { cn, formatDate } from '@/lib/utils';
import type { DesignSession, OutputFile } from '@/types/api';

const FILE_TYPE_CONFIG: Record<string, { icon: React.ComponentType<{ className?: string }>; label: string; color: string }> = {
  dxf_floor_plan: { icon: Layers, label: 'Floor Plan DXF', color: 'text-blue-600' },
  dxf_elevation: { icon: Layers, label: 'Elevation DXF', color: 'text-indigo-600' },
  dxf_3d: { icon: Box, label: '3D DXF', color: 'text-purple-600' },
  dxf_mep: { icon: Layers, label: 'MEP DXF', color: 'text-cyan-600' },
  pdf: { icon: FileText, label: 'PDF Package', color: 'text-red-600' },
  ifc: { icon: Box, label: 'IFC (BIM)', color: 'text-green-600' },
  dwg: { icon: FileType, label: 'DWG', color: 'text-orange-600' },
};

const STATUS_STYLES: Record<string, string> = {
  completed: 'bg-green-100 text-green-700',
  running: 'bg-blue-100 text-blue-700',
  failed: 'bg-red-100 text-red-600',
  pending: 'bg-gray-100 text-gray-600',
  waiting_approval: 'bg-yellow-100 text-yellow-700',
};

function FileBadge({ file }: { file: OutputFile }) {
  const cfg = FILE_TYPE_CONFIG[file.type] ?? { icon: FileText, label: file.type, color: 'text-gray-500' };
  const Icon = cfg.icon;
  const kb = (file.size_bytes / 1024).toFixed(0);
  return (
    <a
      href={file.download_url}
      download
      className="flex items-center gap-2 px-3 py-2 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors group"
    >
      <Icon className={cn('w-4 h-4 shrink-0', cfg.color)} />
      <div className="min-w-0">
        <p className="text-xs font-medium text-gray-700 truncate">{cfg.label}</p>
        <p className="text-xs text-gray-400">{kb} KB</p>
      </div>
      <Download className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500 ml-auto shrink-0 transition-colors" />
    </a>
  );
}

export default function FilesPage() {
  const { id } = useParams<{ id: string }>();

  // Fetch sessions (using decisions endpoint to find sessions)
  const { data: sessions, isLoading } = useQuery<DesignSession[]>({
    queryKey: ['sessions', id],
    queryFn: async () => {
      // In practice this would be GET /projects/{id}/sessions
      // Using decisions as a proxy for now
      return [] as DesignSession[];
    },
  });

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Output Files</h1>

      {isLoading && (
        <div className="space-y-4">
          {[1, 2].map((i) => <div key={i} className="h-32 bg-gray-100 rounded-xl animate-pulse" />)}
        </div>
      )}

      {sessions?.length === 0 && !isLoading && (
        <div className="text-center py-16 text-gray-400 text-sm">
          No completed design sessions yet.
        </div>
      )}

      <div className="space-y-4">
        {sessions?.map((session) => (
          <div key={session.id} className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <p className="text-sm font-semibold text-gray-900">
                  Session {session.id.slice(0, 8)}
                </p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {session.completed_at ? formatDate(session.completed_at) : formatDate(session.created_at)}
                </p>
              </div>
              <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium', STATUS_STYLES[session.status] ?? STATUS_STYLES.pending)}>
                {session.status}
              </span>
            </div>
            {session.output_files.length > 0 ? (
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {session.output_files.map((f, i) => (
                  <FileBadge key={i} file={f} />
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400">No files available yet.</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
