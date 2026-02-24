'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { adminApi } from '@/lib/api';
import { Check, X, ChevronDown, ChevronUp, ShieldCheck, AlertTriangle, HelpCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ExtractedRule } from '@/types/api';

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-700',
  approved: 'bg-green-100 text-green-700',
  rejected: 'bg-red-100 text-red-600',
};

function VerificationBadge({ status, notes }: { status?: string; notes?: string }) {
  if (!status || status === 'pending') {
    return <span className="text-xs text-gray-400">—</span>;
  }
  if (status === 'verified') {
    return (
      <span className="flex items-center gap-1 text-xs text-green-700">
        <ShieldCheck className="w-3 h-3" /> verified
      </span>
    );
  }
  if (status === 'flagged') {
    return (
      <span className="flex items-center gap-1 text-xs text-red-600" title={notes ?? ''}>
        <AlertTriangle className="w-3 h-3" /> flagged
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 text-xs text-gray-500" title={notes ?? ''}>
      <HelpCircle className="w-3 h-3" /> unverifiable
    </span>
  );
}

const CONFIDENCE_COLOR = (c: number) =>
  c >= 0.9 ? 'text-green-600' : c >= 0.7 ? 'text-yellow-600' : 'text-red-500';

interface RuleReviewTableProps {
  docId: string;
}

export function RuleReviewTable({ docId }: RuleReviewTableProps) {
  const qc = useQueryClient();
  const [sortCol, setSortCol] = useState<keyof ExtractedRule>('category');
  const [sortAsc, setSortAsc] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const { data: rules, isLoading } = useQuery<ExtractedRule[]>({
    queryKey: ['rules', docId],
    queryFn: () => adminApi.getExtractedRules(docId) as Promise<ExtractedRule[]>,
  });

  const approveMut = useMutation({
    mutationFn: (ruleId: string) => adminApi.approveRule(docId, ruleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rules', docId] }),
  });

  const rejectMut = useMutation({
    mutationFn: (ruleId: string) => adminApi.rejectRule(docId, ruleId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rules', docId] }),
  });

  async function bulkApprove() {
    for (const id of selected) {
      await approveMut.mutateAsync(id);
    }
    setSelected(new Set());
    toast.success(`${selected.size} rules approved`);
  }

  function toggleSort(col: keyof ExtractedRule) {
    if (col === sortCol) setSortAsc((a) => !a);
    else { setSortCol(col); setSortAsc(true); }
  }

  const sorted = [...(rules ?? [])].sort((a, b) => {
    const av = a[sortCol] as string | number;
    const bv = b[sortCol] as string | number;
    const cmp = String(av).localeCompare(String(bv));
    return sortAsc ? cmp : -cmp;
  });

  function SortIcon({ col }: { col: keyof ExtractedRule }) {
    if (col !== sortCol) return null;
    return sortAsc ? <ChevronUp className="w-3 h-3 inline" /> : <ChevronDown className="w-3 h-3 inline" />;
  }

  if (isLoading) return <div className="h-48 bg-gray-50 rounded-xl animate-pulse" />;

  return (
    <div>
      {selected.size > 0 && (
        <div className="flex items-center gap-3 mb-3 p-3 bg-blue-50 rounded-lg">
          <span className="text-sm text-blue-700">{selected.size} selected</span>
          <button onClick={bulkApprove} className="text-sm px-3 py-1 bg-green-600 text-white rounded-lg hover:bg-green-700">
            Approve all
          </button>
          <button onClick={() => setSelected(new Set())} className="text-sm text-gray-500 hover:text-gray-800">
            Clear
          </button>
        </div>
      )}

      <div className="overflow-x-auto rounded-xl border border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-3 py-2.5 w-8">
                <input type="checkbox" className="rounded"
                  onChange={(e) => setSelected(e.target.checked ? new Set(sorted.map((r) => r.id)) : new Set())} />
              </th>
              {(['category', 'rule_id', 'value', 'unit', 'confidence', 'status'] as (keyof ExtractedRule)[]).map((col) => (
                <th key={col} onClick={() => toggleSort(col)} className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600 cursor-pointer hover:text-gray-900 select-none">
                  {col} <SortIcon col={col} />
                </th>
              ))}
              <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-600">AI check</th>
              <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-600">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map((rule) => (
              <tr key={rule.id} className="hover:bg-gray-50">
                <td className="px-3 py-2">
                  <input type="checkbox" className="rounded"
                    checked={selected.has(rule.id)}
                    onChange={(e) => setSelected((prev) => { const s = new Set(prev); e.target.checked ? s.add(rule.id) : s.delete(rule.id); return s; })} />
                </td>
                <td className="px-3 py-2 text-gray-700">{rule.category}</td>
                <td className="px-3 py-2 font-mono text-xs text-gray-500">{rule.rule_id}</td>
                <td className="px-3 py-2 font-semibold">{String(rule.value)}</td>
                <td className="px-3 py-2 text-gray-500">{rule.unit ?? '—'}</td>
                <td className="px-3 py-2">
                  <span className={cn(CONFIDENCE_COLOR(rule.confidence), 'font-medium')}>
                    {(rule.confidence * 100).toFixed(0)}%
                  </span>
                </td>
                <td className="px-3 py-2">
                  <span className={cn('text-xs px-1.5 py-0.5 rounded-full font-medium', STATUS_STYLES[rule.status] ?? '')}>
                    {rule.status}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <VerificationBadge
                    status={(rule as unknown as { verification_status?: string }).verification_status}
                    notes={(rule as unknown as { verification_notes?: string }).verification_notes}
                  />
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="flex justify-end gap-1">
                    {rule.status !== 'approved' && (
                      <button onClick={() => approveMut.mutate(rule.id)} className="w-6 h-6 flex items-center justify-center rounded-lg bg-green-100 hover:bg-green-200 text-green-700">
                        <Check className="w-3 h-3" />
                      </button>
                    )}
                    {rule.status !== 'rejected' && (
                      <button onClick={() => rejectMut.mutate(rule.id)} className="w-6 h-6 flex items-center justify-center rounded-lg bg-red-100 hover:bg-red-200 text-red-600">
                        <X className="w-3 h-3" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
