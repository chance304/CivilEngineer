'use client';

import { useParams } from 'next/navigation';
import { InterviewChat } from '@/components/interview/InterviewChat';

export default function InterviewPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="max-w-3xl mx-auto h-full flex flex-col">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-gray-900">Design Interview</h1>
        <p className="text-gray-500 text-sm">Tell us about your requirements and we&apos;ll design your building.</p>
      </div>
      <InterviewChat projectId={id} />
    </div>
  );
}
