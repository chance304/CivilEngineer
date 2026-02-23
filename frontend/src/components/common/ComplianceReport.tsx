'use client';

import { AlertCircle, AlertTriangle, Info, CheckCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ComplianceReport, ComplianceViolation } from '@/types/api';

interface ComplianceReportProps {
  report: ComplianceReport;
}

const SEVERITY_CONFIG = {
  hard: {
    icon: AlertCircle,
    bg: 'bg-red-50',
    border: 'border-red-200',
    text: 'text-red-700',
    iconColor: 'text-red-500',
    label: 'Hard violation',
  },
  soft: {
    icon: AlertTriangle,
    bg: 'bg-yellow-50',
    border: 'border-yellow-200',
    text: 'text-yellow-700',
    iconColor: 'text-yellow-500',
    label: 'Warning',
  },
  advisory: {
    icon: Info,
    bg: 'bg-blue-50',
    border: 'border-blue-200',
    text: 'text-blue-700',
    iconColor: 'text-blue-400',
    label: 'Advisory',
  },
};

function ViolationRow({ v }: { v: ComplianceViolation }) {
  const cfg = SEVERITY_CONFIG[v.severity] ?? SEVERITY_CONFIG.advisory;
  const Icon = cfg.icon;
  return (
    <div className={cn('flex gap-3 p-3 rounded-lg border', cfg.bg, cfg.border)}>
      <Icon className={cn('w-4 h-4 shrink-0 mt-0.5', cfg.iconColor)} />
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-0.5">
          <span className={cn('text-xs font-semibold', cfg.text)}>{cfg.label}</span>
          {v.rule_id && <span className="text-xs text-gray-400 font-mono">{v.rule_id}</span>}
        </div>
        <p className={cn('text-sm', cfg.text)}>{v.message}</p>
        {v.page_ref && (
          <p className="text-xs text-gray-400 mt-0.5">Ref: {v.page_ref}</p>
        )}
      </div>
    </div>
  );
}

export function ComplianceReport({ report }: ComplianceReportProps) {
  const hard     = report.violations.filter((v) => v.severity === 'hard');
  const soft     = report.violations.filter((v) => v.severity === 'soft');
  const advisory = report.violations.filter((v) => v.severity === 'advisory');

  return (
    <div className="space-y-4">
      {/* Summary header */}
      <div className={cn(
        'flex items-center gap-3 p-4 rounded-xl border',
        report.passed ? 'bg-green-50 border-green-200' : 'bg-red-50 border-red-200'
      )}>
        {report.passed ? (
          <CheckCircle className="w-6 h-6 text-green-500 shrink-0" />
        ) : (
          <AlertCircle className="w-6 h-6 text-red-500 shrink-0" />
        )}
        <div>
          <p className={cn('font-semibold', report.passed ? 'text-green-700' : 'text-red-700')}>
            {report.passed ? 'Design is compliant' : 'Design has violations'}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">
            FAR: {report.far_actual.toFixed(2)} / {report.far_limit.toFixed(2)}
            {report.vastu_score != null && ` · Vastu: ${report.vastu_score}/10`}
          </p>
        </div>
      </div>

      {/* Violations grouped by severity */}
      {hard.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-red-600 uppercase tracking-wide mb-2">
            Hard Violations ({hard.length})
          </h3>
          <div className="space-y-2">{hard.map((v, i) => <ViolationRow key={i} v={v} />)}</div>
        </section>
      )}
      {soft.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-yellow-600 uppercase tracking-wide mb-2">
            Warnings ({soft.length})
          </h3>
          <div className="space-y-2">{soft.map((v, i) => <ViolationRow key={i} v={v} />)}</div>
        </section>
      )}
      {advisory.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-2">
            Advisory ({advisory.length})
          </h3>
          <div className="space-y-2">{advisory.map((v, i) => <ViolationRow key={i} v={v} />)}</div>
        </section>
      )}
      {report.violations.length === 0 && (
        <p className="text-sm text-gray-500 text-center py-4">No violations found.</p>
      )}
    </div>
  );
}
