import { useAppStore } from '@/store/useAppStore';

const API_BASE = '/api/v1';

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const { accessToken } = useAppStore.getState();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include', // send httpOnly refresh cookie
  });

  if (res.status === 401) {
    // Try token refresh
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      // Retry once with new token
      headers['Authorization'] = `Bearer ${useAppStore.getState().accessToken}`;
      const retry = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers,
        credentials: 'include',
      });
      if (!retry.ok) {
        useAppStore.getState().logout();
        window.location.href = '/login';
        throw new ApiError(retry.status, 'Unauthorized');
      }
      return retry.json() as Promise<T>;
    } else {
      useAppStore.getState().logout();
      window.location.href = '/login';
      throw new ApiError(401, 'Session expired');
    }
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body?.detail ?? res.statusText, body);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

async function tryRefreshToken(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    });
    if (!res.ok) return false;
    const data = await res.json();
    useAppStore.getState().setAccessToken(data.access_token);
    return true;
  } catch {
    return false;
  }
}

// Auth
export const authApi = {
  login: (email: string, password: string) =>
    apiFetch<{ access_token: string; user: unknown }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),
  logout: () => apiFetch('/auth/logout', { method: 'POST' }),
  me: () => apiFetch<unknown>('/auth/me'),
  requestPasswordReset: (email: string) =>
    apiFetch('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
};

// Projects
export const projectsApi = {
  list: () => apiFetch<unknown[]>('/projects/'),
  get: (id: string) => apiFetch<unknown>(`/projects/${id}`),
  create: (data: unknown) =>
    apiFetch<unknown>('/projects/', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: unknown) =>
    apiFetch<unknown>(`/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  getPlotUploadUrl: (id: string) =>
    apiFetch<{ upload_url: string; key: string }>(`/projects/${id}/plot/upload-url`),
  submitPlot: (id: string, data: unknown) =>
    apiFetch<unknown>(`/projects/${id}/plot`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
};

// Design sessions
export const designApi = {
  start: (projectId: string) =>
    apiFetch<{ session_id: string }>(`/projects/${projectId}/design`, {
      method: 'POST',
    }),
  list: (projectId: string) =>
    apiFetch<{
      job_id: string;
      session_id: string;
      status: string;
      current_step: string;
      submitted_at: string;
      completed_at: string | null;
    }[]>(`/projects/${projectId}/design`),
  getJob: (projectId: string, sessionId: string) =>
    apiFetch<{
      job_id: string;
      session_id: string;
      status: string;
      current_step: string;
      result: Record<string, unknown> | null;
    }>(`/projects/${projectId}/design/${sessionId}`),
  sendInterviewAnswer: (projectId: string, sessionId: string, answer: string) =>
    apiFetch<unknown>(`/projects/${projectId}/design/${sessionId}/interview`, {
      method: 'POST',
      body: JSON.stringify({ answer }),
    }),
  approve: (
    projectId: string,
    sessionId: string,
    action: 'approve' | 'revise' | 'abort',
    notes?: string
  ) =>
    apiFetch<unknown>(`/projects/${projectId}/design/${sessionId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ action, notes }),
    }),
  getFiles: (projectId: string, sessionId: string) =>
    apiFetch<{ name: string; type: string; download_url: string; size_bytes: number }[]>(
      `/projects/${projectId}/design/${sessionId}/files`
    ),
  downloadZip: async (projectId: string, sessionId: string) => {
    const { accessToken } = useAppStore.getState();
    const res = await fetch(`${API_BASE}/projects/${projectId}/design/${sessionId}/files/zip`, {
      headers: { Authorization: `Bearer ${accessToken ?? ''}` },
      credentials: 'include',
    });
    if (!res.ok) throw new Error('ZIP download failed');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `design-${sessionId.slice(0, 8)}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },
  finalize: (projectId: string, sessionId: string) =>
    apiFetch<{
      job_id: string;
      session_id: string;
      finalized: boolean;
      finalized_at: string | null;
      completeness: {
        is_complete: boolean;
        missing_required: string[];
        missing_advisory: string[];
        present: Record<string, boolean>;
        total_files: number;
      };
    }>(`/projects/${projectId}/design/${sessionId}/finalize`, { method: 'POST' }),
  getDecisions: (projectId: string) =>
    apiFetch<unknown[]>(`/projects/${projectId}/decisions`),
  getComplianceReports: (projectId: string) =>
    apiFetch<unknown[]>(`/projects/${projectId}/compliance-reports`),
  getClientApproval: (projectId: string, sessionId: string) =>
    apiFetch<{
      session_id: string;
      has_approval: boolean;
      action: string | null;
      notes: string | null;
      submitted_by: string | null;
      submitted_at: string | null;
    }>(`/projects/${projectId}/design/${sessionId}/client-approval`),
  clientApprove: (
    projectId: string,
    sessionId: string,
    action: 'approved' | 'revision_requested',
    notes?: string
  ) =>
    apiFetch<{
      session_id: string;
      has_approval: boolean;
      action: string | null;
      notes: string | null;
      submitted_by: string | null;
      submitted_at: string | null;
    }>(`/projects/${projectId}/design/${sessionId}/client-approve`, {
      method: 'POST',
      body: JSON.stringify({ action, notes: notes ?? '' }),
    }),
};

// Admin
export const adminApi = {
  getLlmConfig: () => apiFetch<unknown>('/admin/llm-config'),
  updateLlmConfig: (data: unknown) =>
    apiFetch<unknown>('/admin/llm-config', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  testLlmConnection: () =>
    apiFetch<{ ok: boolean; message: string }>('/admin/llm-config/test', {
      method: 'POST',
    }),
  getBuildingCodes: () => apiFetch<unknown[]>('/admin/building-codes'),
  uploadBuildingCode: (formData: FormData) =>
    fetch(`${API_BASE}/admin/building-codes/upload`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${useAppStore.getState().accessToken}`,
      },
      body: formData,
      credentials: 'include',
    }).then((r) => r.json()),
  getExtractedRules: (docId: string) =>
    apiFetch<unknown[]>(`/admin/building-codes/${docId}/rules`),
  approveRule: (docId: string, ruleId: string) =>
    apiFetch<unknown>(`/admin/building-codes/${docId}/rules/${ruleId}/approve`, {
      method: 'POST',
    }),
  rejectRule: (docId: string, ruleId: string) =>
    apiFetch<unknown>(`/admin/building-codes/${docId}/rules/${ruleId}/reject`, {
      method: 'POST',
    }),
  extractRules: (docId: string) =>
    apiFetch<{ doc_id: string; celery_task_id: string; message: string }>(
      `/admin/building-codes/${docId}/extract`,
      { method: 'POST' }
    ),
  activateRules: (docId: string) =>
    apiFetch<unknown>(`/admin/building-codes/${docId}/activate`, {
      method: 'POST',
    }),
  getUsers: () => apiFetch<unknown[]>('/admin/users'),
  inviteUser: (data: unknown) =>
    apiFetch<unknown>('/admin/users/invite', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getRules: (params?: { jurisdiction?: string; category?: string }) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return apiFetch<unknown[]>(`/admin/rules${qs ? `?${qs}` : ''}`);
  },
};

export { ApiError };
