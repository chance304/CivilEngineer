'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { adminApi } from '@/lib/api';
import { BuildingCodeUpload } from '@/components/admin/BuildingCodeUpload';
import { RuleReviewTable } from '@/components/admin/RuleReviewTable';
import { formatDate } from '@/lib/utils';
import { cn } from '@/lib/utils';
import type { BuildingCodeDocument } from '@/types/api';

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-700',
  extracting: 'bg-blue-100 text-blue-700',
  needs_review: 'bg-orange-100 text-orange-700',
  active: 'bg-green-100 text-green-700',
};

export default function BuildingCodesPage() {
  const qc = useQueryClient();
  const [selectedDoc, setSelectedDoc] = useState<string | null>(null);

  const { data: docs, isLoading } = useQuery<BuildingCodeDocument[]>({
    queryKey: ['building-codes'],
    queryFn: () => adminApi.getBuildingCodes() as Promise<BuildingCodeDocument[]>,
  });

  const activateMut = useMutation({
    mutationFn: (docId: string) => adminApi.activateRules(docId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['building-codes'] });
      toast.success('Rules activated');
    },
  });

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Building Codes</h1>
          <p className="text-gray-500 text-sm mt-1">Upload jurisdiction PDFs, review extracted rules, and activate them.</p>
        </div>
        <BuildingCodeUpload />
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2].map((i) => <div key={i} className="h-16 bg-gray-100 rounded-xl animate-pulse" />)}
        </div>
      )}

      <div className="space-y-2 mb-6">
        {docs?.map((doc) => (
          <div
            key={doc.id}
            className={cn('bg-white rounded-xl border p-4 cursor-pointer hover:shadow-sm transition-shadow', selectedDoc === doc.id ? 'border-blue-400' : 'border-gray-200')}
            onClick={() => setSelectedDoc((prev) => prev === doc.id ? null : doc.id)}
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="font-medium text-gray-900 text-sm">{doc.title}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {doc.jurisdiction} · Uploaded {formatDate(doc.uploaded_at)} · {doc.rule_count} rules
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium', STATUS_STYLES[doc.status])}>
                  {doc.status}
                </span>
                {doc.status === 'needs_review' && (
                  <button
                    onClick={(e) => { e.stopPropagation(); activateMut.mutate(doc.id); }}
                    className="text-xs px-3 py-1 bg-green-600 text-white rounded-lg hover:bg-green-700"
                  >
                    Activate
                  </button>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {selectedDoc && (
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <h2 className="font-semibold text-gray-900 mb-4">Extracted Rules</h2>
          <RuleReviewTable docId={selectedDoc} />
        </div>
      )}
    </div>
  );
}
