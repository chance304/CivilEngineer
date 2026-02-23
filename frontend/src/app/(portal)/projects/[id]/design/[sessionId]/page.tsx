'use client';

import { useParams, useRouter } from 'next/navigation';
import { useDesignJob } from '@/hooks/useDesignJob';
import { DesignProgress } from '@/components/common/DesignProgress';
import { useAppStore } from '@/store/useAppStore';
import { useEffect } from 'react';

export default function DesignJobPage() {
  const { id, sessionId } = useParams<{ id: string; sessionId: string }>();
  const router = useRouter();
  const { approvalRequest } = useAppStore();
  const { jobProgress } = useDesignJob(sessionId);

  // Redirect to review page when approval is needed
  useEffect(() => {
    if (approvalRequest?.type === 'floor_plan_review') {
      router.push(`/projects/${id}/design/${sessionId}/review`);
    }
  }, [approvalRequest, id, sessionId, router]);

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Generating Design</h1>
        <p className="text-gray-500 text-sm mt-1">
          Our AI pipeline is designing your building. This usually takes 1–3 minutes.
        </p>
      </div>
      <DesignProgress progress={jobProgress} />
    </div>
  );
}
