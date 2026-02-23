'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Sidebar } from '@/components/common/Sidebar';
import { Header } from '@/components/common/Header';
import { useAppStore } from '@/store/useAppStore';

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  const { accessToken, user } = useAppStore();
  const router = useRouter();

  useEffect(() => {
    if (!accessToken || !user) {
      router.push('/login');
    }
  }, [accessToken, user, router]);

  if (!accessToken || !user) return null;

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar role={user.role} />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Header user={user} />
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
