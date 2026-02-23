'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';
import type { ElevationView, ElevationOpening } from '@/types/api';

interface ElevationViewerProps {
  elevations: ElevationView[];
}

const DIR_LABELS: Record<string, string> = {
  front: 'Front', rear: 'Rear', left: 'Left', right: 'Right',
};

export function ElevationViewer({ elevations }: ElevationViewerProps) {
  const [active, setActive] = useState(0);

  const ev = elevations[active];
  if (!ev) return null;

  const pad = 0.5;
  const vbW = ev.width_m + pad * 2;
  const vbH = ev.height_m + pad * 2;
  const vbStr = `${-pad} ${-pad} ${vbW} ${vbH}`;

  function openingColor(type: ElevationOpening['type']) {
    return type === 'door' ? '#BFDBFE' : '#BAE6FD';
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
      {/* Direction tabs */}
      <div className="flex border-b border-gray-100">
        {elevations.map((e, i) => (
          <button
            key={e.direction}
            onClick={() => setActive(i)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 transition-colors',
              i === active ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-800'
            )}
          >
            {DIR_LABELS[e.direction] ?? e.direction}
          </button>
        ))}
      </div>

      {/* SVG */}
      <div className="flex-1 bg-gray-50 p-4" style={{ minHeight: 280 }}>
        <svg viewBox={vbStr} className="w-full h-full">
          {/* Building outline */}
          <rect x={0} y={0} width={ev.width_m} height={ev.height_m} fill="#F1F5F9" stroke="#334155" strokeWidth={0.05} />

          {/* Floor bands */}
          {ev.floor_levels.map((level, i) => (
            <g key={i}>
              <line x1={0} y1={ev.height_m - level} x2={ev.width_m} y2={ev.height_m - level}
                stroke="#94A3B8" strokeWidth={0.03} strokeDasharray="0.2 0.1" />
              <text x={-pad + 0.05} y={ev.height_m - level + 0.15} fontSize={0.18} fill="#94A3B8">
                {level.toFixed(1)}m
              </text>
            </g>
          ))}

          {/* Openings */}
          {ev.openings.map((o, i) => (
            <rect
              key={i}
              x={o.x_m}
              y={ev.height_m - o.bottom_m - o.height_m}
              width={o.width_m}
              height={o.height_m}
              fill={openingColor(o.type)}
              stroke="#60A5FA"
              strokeWidth={0.03}
            />
          ))}

          {/* Parapet */}
          <rect
            x={0} y={ev.height_m - ev.parapet_height_m}
            width={ev.width_m} height={ev.parapet_height_m}
            fill="#E2E8F0" stroke="#94A3B8" strokeWidth={0.03}
          />

          {/* Cardinal direction label */}
          <text x={ev.width_m / 2} y={-0.15} textAnchor="middle" fontSize={0.3} fill="#3B82F6" fontWeight="600">
            {DIR_LABELS[ev.direction]}
          </text>
        </svg>
      </div>

      {/* Stats */}
      <div className="px-4 py-2 border-t border-gray-100 flex gap-6 text-xs text-gray-500">
        <span>Width: {ev.width_m.toFixed(1)} m</span>
        <span>Height: {ev.height_m.toFixed(1)} m</span>
        <span>Parapet: {ev.parapet_height_m.toFixed(2)} m</span>
        <span>Openings: {ev.openings.length}</span>
      </div>
    </div>
  );
}
