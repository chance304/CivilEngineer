'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { designApi } from '@/lib/api';
import { FloorPlanViewer } from '@/components/design/FloorPlanViewer';
import { ComplianceReport } from '@/components/common/ComplianceReport';
import { CheckCircle, RotateCcw, XCircle, Loader2 } from 'lucide-react';
import type { FloorPlan, ComplianceReport as ComplianceReportType } from '@/types/api';

export default function ReviewPage() {
  const { id, sessionId } = useParams<{ id: string; sessionId: string }>();
  const router = useRouter();
  const [reviseNotes, setReviseNotes] = useState('');
  const [showReviseModal, setShowReviseModal] = useState(false);
  const [acting, setActing] = useState(false);

  const { data: decisions, isLoading } = useQuery({
    queryKey: ['decisions', id],
    queryFn: () => designApi.getDecisions(id),
  });

  const { data: reports } = useQuery<ComplianceReportType[]>({
    queryKey: ['compliance', id],
    queryFn: () => designApi.getComplianceReports(id) as Promise<ComplianceReportType[]>,
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

  const latestReport = reports?.[0] ?? null;

  async function act(action: 'approve' | 'revise' | 'abort', notes?: string) {
    setActing(true);
    try {
      await designApi.approve(id, sessionId, action, notes);
      if (action === 'approve') {
        toast.success('Design approved! Generating output files…');
        router.push(`/projects/${id}/files`);
      } else if (action === 'revise') {
        toast.info('Revision requested. Redesigning…');
        router.push(`/projects/${id}/design/${sessionId}`);
      } else {
        toast.info('Design session aborted.');
        router.push('/dashboard');
      }
    } catch {
      toast.error('Action failed. Please try again.');
    } finally {
      setActing(false);
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
      </div>
    );
  }

  return (
    <div className="flex gap-6 h-full">
      {/* Left: floor plan */}
      <div className="flex-1 min-w-0">
        <h1 className="text-xl font-bold text-gray-900 mb-4">Review Design</h1>
        {floorPlans.length > 0 ? (
          <FloorPlanViewer
            floorPlans={floorPlans}
            complianceBadges={latestReport ? [
              { label: 'Vastu', ok: (latestReport.vastu_score ?? 0) >= 7 },
              { label: 'FAR', ok: latestReport.far_actual <= latestReport.far_limit },
              { label: 'Compliance', ok: latestReport.passed },
            ] : []}
          />
        ) : (
          <div className="bg-gray-50 rounded-xl border border-gray-200 p-12 text-center text-gray-400 text-sm">
            Floor plan data not yet available
          </div>
        )}
      </div>

      {/* Right: summary + actions */}
      <div className="w-80 shrink-0 space-y-4">
        {/* Action buttons */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
          <h2 className="font-semibold text-gray-900 text-sm">Engineer Decision</h2>
          <button
            onClick={() => act('approve')}
            disabled={acting}
            className="w-full flex items-center justify-center gap-2 py-2.5 bg-green-600 text-white rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50"
          >
            <CheckCircle className="w-4 h-4" /> Approve Design
          </button>
          <button
            onClick={() => setShowReviseModal(true)}
            disabled={acting}
            className="w-full flex items-center justify-center gap-2 py-2.5 border border-yellow-300 text-yellow-700 rounded-lg text-sm font-medium hover:bg-yellow-50 disabled:opacity-50"
          >
            <RotateCcw className="w-4 h-4" /> Request Revision
          </button>
          <button
            onClick={() => act('abort')}
            disabled={acting}
            className="w-full flex items-center justify-center gap-2 py-2.5 border border-red-200 text-red-600 rounded-lg text-sm font-medium hover:bg-red-50 disabled:opacity-50"
          >
            <XCircle className="w-4 h-4" /> Abort Session
          </button>
        </div>

        {/* Compliance report */}
        {latestReport && (
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h2 className="font-semibold text-gray-900 text-sm mb-3">Compliance Report</h2>
            <ComplianceReport report={latestReport} />
          </div>
        )}
      </div>

      {/* Revise modal */}
      {showReviseModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="font-semibold text-gray-900 mb-3">Request Revision</h2>
            <p className="text-sm text-gray-500 mb-4">
              Describe what should be changed. The pipeline will re-run with your notes.
            </p>
            <textarea
              value={reviseNotes}
              onChange={(e) => setReviseNotes(e.target.value)}
              rows={4}
              placeholder="e.g. Move master bedroom to south-facing wall, increase kitchen area…"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 mb-4"
            />
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowReviseModal(false)} className="text-sm text-gray-500 hover:text-gray-800 px-3 py-1.5">
                Cancel
              </button>
              <button
                onClick={() => { setShowReviseModal(false); act('revise', reviseNotes); }}
                disabled={!reviseNotes.trim() || acting}
                className="px-4 py-1.5 bg-yellow-500 text-white rounded-lg text-sm font-medium hover:bg-yellow-600 disabled:opacity-50"
              >
                Submit Revision
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
