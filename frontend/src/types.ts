export interface Account {
  id: number;
  email: string;
  display_name: string;
  status: "CONNECTED" | "DISCONNECTED" | "ERROR";
  priority: number;
  can_be_destination: boolean;
  storage_limit: number;
  storage_usage: number;
  storage_free: number;
  storage_fraction: number;
  near_full: boolean;
  is_full: boolean;
  storage_checked_at: string | null;
}

export interface FileRow {
  id: number;
  source_account_id: number | null;
  source_file_id: string;
  file_name: string;
  mime_type: string;
  file_size: number;
  created_time: string | null;
  checksum: string | null;
  status: "PENDING" | "PROCESSING" | "SYNCED" | "SKIPPED_DUPLICATE" | "FAILED";
  destination_account_id: number | null;
  destination_file_id: string | null;
  synced_at: string | null;
  ai_note: string | null;
  attempts: number;
  last_error: string | null;
  queue_seq: number;
}

export interface Totals {
  total: number;
  synced: number;
  pending: number;
  processing: number;
  skipped_duplicate: number;
  failed: number;
  remaining: number;
  progress_pct: number;
}

export interface SyncStatus {
  state: "IDLE" | "RUNNING" | "PAUSED";
  paused_reason: string | null;
  current_file: FileRow | null;
  current_destination_account_id: number | null;
  totals: Totals;
  accounts: Account[];
}
