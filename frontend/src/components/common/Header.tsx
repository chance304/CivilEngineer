'use client';

import { LogOut, User as UserIcon } from 'lucide-react';
import { useAppStore } from '@/store/useAppStore';
import { useRouter } from 'next/navigation';
import { authApi } from '@/lib/api';

interface HeaderProps {
  user: { full_name: string; email: string; role: string };
}

const ROLE_LABELS: Record<string, string> = {
  firm_admin: 'Admin',
  senior_engineer: 'Sr. Engineer',
  engineer: 'Engineer',
  viewer: 'Viewer',
};

export function Header({ user }: HeaderProps) {
  const { logout } = useAppStore();
  const router = useRouter();

  async function handleLogout() {
    try { await authApi.logout(); } catch { /* ignore */ }
    logout();
    router.push('/login');
  }

  return (
    <header className="h-14 bg-white border-b border-gray-200 flex items-center justify-between px-6 shrink-0">
      <div className="text-sm text-gray-500">CivilEngineer AI Portal</div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2 text-sm">
          <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center">
            <UserIcon className="w-4 h-4 text-blue-600" />
          </div>
          <div className="hidden md:block">
            <div className="font-medium text-gray-900 text-xs">{user.full_name}</div>
            <div className="text-gray-400 text-xs">{ROLE_LABELS[user.role] ?? user.role}</div>
          </div>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-800 transition-colors px-2 py-1.5 rounded-md hover:bg-gray-100"
          aria-label="Sign out"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span className="hidden md:inline">Sign out</span>
        </button>
      </div>
    </header>
  );
}
