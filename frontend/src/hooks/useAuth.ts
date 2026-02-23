'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAppStore } from '@/store/useAppStore';
import { authApi } from '@/lib/api';

export function useAuth() {
  const { user, accessToken, setUser, logout } = useAppStore();
  const router = useRouter();

  const isAuthenticated = !!accessToken && !!user;

  async function refreshUser() {
    if (!accessToken) return;
    try {
      const me = await authApi.me();
      setUser(me as Parameters<typeof setUser>[0]);
    } catch {
      logout();
      router.push('/login');
    }
  }

  return {
    user,
    accessToken,
    isAuthenticated,
    logout: () => {
      authApi.logout().catch(() => {});
      logout();
      router.push('/login');
    },
    refreshUser,
    isAdmin: user?.role === 'firm_admin',
    isSeniorEngineer: user?.role === 'senior_engineer' || user?.role === 'firm_admin',
  };
}

export function useRequireAuth() {
  const { isAuthenticated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, router]);

  return useAuth();
}
