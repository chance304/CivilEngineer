'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { toast } from 'sonner';
import { adminApi } from '@/lib/api';
import { cn } from '@/lib/utils';
import { UserPlus } from 'lucide-react';
import type { User } from '@/types/api';

const ROLE_STYLES: Record<string, string> = {
  firm_admin: 'bg-purple-100 text-purple-700',
  senior_engineer: 'bg-blue-100 text-blue-700',
  engineer: 'bg-green-100 text-green-700',
  viewer: 'bg-gray-100 text-gray-600',
};

const inviteSchema = z.object({
  email: z.string().email('Enter a valid email'),
  full_name: z.string().min(2, 'Name required'),
  role: z.enum(['firm_admin', 'senior_engineer', 'engineer', 'viewer']).default('engineer'),
});

type InviteData = z.infer<typeof inviteSchema>;

export default function UsersPage() {
  const qc = useQueryClient();
  const [showInvite, setShowInvite] = useState(false);

  const { data: users, isLoading } = useQuery<User[]>({
    queryKey: ['admin-users'],
    queryFn: () => adminApi.getUsers() as Promise<User[]>,
  });

  const inviteMut = useMutation({
    mutationFn: (data: InviteData) => adminApi.inviteUser(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-users'] });
      toast.success('Invitation sent');
      setShowInvite(false);
      form.reset();
    },
    onError: () => toast.error('Failed to send invitation'),
  });

  const form = useForm<InviteData>({ resolver: zodResolver(inviteSchema) });

  return (
    <div className="max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Users</h1>
          <p className="text-gray-500 text-sm mt-1">Manage firm members and their roles.</p>
        </div>
        <button
          onClick={() => setShowInvite(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          <UserPlus className="w-4 h-4" /> Invite user
        </button>
      </div>

      {isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => <div key={i} className="h-14 bg-gray-100 rounded-xl animate-pulse" />)}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-200">
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600">Name</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600">Email</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600">Role</th>
              <th className="px-4 py-2.5 text-left text-xs font-semibold text-gray-600">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {users?.map((user) => (
              <tr key={user.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium text-gray-900">{user.full_name}</td>
                <td className="px-4 py-3 text-gray-500">{user.email}</td>
                <td className="px-4 py-3">
                  <span className={cn('text-xs px-2 py-0.5 rounded-full font-medium', ROLE_STYLES[user.role] ?? '')}>
                    {user.role}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <span className={cn('text-xs px-2 py-0.5 rounded-full', user.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500')}>
                    {user.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Invite modal */}
      {showInvite && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-2xl">
            <h2 className="font-semibold text-gray-900 mb-4">Invite User</h2>
            <form onSubmit={form.handleSubmit((d) => inviteMut.mutate(d))} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Full name</label>
                <input {...form.register('full_name')} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                {form.formState.errors.full_name && <p className="text-red-500 text-xs mt-1">{form.formState.errors.full_name.message}</p>}
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Email</label>
                <input {...form.register('email')} type="email" className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                {form.formState.errors.email && <p className="text-red-500 text-xs mt-1">{form.formState.errors.email.message}</p>}
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
                <select {...form.register('role')} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                  <option value="engineer">Engineer</option>
                  <option value="senior_engineer">Senior Engineer</option>
                  <option value="firm_admin">Firm Admin</option>
                  <option value="viewer">Viewer</option>
                </select>
              </div>
              <div className="flex justify-end gap-3 pt-2">
                <button type="button" onClick={() => setShowInvite(false)} className="text-sm text-gray-500 hover:text-gray-800 px-3 py-1.5">Cancel</button>
                <button type="submit" disabled={inviteMut.isPending} className="px-4 py-1.5 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
                  {inviteMut.isPending ? 'Sending…' : 'Send invitation'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
