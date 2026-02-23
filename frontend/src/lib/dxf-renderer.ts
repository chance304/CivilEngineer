/**
 * FloorPlan JSON → SVG element data
 *
 * Pure functions that convert FloorPlan data into SVG primitive descriptions.
 * No DXF parser needed — we render from the JSON design data directly.
 */

import type { FloorPlan, RoomLayout } from '@/types/api';

export interface SvgViewBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SvgRoom {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
  area: string;
  fill: string;
  roomType: string;
}

export interface SvgWall {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  strokeWidth: number;
  dashed: boolean;
}

export interface SvgColumn {
  x: number;
  y: number;
  width: number;
  height: number;
}

// Room type → fill colour
const ROOM_COLORS: Record<string, string> = {
  master_bedroom:   '#DBEAFE',
  bedroom:          '#EFF6FF',
  living_room:      '#DCFCE7',
  dining_room:      '#F0FDF4',
  kitchen:          '#FEF3C7',
  bathroom:         '#CCFBF1',
  toilet:           '#E0F2FE',
  staircase:        '#F5F3FF',
  corridor:         '#F9FAFB',
  garage:           '#F3F4F6',
  store:            '#FEF9C3',
  pooja_room:       '#FDF2F8',
  home_office:      '#EFF6FF',
  balcony:          '#ECFDF5',
  terrace:          '#F0FDF4',
  other:            '#F9FAFB',
};

export function getViewBox(fp: FloorPlan): SvgViewBox {
  const bz = fp.buildable_zone;
  const pad = 2;
  return {
    x: bz.x - pad,
    y: bz.y - pad,
    width: bz.width + pad * 2,
    height: bz.depth + pad * 2,
  };
}

export function getRooms(fp: FloorPlan): SvgRoom[] {
  return fp.rooms.map((r) => ({
    id: r.room_id,
    x: r.bounds.x,
    y: r.bounds.y,
    width: r.bounds.width,
    height: r.bounds.depth,
    label: r.name,
    area: `${(r.bounds.width * r.bounds.depth).toFixed(1)} m²`,
    fill: ROOM_COLORS[r.room_type] ?? ROOM_COLORS.other,
    roomType: r.room_type,
  }));
}

export function getWalls(fp: FloorPlan): SvgWall[] {
  return fp.wall_segments.map((w) => ({
    x1: w.start.x,
    y1: w.start.y,
    x2: w.end.x,
    y2: w.end.y,
    strokeWidth: w.is_external ? 0.15 : 0.10,
    dashed: !w.is_load_bearing,
  }));
}

export function getColumns(fp: FloorPlan): SvgColumn[] {
  return fp.columns.map((c) => ({
    x: c.x - c.width / 2,
    y: c.y - c.depth / 2,
    width: c.width,
    height: c.depth,
  }));
}

export function getRoomCentroid(r: RoomLayout): { cx: number; cy: number } {
  return {
    cx: r.bounds.x + r.bounds.width / 2,
    cy: r.bounds.y + r.bounds.depth / 2,
  };
}
