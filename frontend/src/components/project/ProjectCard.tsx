'use client';

import Link from 'next/link';
import { ArrowRight, Calendar, MapPin } from 'lucide-react';
import { cn, formatRelativeDate } from '@/lib/utils';
import type { ProjectListItem } from '@/types/api';

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-700',
  draft: 'bg-yellow-100 text-yellow-700',
  completed: 'bg-blue-100 text-blue-700',
  archived: 'bg-gray-100 text-gray-600',
};

interface ProjectCardProps {
  project: ProjectListItem;
}

export function ProjectCard({ project }: ProjectCardProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition-shadow flex flex-col gap-4">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-gray-900 truncate text-sm">{project.name}</h3>
          {project.client_name && (
            <p className="text-gray-500 text-xs mt-0.5 truncate">{project.client_name}</p>
          )}
        </div>
        <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium ml-2 shrink-0', STATUS_STYLES[project.status] ?? STATUS_STYLES.draft)}>
          {project.status}
        </span>
      </div>

      <div className="space-y-1.5 text-xs text-gray-500">
        <div className="flex items-center gap-1.5">
          <MapPin className="w-3 h-3 shrink-0" />
          <span className="truncate">{project.jurisdiction}</span>
          {project.num_floors && <span className="ml-auto shrink-0">{project.num_floors} floor{project.num_floors > 1 ? 's' : ''}</span>}
        </div>
        <div className="flex items-center gap-1.5">
          <Calendar className="w-3 h-3 shrink-0" />
          <span>{formatRelativeDate(project.updated_at)}</span>
        </div>
      </div>

      <div className="flex gap-2 pt-1">
        <Link
          href={`/projects/${project.id}/plot`}
          className="flex-1 text-center py-1.5 px-3 text-xs font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
        >
          Open
        </Link>
        <Link
          href={`/projects/${project.id}/interview`}
          className="flex items-center gap-1 py-1.5 px-3 text-xs font-medium text-blue-600 border border-blue-200 rounded-lg hover:bg-blue-50 transition-colors"
        >
          New Design <ArrowRight className="w-3 h-3" />
        </Link>
      </div>
    </div>
  );
}
