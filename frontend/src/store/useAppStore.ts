import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'firm_admin' | 'senior_engineer' | 'engineer' | 'viewer';
  firm_id: string;
}

interface Firm {
  id: string;
  name: string;
}

interface JobProgress {
  session_id: string;
  step: string;
  step_index: number;
  total_steps: number;
  message: string;
  status: 'running' | 'completed' | 'failed' | 'waiting_approval';
}

interface ApprovalRequest {
  session_id: string;
  project_id: string;
  prompt: string;
  type: 'floor_plan_review' | 'interview';
}

interface AppState {
  // Auth
  user: User | null;
  accessToken: string | null;
  firm: Firm | null;

  // Navigation
  activeProjectId: string | null;

  // Design job
  jobProgress: JobProgress | null;
  approvalRequest: ApprovalRequest | null;

  // Actions
  setUser: (user: User | null) => void;
  setAccessToken: (token: string | null) => void;
  setFirm: (firm: Firm | null) => void;
  setActiveProjectId: (id: string | null) => void;
  setJobProgress: (progress: JobProgress | null) => void;
  setApprovalRequest: (req: ApprovalRequest | null) => void;
  logout: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      user: null,
      accessToken: null,
      firm: null,
      activeProjectId: null,
      jobProgress: null,
      approvalRequest: null,

      setUser: (user) => set({ user }),
      setAccessToken: (accessToken) => set({ accessToken }),
      setFirm: (firm) => set({ firm }),
      setActiveProjectId: (id) => set({ activeProjectId: id }),
      setJobProgress: (jobProgress) => set({ jobProgress }),
      setApprovalRequest: (approvalRequest) => set({ approvalRequest }),
      logout: () =>
        set({
          user: null,
          accessToken: null,
          firm: null,
          activeProjectId: null,
          jobProgress: null,
          approvalRequest: null,
        }),
    }),
    {
      name: 'civilengineer-store',
      partialize: (state) => ({
        user: state.user,
        accessToken: state.accessToken,
        firm: state.firm,
      }),
    }
  )
);
