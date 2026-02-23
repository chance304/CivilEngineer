'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { toast } from 'sonner';
import { useAppStore } from '@/store/useAppStore';

const profileSchema = z.object({
  full_name: z.string().min(2, 'Name must be at least 2 characters'),
});

const passwordSchema = z.object({
  current_password: z.string().min(1, 'Current password required'),
  new_password: z.string().min(8, 'At least 8 characters'),
  confirm_password: z.string(),
}).refine((d) => d.new_password === d.confirm_password, {
  message: 'Passwords do not match',
  path: ['confirm_password'],
});

type ProfileData = z.infer<typeof profileSchema>;
type PasswordData = z.infer<typeof passwordSchema>;

export default function SettingsPage() {
  const { user } = useAppStore();

  const profileForm = useForm<ProfileData>({
    resolver: zodResolver(profileSchema),
    defaultValues: { full_name: user?.full_name ?? '' },
  });

  const passwordForm = useForm<PasswordData>({ resolver: zodResolver(passwordSchema) });

  async function onProfileSubmit(data: ProfileData) {
    // In a real app: PATCH /users/me
    toast.success('Profile updated');
    console.log('profile update', data);
  }

  async function onPasswordSubmit(data: PasswordData) {
    // In a real app: POST /auth/change-password
    toast.success('Password changed');
    passwordForm.reset();
    console.log('password change', data);
  }

  return (
    <div className="max-w-xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Settings</h1>

      {/* Profile */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="font-semibold text-gray-900 mb-4">Profile</h2>
        <form onSubmit={profileForm.handleSubmit(onProfileSubmit)} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Display name</label>
            <input {...profileForm.register('full_name')} className={inputClass} />
            {profileForm.formState.errors.full_name && (
              <p className="text-red-500 text-xs mt-1">{profileForm.formState.errors.full_name.message}</p>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Email address</label>
            <input value={user?.email ?? ''} readOnly className={`${inputClass} bg-gray-50 text-gray-400 cursor-not-allowed`} />
            <p className="text-xs text-gray-400 mt-1">Email cannot be changed. Contact your firm admin.</p>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Role</label>
            <input value={user?.role ?? ''} readOnly className={`${inputClass} bg-gray-50 text-gray-400 cursor-not-allowed capitalize`} />
          </div>
          <button type="submit" disabled={profileForm.formState.isSubmitting} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            Save changes
          </button>
        </form>
      </div>

      {/* Password */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="font-semibold text-gray-900 mb-4">Change password</h2>
        <form onSubmit={passwordForm.handleSubmit(onPasswordSubmit)} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Current password</label>
            <input {...passwordForm.register('current_password')} type="password" className={inputClass} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">New password</label>
            <input {...passwordForm.register('new_password')} type="password" className={inputClass} />
            {passwordForm.formState.errors.new_password && (
              <p className="text-red-500 text-xs mt-1">{passwordForm.formState.errors.new_password.message}</p>
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Confirm new password</label>
            <input {...passwordForm.register('confirm_password')} type="password" className={inputClass} />
            {passwordForm.formState.errors.confirm_password && (
              <p className="text-red-500 text-xs mt-1">{passwordForm.formState.errors.confirm_password.message}</p>
            )}
          </div>
          <button type="submit" disabled={passwordForm.formState.isSubmitting} className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            Update password
          </button>
        </form>
      </div>

      {/* Notification preferences placeholder */}
      <div className="bg-white rounded-xl border border-gray-200 p-6">
        <h2 className="font-semibold text-gray-900 mb-2">Notifications</h2>
        <p className="text-sm text-gray-400">Notification preferences coming soon.</p>
      </div>
    </div>
  );
}

const inputClass = 'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
