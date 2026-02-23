'use client';

import { Check, Loader2, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { JobProgress } from '@/types/api';

const STEPS = [
  { key: 'loading', label: 'Loading project' },
  { key: 'interview', label: 'Requirements interview' },
  { key: 'planning', label: 'Planning & rules' },
  { key: 'solving', label: 'Space solving (OR-Tools)' },
  { key: 'geometry', label: 'Generating geometry' },
  { key: 'mep_routing', label: 'MEP routing' },
  { key: 'drawing', label: 'Drawing DXF + PDF' },
  { key: 'verifying', label: 'Compliance verification' },
];

interface DesignProgressProps {
  progress: JobProgress | null;
}

export function DesignProgress({ progress }: DesignProgressProps) {
  const currentStep = progress?.step ?? '';
  const currentIdx = STEPS.findIndex((s) => s.key === currentStep);
  const statusText = progress?.message ?? 'Initialising pipeline…';

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-6">
        <h2 className="font-semibold text-gray-900">Pipeline Progress</h2>
        {progress && (
          <span className="text-xs text-gray-400">
            Step {progress.step_index} of {progress.total_steps}
          </span>
        )}
      </div>

      {/* Steps timeline */}
      <div className="space-y-3">
        {STEPS.map((step, i) => {
          const done = currentIdx > i || progress?.status === 'completed';
          const active = currentIdx === i && progress?.status === 'running';
          const failed = progress?.status === 'failed' && currentIdx === i;

          return (
            <div key={step.key} className="flex items-center gap-3">
              <div className={cn(
                'w-7 h-7 rounded-full flex items-center justify-center shrink-0 border-2 transition-all',
                done && 'bg-green-500 border-green-500',
                active && 'bg-white border-blue-500',
                failed && 'bg-red-500 border-red-500',
                !done && !active && !failed && 'bg-white border-gray-200'
              )}>
                {done && <Check className="w-4 h-4 text-white" />}
                {active && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />}
                {failed && <AlertCircle className="w-4 h-4 text-white" />}
                {!done && !active && !failed && (
                  <span className="text-xs text-gray-300 font-medium">{i + 1}</span>
                )}
              </div>
              <div className="flex-1">
                <span className={cn(
                  'text-sm',
                  done && 'text-gray-500 line-through',
                  active && 'text-gray-900 font-medium',
                  !done && !active && 'text-gray-400'
                )}>
                  {step.label}
                </span>
                {active && statusText && (
                  <p className="text-xs text-blue-500 mt-0.5">{statusText}</p>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {progress?.status === 'completed' && (
        <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">
          Design complete! Redirecting to review…
        </div>
      )}
      {progress?.status === 'failed' && (
        <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          Pipeline failed: {statusText}
        </div>
      )}
      {progress?.status === 'waiting_approval' && (
        <div className="mt-4 p-3 bg-blue-50 border border-blue-200 rounded-lg text-blue-700 text-sm">
          Waiting for your review — redirecting to approval page…
        </div>
      )}
    </div>
  );
}
