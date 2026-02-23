'use client';

import { formatArea } from '@/lib/utils';
import type { PlotInfo } from '@/types/api';

interface PlotPreviewProps {
  plotInfo: PlotInfo;
}

const FACING_LABEL: Record<string, string> = {
  north: 'North-facing', south: 'South-facing',
  east: 'East-facing', west: 'West-facing',
  northeast: 'North-East facing', northwest: 'North-West facing',
  southeast: 'South-East facing', southwest: 'South-West facing',
};

export function PlotPreview({ plotInfo }: PlotPreviewProps) {
  const { polygon, area_sqm, width_m, depth_m, facing, extraction_confidence } = plotInfo;

  // Compute SVG viewBox from polygon
  const hasPolygon = polygon.length > 2;
  const padding = 10;
  let minX = 0, minY = 0, maxX = width_m, maxY = depth_m;
  if (hasPolygon) {
    minX = Math.min(...polygon.map((p) => p.x));
    minY = Math.min(...polygon.map((p) => p.y));
    maxX = Math.max(...polygon.map((p) => p.x));
    maxY = Math.max(...polygon.map((p) => p.y));
  }

  const vbX = minX - padding;
  const vbY = minY - padding;
  const vbW = maxX - minX + padding * 2;
  const vbH = maxY - minY + padding * 2;

  const polyPoints = hasPolygon
    ? polygon.map((p) => `${p.x},${p.y}`).join(' ')
    : `0,0 ${width_m},0 ${width_m},${depth_m} 0,${depth_m}`;

  const confidencePct = Math.round(extraction_confidence * 100);
  const confidenceColor = confidencePct >= 90 ? 'text-green-600' : confidencePct >= 70 ? 'text-yellow-600' : 'text-red-600';

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-6">
      <h2 className="font-semibold text-gray-900 mb-4">Plot Analysis</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* SVG preview */}
        <div className="bg-gray-50 rounded-lg p-4">
          <svg viewBox={`${vbX} ${vbY} ${vbW} ${vbH}`} className="w-full h-48">
            <polygon
              points={polyPoints}
              fill="#EFF6FF"
              stroke="#2563EB"
              strokeWidth={0.5}
              strokeDasharray="0"
            />
            {/* North arrow */}
            <text x={minX} y={minY - 2} fontSize={4} fill="#6B7280">N ↑</text>
          </svg>
        </div>

        {/* Stats */}
        <div className="space-y-3">
          <Stat label="Plot area" value={formatArea(area_sqm)} />
          <Stat label="Width" value={`${width_m.toFixed(1)} m`} />
          <Stat label="Depth" value={`${depth_m.toFixed(1)} m`} />
          <Stat label="Facing" value={FACING_LABEL[facing] ?? facing} />
          {plotInfo.road_width_m && (
            <Stat label="Road width" value={`${plotInfo.road_width_m} m`} />
          )}
          <div className="flex justify-between items-center text-sm">
            <span className="text-gray-500">Extraction confidence</span>
            <span className={`font-semibold ${confidenceColor}`}>{confidencePct}%</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center text-sm">
      <span className="text-gray-500">{label}</span>
      <span className="font-semibold text-gray-900">{value}</span>
    </div>
  );
}
