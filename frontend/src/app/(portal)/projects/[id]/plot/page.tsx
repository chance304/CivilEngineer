'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { PlotUpload } from '@/components/project/PlotUpload';
import { PlotPreview } from '@/components/project/PlotPreview';
import type { PlotInfo } from '@/types/api';

export default function PlotPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [plotInfo, setPlotInfo] = useState<PlotInfo | null>(null);

  return (
    <div className="max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Upload Plot Drawing</h1>
        <p className="text-gray-500 text-sm mt-1">
          Upload a DWG or DXF file of your plot. We&apos;ll extract the boundary and calculate setbacks automatically.
        </p>
      </div>

      {!plotInfo ? (
        <PlotUpload projectId={id} onAnalysed={setPlotInfo} />
      ) : (
        <div className="space-y-6">
          <PlotPreview plotInfo={plotInfo} />
          <div className="flex justify-end">
            <button
              onClick={() => router.push(`/projects/${id}/interview`)}
              className="px-6 py-2.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
            >
              Start Design Interview
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
