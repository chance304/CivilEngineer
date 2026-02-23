'use client';

import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/api';
import { LLMConfigForm } from '@/components/admin/LLMConfigForm';
import type { LlmConfig } from '@/types/api';

export default function LlmConfigPage() {
  const { data: config, isLoading } = useQuery<LlmConfig>({
    queryKey: ['llm-config'],
    queryFn: () => adminApi.getLlmConfig() as Promise<LlmConfig>,
  });

  return (
    <div className="max-w-2xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">LLM Configuration</h1>
        <p className="text-gray-500 text-sm mt-1">
          Configure the AI model used by the design pipeline. Settings are stored per-firm.
        </p>
      </div>
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        {isLoading ? (
          <div className="space-y-4">
            {[1, 2, 3].map((i) => <div key={i} className="h-10 bg-gray-100 rounded-lg animate-pulse" />)}
          </div>
        ) : (
          <LLMConfigForm initialConfig={config ?? null} />
        )}
      </div>
    </div>
  );
}
