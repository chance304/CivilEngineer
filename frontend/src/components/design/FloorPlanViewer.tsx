'use client';

import { useState, useRef } from 'react';
import { ZoomIn, ZoomOut, RotateCcw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { getViewBox, getRooms, getWalls, getColumns } from '@/lib/dxf-renderer';
import type { FloorPlan } from '@/types/api';

interface FloorPlanViewerProps {
  floorPlans: FloorPlan[];
  complianceBadges?: { label: string; ok: boolean }[];
}

export function FloorPlanViewer({ floorPlans, complianceBadges = [] }: FloorPlanViewerProps) {
  const [activeFloor, setActiveFloor] = useState(0);
  const [scale, setScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef({ x: 0, y: 0 });
  const panOrigin = useRef({ x: 0, y: 0 });

  const fp = floorPlans[activeFloor];
  if (!fp) return null;

  const vb = getViewBox(fp);
  const rooms = getRooms(fp);
  const walls = getWalls(fp);
  const columns = getColumns(fp);

  const vbStr = `${vb.x} ${vb.y} ${vb.width} ${vb.height}`;

  function onWheel(e: React.WheelEvent) {
    e.preventDefault();
    setScale((s) => Math.max(0.5, Math.min(5, s - e.deltaY * 0.001)));
  }

  function onMouseDown(e: React.MouseEvent) {
    setIsPanning(true);
    panStart.current = { x: e.clientX, y: e.clientY };
    panOrigin.current = { ...pan };
  }

  function onMouseMove(e: React.MouseEvent) {
    if (!isPanning) return;
    setPan({
      x: panOrigin.current.x + (e.clientX - panStart.current.x),
      y: panOrigin.current.y + (e.clientY - panStart.current.y),
    });
  }

  function onMouseUp() { setIsPanning(false); }

  function reset() { setScale(1); setPan({ x: 0, y: 0 }); }

  return (
    <div className="bg-white rounded-xl border border-gray-200 flex flex-col overflow-hidden">
      {/* Floor tabs */}
      <div className="flex border-b border-gray-100 overflow-x-auto">
        {floorPlans.map((f, i) => (
          <button
            key={f.floor}
            onClick={() => setActiveFloor(i)}
            className={cn(
              'px-4 py-2 text-sm font-medium shrink-0 border-b-2 transition-colors',
              i === activeFloor
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-800'
            )}
          >
            Floor {f.floor}
          </button>
        ))}
      </div>

      {/* Compliance badges */}
      {complianceBadges.length > 0 && (
        <div className="flex gap-2 px-4 py-2 border-b border-gray-100 overflow-x-auto">
          {complianceBadges.map((b) => (
            <span
              key={b.label}
              className={cn(
                'text-xs px-2 py-0.5 rounded-full font-medium',
                b.ok ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-600'
              )}
            >
              {b.ok ? '✓' : '✗'} {b.label}
            </span>
          ))}
        </div>
      )}

      {/* SVG canvas */}
      <div
        className="flex-1 bg-gray-50 relative overflow-hidden cursor-grab active:cursor-grabbing"
        style={{ minHeight: 400 }}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
      >
        <svg
          viewBox={vbStr}
          className="w-full h-full"
          style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})`, transformOrigin: 'center', transition: isPanning ? 'none' : 'transform 0.1s' }}
        >
          {/* Plot boundary background */}
          <rect
            x={vb.x} y={vb.y} width={vb.width} height={vb.height}
            fill="#F8FAFC" stroke="#CBD5E1" strokeWidth={0.1} strokeDasharray="0.5 0.3"
          />

          {/* Rooms */}
          {rooms.map((r) => (
            <g key={r.id}>
              <rect x={r.x} y={r.y} width={r.width} height={r.height} fill={r.fill} stroke="#94A3B8" strokeWidth={0.05} />
              <text x={r.x + r.width / 2} y={r.y + r.height / 2 - 0.1} textAnchor="middle" fontSize={0.22} fill="#374151" fontWeight="500">
                {r.label}
              </text>
              <text x={r.x + r.width / 2} y={r.y + r.height / 2 + 0.25} textAnchor="middle" fontSize={0.16} fill="#6B7280">
                {r.area}
              </text>
            </g>
          ))}

          {/* Walls */}
          {walls.map((w, i) => (
            <line
              key={i}
              x1={w.x1} y1={w.y1} x2={w.x2} y2={w.y2}
              stroke="#1E293B"
              strokeWidth={w.strokeWidth}
              strokeDasharray={w.dashed ? '0.2 0.1' : undefined}
            />
          ))}

          {/* Columns */}
          {columns.map((c, i) => (
            <rect key={i} x={c.x} y={c.y} width={c.width} height={c.height} fill="#334155" />
          ))}

          {/* North arrow */}
          <text x={vb.x + 0.3} y={vb.y + 0.5} fontSize={0.3} fill="#6B7280">N↑</text>
        </svg>

        {/* Zoom controls */}
        <div className="absolute top-2 right-2 flex flex-col gap-1">
          <button onClick={() => setScale((s) => Math.min(5, s + 0.2))} className="w-7 h-7 bg-white border border-gray-200 rounded-lg flex items-center justify-center shadow-sm hover:bg-gray-50">
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
          <button onClick={() => setScale((s) => Math.max(0.5, s - 0.2))} className="w-7 h-7 bg-white border border-gray-200 rounded-lg flex items-center justify-center shadow-sm hover:bg-gray-50">
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <button onClick={reset} className="w-7 h-7 bg-white border border-gray-200 rounded-lg flex items-center justify-center shadow-sm hover:bg-gray-50">
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="px-4 py-2 border-t border-gray-100 flex gap-4 overflow-x-auto">
        <LegendItem color="#1E293B" label="Load-bearing wall" />
        <LegendItem color="#94A3B8" label="Partition" dashed />
        <LegendItem color="#334155" label="Column" />
      </div>
    </div>
  );
}

function LegendItem({ color, label, dashed = false }: { color: string; label: string; dashed?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <svg width="20" height="8">
        <line x1="0" y1="4" x2="20" y2="4" stroke={color} strokeWidth="2.5" strokeDasharray={dashed ? '4 2' : undefined} />
      </svg>
      <span className="text-xs text-gray-500">{label}</span>
    </div>
  );
}
