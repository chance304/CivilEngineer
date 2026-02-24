'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { designApi } from '@/lib/api';
import { Download, FileType, Layers, Box, FileText, ChevronDown, ChevronRight, Archive, ShieldCheck, AlertCircle, Eye } from 'lucide-react';
import Link from 'next/link';
import { cn, formatDate } from '@/lib/utils';
import { toast } from 'sonner';

type JobSummary = {
  job_id: string;
  session_id: string;
  status: string;
  current_step: string;
  submitted_at: string;
  completed_at: string | null;
};

type OutputFile = {
  name: string;
  type: string;
  download_url: string;
  size_bytes: number;
};

const FILE_TYPE_CONFIG: Record<string, { icon: React.ComponentType<{ className?: string }>; label: string; color: string }> = {
  dxf_floor_plan: { icon: Layers,    label: 'Floor Plan DXF', color: 'text-blue-600' },
  dxf_elevation:  { icon: Layers,    label: 'Elevation DXF',  color: 'text-indigo-600' },
  dxf_3d:         { icon: Box,       label: '3D DXF',         color: 'text-purple-600' },
  dxf_mep:        { icon: Layers,    label: 'MEP DXF',        color: 'text-cyan-600' },
  pdf:            { icon: FileText,  label: 'PDF Package',    color: 'text-red-600' },
  ifc:            { icon: Box,       label: 'IFC (BIM)',      color: 'text-green-600' },
  dwg:            { icon: FileType,  label: 'DWG',            color: 'text-orange-600' },
};

const STATUS_STYLES: Record<string, string> = {
  completed:        'bg-green-100 text-green-700',
  finalized:        'bg-emerald-100 text-emerald-700',
  running:          'bg-blue-100 text-blue-700',
  failed:           'bg-red-100 text-red-600',
  pending:          'bg-gray-100 text-gray-600',
  waiting_approval: 'bg-yellow-100 text-yellow-700',
  paused:           'bg-yellow-100 text-yellow-700',
  cancelled:        'bg-gray-100 text-gray-500',
};

function FileBadge({ file }: { file: OutputFile }) {
  const cfg = FILE_TYPE_CONFIG[file.type] ?? { icon: FileText, label: file.type, color: 'text-gray-500' };
  const Icon = cfg.icon;
  const kb = (file.size_bytes / 1024).toFixed(0);
  return (
    <a
      href={file.download_url}
      download={file.name}
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

function SessionFilesPanel({ projectId, sessionId }: { projectId: string; sessionId: string }) {
  const { data: files, isLoading } = useQuery<OutputFile[]>({
    queryKey: ['session-files', projectId, sessionId],
    queryFn: () => designApi.getFiles(projectId, sessionId) as Promise<OutputFile[]>,
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 bg-gray-100 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (!files || files.length === 0) {
    return <p className="text-xs text-gray-400 mt-3">No files available yet.</p>;
  }

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 mt-3">
      {files.map((f, i) => <FileBadge key={i} file={f} />)}
    </div>
  );
}

function SessionCard({ job, projectId }: { job: JobSummary; projectId: string }) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [zipping, setZipping] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [completenessReport, setCompletenessReport] = useState<null | {
    missing_required: string[];
    missing_advisory: string[];
    present: Record<string, boolean>;
  }>(null);

  const isCompleted  = job.status === 'completed';
  const isFinalized  = job.status === 'finalized';
  const showFiles    = isCompleted || isFinalized;

  async function handleZipDownload() {
    setZipping(true);
    try {
      await designApi.downloadZip(projectId, job.session_id);
    } catch {
      toast.error('Download failed');
    } finally {
      setZipping(false);
    }
  }

  async function handleFinalize() {
    setFinalizing(true);
    setCompletenessReport(null);
    try {
      const res = await designApi.finalize(projectId, job.session_id);
      toast.success('Session finalized successfully');
      setCompletenessReport(res.completeness);
      qc.invalidateQueries({ queryKey: ['design-sessions', projectId] });
    } catch (err: unknown) {
      const body = (err as { body?: { missing_required?: string[]; missing_advisory?: string[]; present?: Record<string, boolean> } })?.body;
      if (body?.missing_required) {
        setCompletenessReport({
          missing_required: body.missing_required,
          missing_advisory: body.missing_advisory ?? [],
          present: body.present ?? {},
        });
        toast.error(`Missing required files: ${body.missing_required.join(', ')}`);
      } else {
        toast.error('Finalization failed');
      }
    } finally {
      setFinalizing(false);
    }
  }

  return (
    <div className={cn(
      'bg-white rounded-xl border p-5',
      isFinalized ? 'border-emerald-300' : 'border-gray-200',
    )}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {showFiles && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-gray-400 hover:text-gray-700 transition-colors"
              aria-label={expanded ? 'Collapse files' : 'Expand files'}
            >
              {expanded
                ? <ChevronDown className="w-4 h-4" />
                : <ChevronRight className="w-4 h-4" />}
            </button>
          )}
          <div>
            <p className="text-sm font-semibold text-gray-900 flex items-center gap-1.5">
              Session {job.session_id.slice(0, 8)}
              {isFinalized && <ShieldCheck className="w-3.5 h-3.5 text-emerald-600" />}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">
              {job.completed_at ? formatDate(job.completed_at) : formatDate(job.submitted_at)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium', STATUS_STYLES[job.status] ?? STATUS_STYLES.pending)}>
            {job.status}
          </span>
          {showFiles && (
            <button
              onClick={handleZipDownload}
              disabled={zipping}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-xs font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              <Archive className="w-3.5 h-3.5" />
              {zipping ? 'Downloading…' : 'Download All'}
            </button>
          )}
          {isCompleted && (
            <button
              onClick={handleFinalize}
              disabled={finalizing}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 text-white rounded-lg text-xs font-medium hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              {finalizing ? 'Checking…' : 'Finalize'}
            </button>
          )}
          {showFiles && (
            <Link
              href={`/projects/${projectId}/design/${job.session_id}/client-review`}
              className="flex items-center gap-1.5 px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg text-xs font-medium hover:bg-gray-50 transition-colors"
            >
              <Eye className="w-3.5 h-3.5" />
              Client View
            </Link>
          )}
        </div>
      </div>

      {/* Completeness report (shown after finalize attempt) */}
      {completenessReport && (
        <div className="mt-3 rounded-lg border border-gray-100 bg-gray-50 p-3 space-y-2">
          <p className="text-xs font-semibold text-gray-700">Documentation Completeness</p>
          <div className="grid grid-cols-2 gap-1">
            {Object.entries(completenessReport.present).map(([key, present]) => (
              <div key={key} className="flex items-center gap-1.5">
                <span className={cn('w-1.5 h-1.5 rounded-full shrink-0', present ? 'bg-green-500' : 'bg-red-400')} />
                <span className="text-xs text-gray-600">{key.replace(/_/g, ' ')}</span>
              </div>
            ))}
          </div>
          {completenessReport.missing_advisory.length > 0 && (
            <div className="flex items-start gap-1.5 pt-1">
              <AlertCircle className="w-3.5 h-3.5 text-yellow-500 shrink-0 mt-0.5" />
              <p className="text-xs text-yellow-700">
                Advisory: {completenessReport.missing_advisory.join('; ')}
              </p>
            </div>
          )}
        </div>
      )}

      {showFiles && expanded && (
        <SessionFilesPanel projectId={projectId} sessionId={job.session_id} />
      )}
    </div>
  );
}

export default function FilesPage() {
  const { id } = useParams<{ id: string }>();

  const { data: sessions, isLoading } = useQuery<JobSummary[]>({
    queryKey: ['design-sessions', id],
    queryFn: () => designApi.list(id) as Promise<JobSummary[]>,
  });

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Output Files</h1>

      {isLoading && (
        <div className="space-y-4">
          {[1, 2].map((i) => <div key={i} className="h-20 bg-gray-100 rounded-xl animate-pulse" />)}
        </div>
      )}

      {!isLoading && (!sessions || sessions.length === 0) && (
        <div className="text-center py-16 text-gray-400 text-sm">
          No design sessions yet.
        </div>
      )}

      <div className="space-y-4">
        {sessions?.map((job) => (
          <SessionCard key={job.session_id} job={job} projectId={id} />
        ))}
      </div>
    </div>
  );
}
