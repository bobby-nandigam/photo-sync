import type { Account, FileRow, SyncStatus } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export const api = {
  // --- auth / accounts ---
  async connect(): Promise<void> {
    const { authorization_url } = await req<{ authorization_url: string }>(
      "/api/auth/google/connect"
    );
    window.location.href = authorization_url;
  },
  listAccounts: () => req<Account[]>("/api/accounts"),
  refreshAccount: (id: number) =>
    req<Account>(`/api/accounts/${id}/refresh`, { method: "POST" }),
  disconnect: (id: number) =>
    req<{ ok: boolean; message: string }>(`/api/accounts/${id}`, { method: "DELETE" }),

  // --- sync ---
  status: () => req<SyncStatus>("/api/sync/status"),
  start: () => req<{ ok: boolean; message: string }>("/api/sync/start", { method: "POST" }),
  pause: () => req<{ ok: boolean; message: string }>("/api/sync/pause", { method: "POST" }),
  resume: () => req<{ ok: boolean; message: string }>("/api/sync/resume", { method: "POST" }),
  retryFailed: () =>
    req<{ ok: boolean; message: string }>("/api/sync/retry-failed", { method: "POST" }),
  queue: (status?: string, limit = 200) =>
    req<{ items: FileRow[]; total: number }>(
      `/api/sync/queue?limit=${limit}${status ? `&status=${status}` : ""}`
    ),

  // --- picker ---
  createPickerSession: (accountId: number) =>
    req<{
      session_id: string;
      picker_uri: string;
      poll_interval_seconds: number;
      media_items_set: boolean;
    }>(`/api/picker/sessions?account_id=${accountId}`, { method: "POST" }),
  pollPickerSession: (sessionId: string, accountId: number) =>
    req<{ session_id: string; media_items_set: boolean }>(
      `/api/picker/sessions/${sessionId}?account_id=${accountId}`
    ),
  importPicked: (accountId: number, sessionId: string) =>
    req<{ imported: number; already_tracked: number; total_selected: number }>(
      `/api/picker/import?account_id=${accountId}&session_id=${sessionId}`,
      { method: "POST" }
    ),
};

export function formatBytes(n: number): string {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(n) / Math.log(1024));
  return `${(n / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${units[i]}`;
}
