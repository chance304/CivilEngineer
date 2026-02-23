'use client';

import { useState } from 'react';
import { RotateCw, RotateCcw } from 'lucide-react';
import type { BuildingOutline3D } from '@/types/api';

interface Building3DViewerProps {
  outline: BuildingOutline3D;
}

// Isometric projection: rotate around Z-axis then project
function isoProject(
  v: { x: number; y: number; z: number },
  rotationDeg: number
): { px: number; py: number } {
  const rad = (rotationDeg * Math.PI) / 180;
  const rx = v.x * Math.cos(rad) - v.y * Math.sin(rad);
  const ry = v.x * Math.sin(rad) + v.y * Math.cos(rad);
  // Isometric: flatten Y axis
  return {
    px: rx,
    py: -ry * 0.5 - v.z * 0.6,
  };
}

export function Building3DViewer({ outline }: Building3DViewerProps) {
  const [rotation, setRotation] = useState(45);

  const projected = outline.vertices.map((v) => isoProject(v, rotation));

  // Compute viewBox from projected points
  const xs = projected.map((p) => p.px);
  const ys = projected.map((p) => p.py);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const maxX = Math.max(...xs);
  const maxY = Math.max(...ys);
  const pad = 1;
  const vbStr = `${minX - pad} ${minY - pad} ${maxX - minX + pad * 2} ${maxY - minY + pad * 2}`;

  const roofSet = new Set(outline.roof_edge_indices ?? []);

  return (
    <div className="bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100">
        <span className="text-sm font-medium text-gray-700">3D Building Outline</span>
        <div className="flex gap-1">
          <button
            onClick={() => setRotation((r) => r - 45)}
            className="w-7 h-7 flex items-center justify-center rounded-lg border border-gray-200 hover:bg-gray-50"
            aria-label="Rotate left"
          >
            <RotateCcw className="w-3.5 h-3.5 text-gray-600" />
          </button>
          <button
            onClick={() => setRotation((r) => r + 45)}
            className="w-7 h-7 flex items-center justify-center rounded-lg border border-gray-200 hover:bg-gray-50"
            aria-label="Rotate right"
          >
            <RotateCw className="w-3.5 h-3.5 text-gray-600" />
          </button>
        </div>
      </div>

      <div className="flex-1 bg-gray-50" style={{ minHeight: 260 }}>
        <svg viewBox={vbStr} className="w-full h-full">
          {outline.edges.map(([a, b], i) => {
            const pa = projected[a];
            const pb = projected[b];
            if (!pa || !pb) return null;
            const isRoof = roofSet.has(i);
            return (
              <line
                key={i}
                x1={pa.px} y1={pa.py}
                x2={pb.px} y2={pb.py}
                stroke={isRoof ? '#3B82F6' : '#334155'}
                strokeWidth={isRoof ? 0.08 : 0.12}
                strokeDasharray={isRoof ? '0.3 0.15' : undefined}
              />
            );
          })}
          {outline.vertices.map((_, i) => {
            const p = projected[i];
            return <circle key={i} cx={p.px} cy={p.py} r={0.06} fill="#64748B" />;
          })}
        </svg>
      </div>

      <div className="px-4 py-2 border-t border-gray-100 text-xs text-gray-400">
        Rotation: {((rotation % 360) + 360) % 360}° — drag controls to rotate
      </div>
    </div>
  );
}
