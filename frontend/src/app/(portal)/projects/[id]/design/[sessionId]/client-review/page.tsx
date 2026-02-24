'use client';

import { useState } from 'react';
import { useParams } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { designApi, projectsApi } from '@/lib/api';
import { FloorPlanViewer } from '@/components/design/FloorPlanViewer';
import {
  CheckCircle2,
  RotateCcw,
  Download,
  FileText,
  Layers,
  Box,
  AlertCircle,
  Loader2,
  ShieldCheck,
  IndianRupee,
} from 'lucide-react';
import { cn, formatDate } from '@/lib/utils';
import { toast } from 'sonner';
import type { FloorPlan } from '@/types/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ClientApproval = {
  session_id: string;
  has_approval: boolean;
  action: string | null;
  notes: string | null;
  submitted_by: string | null;
  submitted_at: string | null;
};

type OutputFile = {
  name: string;
  type: string;
  download_url: string;
  size_bytes: number;
};

type CostEstimate = {
  material_grade: string;
  total_area_sqm: number;
  total_cost_inr: number;
  cost_per_sqm_inr: number;
  tier_comparison?: Record<string, number>;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const FILE_ICONS: Record<string, { icon: React.ComponentType<{ className?: string }>; label: string; color: string }> = {
  pdf:           { icon: FileText, label: 'PDF Package',    color: 'text-red-600' },
  dxf_floor_plan:{ icon: Layers,   label: 'Floor Plans',    color: 'text-blue-600' },
  dxf_elevation: { icon: Layers,   label: 'Elevations',     color: 'text-indigo-600' },
  dxf_3d:        { icon: Box,      label: '3D Drawing',     color: 'text-purple-600' },
  dxf_mep:       { icon: Layers,   label: 'MEP Drawings',   color: 'text-cyan-600' },
};

function fmtInr(val: number): string {
  const crore = val / 1_00_00_000;
  const lakh  = val / 1_00_000;
  if (crore >= 1) return `₹${crore.toFixed(2)} Cr`;
  return `₹${lakh.toFixed(2)} L`;
}

// ---------------------------------------------------------------------------
// File download card
// ---------------------------------------------------------------------------

function FileCard({ file }: { file: OutputFile }) {
  const cfg = FILE_ICONS[file.type] ?? { icon: FileText, label: file.type, color: 'text-gray-500' };
  const Icon = cfg.icon;
  return (
    <a
      href={file.download_url}
      download={file.name}
      className="flex items-center gap-3 p-3 bg-white border border-gray-200 rounded-xl hover:bg-gray-50 transition-colors group"
    >
      <Icon className={cn('w-5 h-5 shrink-0', cfg.color)} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-gray-800 truncate">{cfg.label}</p>
        <p className="text-xs text-gray-400">{(file.size_bytes / 1024).toFixed(0)} KB</p>
      </div>
      <Download className="w-4 h-4 text-gray-300 group-hover:text-blue-500 transition-colors shrink-0" />
    </a>
  );
}

// ---------------------------------------------------------------------------
// Approval status banner
// ---------------------------------------------------------------------------

function ApprovalBanner({ approval }: { approval: ClientApproval }) {
  if (!approval.has_approval) return null;

  const approved = approval.action === 'approved';
  return (
    <div className={cn(
      'flex items-start gap-3 rounded-xl p-4 border',
      approved
        ? 'bg-emerald-50 border-emerald-200'
        : 'bg-yellow-50 border-yellow-200',
    )}>
      {approved
        ? <ShieldCheck className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
        : <AlertCircle className="w-5 h-5 text-yellow-600 shrink-0 mt-0.5" />
      }
      <div>
        <p className={cn('text-sm font-semibold', approved ? 'text-emerald-800' : 'text-yellow-800')}>
          {approved ? 'Design approved by client' : 'Revision requested by client'}
        </p>
        {approval.submitted_at && (
          <p className="text-xs text-gray-500 mt-0.5">{formatDate(approval.submitted_at)}</p>
        )}
        {approval.notes && (
          <p className="text-sm text-gray-700 mt-1 italic">&ldquo;{approval.notes}&rdquo;</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Revision modal
// ---------------------------------------------------------------------------

function RevisionModal({
  onClose,
  onSubmit,
  submitting,
}: {
  onClose: () => void;
  onSubmit: (notes: string) => void;
  submitting: boolean;
}) {
  const [notes, setNotes] = useState('');
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <h2 className="text-lg font-semibold text-gray-900 mb-1">Request Revision</h2>
        <p className="text-sm text-gray-500 mb-4">
          Describe what you would like changed. The engineering team will review your feedback.
        </p>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={4}
          placeholder="e.g. Please move the master bedroom to face south, and increase the kitchen area…"
          className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none mb-4"
        />
        <div className="flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 rounded-lg hover:bg-gray-100 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onSubmit(notes)}
            disabled={!notes.trim() || submitting}
            className="px-4 py-2 bg-yellow-500 text-white rounded-lg text-sm font-medium hover:bg-yellow-600 disabled:opacity-50 transition-colors flex items-center gap-1.5"
          >
            {submitting && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Submit Feedback
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ClientReviewPage() {
  const { id, sessionId } = useParams<{ id: string; sessionId: string }>();
  const qc = useQueryClient();
  const [showReviseModal, setShowReviseModal] = useState(false);

  // Project info
  const { data: project } = useQuery({
    queryKey: ['project', id],
    queryFn: () => projectsApi.get(id) as Promise<{
      name: string;
      client_name: string;
      num_floors: number | null;
    }>,
  });

  // Session job (to get cost estimate from result)
  const { data: job } = useQuery({
    queryKey: ['job', id, sessionId],
    queryFn: () => designApi.getJob(id, sessionId),
  });

  // Output files
  const { data: files } = useQuery<OutputFile[]>({
    queryKey: ['session-files', id, sessionId],
    queryFn: () => designApi.getFiles(id, sessionId) as Promise<OutputFile[]>,
    enabled: !!job && ['completed', 'finalized'].includes((job as { status: string }).status),
  });

  // Decision events (for floor plans)
  const { data: decisions, isLoading: decisionsLoading } = useQuery({
    queryKey: ['decisions', id],
    queryFn: () => designApi.getDecisions(id),
  });

  // Client approval status
  const { data: approval, isLoading: approvalLoading } = useQuery<ClientApproval>({
    queryKey: ['client-approval', id, sessionId],
    queryFn: () => designApi.getClientApproval(id, sessionId) as Promise<ClientApproval>,
  });

  // Approval mutation
  const approveMutation = useMutation({
    mutationFn: ({ action, notes }: { action: 'approved' | 'revision_requested'; notes?: string }) =>
      designApi.clientApprove(id, sessionId, action, notes),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['client-approval', id, sessionId] });
      if (data.action === 'approved') {
        toast.success('Thank you! Your approval has been recorded.');
      } else {
        toast.info('Your feedback has been submitted to the engineering team.');
      }
      setShowReviseModal(false);
    },
    onError: () => {
      toast.error('Failed to submit. Please try again.');
    },
  });

  // Extract floor plans from decision events
  const floorPlans: FloorPlan[] = [];
  if (Array.isArray(decisions)) {
    const geoEvent = (decisions as Array<{ type: string; data: { floor_plans?: FloorPlan[] } }>)
      .find((e) => e.type === 'geometry_generated');
    if (geoEvent?.data?.floor_plans) {
      floorPlans.push(...geoEvent.data.floor_plans);
    }
  }

  // Cost estimate from job result
  const costEstimate: CostEstimate | null =
    (job as { result?: { cost_estimate?: CostEstimate } } | undefined)?.result?.cost_estimate ?? null;

  const isLoading = decisionsLoading || approvalLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  const alreadyActed = approval?.has_approval ?? false;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Design Review</h1>
        {project && (
          <p className="text-sm text-gray-500 mt-1">
            {project.name}
            {project.client_name ? ` · ${project.client_name}` : ''}
            {project.num_floors ? ` · ${project.num_floors} floor${project.num_floors !== 1 ? 's' : ''}` : ''}
          </p>
        )}
      </div>

      {/* Approval status banner */}
      {approval && <ApprovalBanner approval={approval} />}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Floor plan viewer — takes 2/3 */}
        <div className="lg:col-span-2">
          {floorPlans.length > 0 ? (
            <FloorPlanViewer floorPlans={floorPlans} complianceBadges={[]} />
          ) : (
            <div className="bg-gray-50 rounded-2xl border border-gray-200 p-12 text-center text-gray-400 text-sm h-64 flex items-center justify-center">
              Floor plan diagram not available
            </div>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-4">
          {/* Cost summary */}
          {costEstimate && (
            <div className="bg-white border border-gray-200 rounded-2xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <IndianRupee className="w-4 h-4 text-gray-500" />
                <h2 className="font-semibold text-gray-900 text-sm">Cost Estimate</h2>
              </div>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-500">Grade</span>
                  <span className="font-medium capitalize">{costEstimate.material_grade}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Total area</span>
                  <span className="font-medium">{costEstimate.total_area_sqm.toFixed(1)} sqm</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Rate / sqm</span>
                  <span className="font-medium">₹{costEstimate.cost_per_sqm_inr.toLocaleString()}</span>
                </div>
                <div className="border-t border-gray-100 pt-2 mt-2 flex justify-between">
                  <span className="font-semibold text-gray-900">Total</span>
                  <span className="font-bold text-blue-700 text-base">{fmtInr(costEstimate.total_cost_inr)}</span>
                </div>
              </div>
              {/* Tier comparison */}
              {costEstimate.tier_comparison && (
                <div className="mt-3 pt-3 border-t border-gray-100">
                  <p className="text-xs text-gray-400 mb-1.5">Grade comparison</p>
                  <div className="space-y-1">
                    {(['basic', 'standard', 'premium'] as const).map((g) => {
                      const val = costEstimate.tier_comparison?.[g];
                      if (val == null) return null;
                      const isCurrent = g === costEstimate.material_grade;
                      return (
                        <div
                          key={g}
                          className={cn(
                            'flex justify-between text-xs rounded-lg px-2 py-1',
                            isCurrent ? 'bg-blue-50 font-semibold text-blue-800' : 'text-gray-500',
                          )}
                        >
                          <span className="capitalize">{g}</span>
                          <span>{fmtInr(val)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* File downloads */}
          {files && files.length > 0 && (
            <div className="bg-white border border-gray-200 rounded-2xl p-4">
              <h2 className="font-semibold text-gray-900 text-sm mb-3">Download Files</h2>
              <div className="space-y-2">
                {/* Show PDF first, then others */}
                {[...files]
                  .sort((a, b) => (a.type === 'pdf' ? -1 : b.type === 'pdf' ? 1 : 0))
                  .map((f, i) => <FileCard key={i} file={f} />)
                }
              </div>
            </div>
          )}

          {/* Client action buttons */}
          <div className="bg-white border border-gray-200 rounded-2xl p-4">
            <h2 className="font-semibold text-gray-900 text-sm mb-3">Your Decision</h2>

            {alreadyActed ? (
              <p className="text-xs text-gray-500 text-center py-2">
                You have already submitted a response for this design.
                Contact the engineering team if you need to change your decision.
              </p>
            ) : (
              <div className="space-y-2.5">
                <button
                  onClick={() => approveMutation.mutate({ action: 'approved' })}
                  disabled={approveMutation.isPending}
                  className="w-full flex items-center justify-center gap-2 py-3 bg-emerald-600 text-white rounded-xl text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                >
                  {approveMutation.isPending && approveMutation.variables?.action === 'approved'
                    ? <Loader2 className="w-4 h-4 animate-spin" />
                    : <CheckCircle2 className="w-4 h-4" />
                  }
                  Approve Design
                </button>
                <button
                  onClick={() => setShowReviseModal(true)}
                  disabled={approveMutation.isPending}
                  className="w-full flex items-center justify-center gap-2 py-3 border border-yellow-300 text-yellow-700 bg-yellow-50 rounded-xl text-sm font-semibold hover:bg-yellow-100 disabled:opacity-50 transition-colors"
                >
                  <RotateCcw className="w-4 h-4" />
                  Request Changes
                </button>
                <p className="text-xs text-gray-400 text-center leading-relaxed">
                  Approving confirms you accept this design for construction. Requesting changes will
                  notify the engineering team to revise the design.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Revision modal */}
      {showReviseModal && (
        <RevisionModal
          onClose={() => setShowReviseModal(false)}
          onSubmit={(notes) => approveMutation.mutate({ action: 'revision_requested', notes })}
          submitting={approveMutation.isPending}
        />
      )}
    </div>
  );
}
