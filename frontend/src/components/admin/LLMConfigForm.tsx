'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { toast } from 'sonner';
import { adminApi } from '@/lib/api';
import { Loader2, CheckCircle } from 'lucide-react';
import { useState } from 'react';
import type { LlmConfig } from '@/types/api';

const schema = z.object({
  provider: z.enum(['anthropic', 'openai', 'azure', 'ollama', 'custom']),
  model_name: z.string().min(1, 'Model name is required'),
  base_url: z.string().url().optional().or(z.literal('')),
  api_key: z.string().optional(),
  temperature: z.coerce.number().min(0).max(2).default(0.2),
  max_tokens: z.coerce.number().int().min(256).max(131072).default(8192),
});

type FormData = z.infer<typeof schema>;

interface LLMConfigFormProps {
  initialConfig: LlmConfig | null;
}

const PROVIDERS = [
  { value: 'anthropic', label: 'Anthropic (Claude)' },
  { value: 'openai', label: 'OpenAI (GPT)' },
  { value: 'azure', label: 'Azure OpenAI' },
  { value: 'ollama', label: 'Ollama (local)' },
  { value: 'custom', label: 'Custom (LiteLLM)' },
];

const DEFAULT_MODELS: Record<string, string> = {
  anthropic: 'claude-sonnet-4-6',
  openai: 'gpt-4o',
  azure: 'gpt-4o',
  ollama: 'llama3.1',
  custom: '',
};

export function LLMConfigForm({ initialConfig }: LLMConfigFormProps) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const { register, handleSubmit, watch, setValue, formState: { errors, isSubmitting } } = useForm<FormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      provider: (initialConfig?.provider as FormData['provider']) ?? 'anthropic',
      model_name: initialConfig?.model_name ?? 'claude-sonnet-4-6',
      base_url: initialConfig?.base_url ?? '',
      temperature: initialConfig?.temperature ?? 0.2,
      max_tokens: initialConfig?.max_tokens ?? 8192,
    },
  });

  const provider = watch('provider');

  function onProviderChange(e: React.ChangeEvent<HTMLSelectElement>) {
    const p = e.target.value as FormData['provider'];
    setValue('provider', p);
    if (DEFAULT_MODELS[p]) setValue('model_name', DEFAULT_MODELS[p]);
  }

  async function onSubmit(data: FormData) {
    try {
      await adminApi.updateLlmConfig(data);
      toast.success('LLM configuration saved');
      setTestResult(null);
    } catch {
      toast.error('Failed to save configuration');
    }
  }

  async function testConnection() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await adminApi.testLlmConnection();
      setTestResult(result);
      if (result.ok) toast.success('Connection successful');
      else toast.error(`Connection failed: ${result.message}`);
    } catch {
      toast.error('Test request failed');
    } finally {
      setTesting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-5">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Provider</label>
          <select {...register('provider')} onChange={onProviderChange} className={inputClass}>
            {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Model name</label>
          <input {...register('model_name')} placeholder="e.g. claude-sonnet-4-6" className={inputClass} />
          {errors.model_name && <p className="text-red-500 text-xs mt-1">{errors.model_name.message}</p>}
        </div>
      </div>

      {(provider === 'azure' || provider === 'ollama' || provider === 'custom') && (
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Base URL</label>
          <input {...register('base_url')} placeholder="https://..." className={inputClass} />
          {errors.base_url && <p className="text-red-500 text-xs mt-1">{errors.base_url.message}</p>}
        </div>
      )}

      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">
          API Key {initialConfig?.api_key_set && <span className="text-green-600">(currently set)</span>}
        </label>
        <input
          {...register('api_key')}
          type="password"
          placeholder={initialConfig?.api_key_set ? '••••••• (leave blank to keep)' : 'sk-…'}
          className={inputClass}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Temperature (0–2)</label>
          <input {...register('temperature')} type="number" step="0.1" min={0} max={2} className={inputClass} />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">Max tokens</label>
          <input {...register('max_tokens')} type="number" min={256} max={131072} className={inputClass} />
        </div>
      </div>

      {testResult && (
        <div className={`flex items-center gap-2 p-3 rounded-lg border text-sm ${testResult.ok ? 'bg-green-50 border-green-200 text-green-700' : 'bg-red-50 border-red-200 text-red-700'}`}>
          <CheckCircle className="w-4 h-4 shrink-0" />
          {testResult.message}
        </div>
      )}

      <div className="flex gap-3 pt-2">
        <button
          type="button"
          onClick={testConnection}
          disabled={testing}
          className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : null}
          Test Connection
        </button>
        <button
          type="submit"
          disabled={isSubmitting}
          className="px-5 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {isSubmitting ? 'Saving…' : 'Save Configuration'}
        </button>
      </div>
    </form>
  );
}

const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
