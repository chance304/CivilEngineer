'use client';

import { useEffect } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { wsManager } from '@/lib/websocket';
import type { JobProgress } from '@/types/api';

export function useDesignJob(sessionId: string | null) {
  const { accessToken, setJobProgress, setApprovalRequest, jobProgress } = useAppStore();

  useEffect(() => {
    if (!sessionId || !accessToken) return;

    wsManager.connect(sessionId, accessToken);

    const unsubProgress = wsManager.on('design.progress', (data) => {
      setJobProgress(data as JobProgress);
    });

    const unsubApproval = wsManager.on('design.approval_required', (data) => {
      const req = data as { type: string; prompt: string };
      setApprovalRequest({
        session_id: sessionId,
        project_id: '',
        prompt: req.prompt ?? 'Please review the floor plan.',
        type: req.type as 'floor_plan_review' | 'interview',
      });
    });

    return () => {
      unsubProgress();
      unsubApproval();
      wsManager.disconnect();
    };
  }, [sessionId, accessToken]);

  return { jobProgress };
}
