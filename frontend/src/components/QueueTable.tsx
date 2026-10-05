import { useState } from "react";
import type { Account, FileRow } from "../types";
import { formatBytes } from "../api";

const STATUS_BADGE: Record<string, string> = {
  PENDING: "bg-slate-500/15 text-slate-300",
  PROCESSING: "bg-amber-500/15 text-amber-300",
  SYNCED: "bg-emerald-500/15 text-emerald-300",
  SKIPPED_DUPLICATE: "bg-indigo-500/15 text-indigo-300",
  FAILED: "bg-red-500/15 text-red-300",
};

const FILTERS = ["", "PENDING", "PROCESSING", "SYNCED", "SKIPPED_DUPLICATE", "FAILED"];

export function QueueTable({
  items,
  accounts,
  total,
  filter,
  onFilter,
}: {
  items: FileRow[];
  accounts: Account[];
  total: number;
  filter: string;
  onFilter: (f: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const emailOf = (id: number | null) =>
    id ? accounts.find((a) => a.id === id)?.email ?? `#${id}` : "—";

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 p-3">
        <button
          onClick={() => setOpen((o) => !o)}
          className="text-sm font-semibold uppercase tracking-wide text-slate-400"
        >
          Sync queue ({total}) {open ? "▾" : "▸"}
        </button>
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((f) => (
            <button
              key={f || "all"}
              onClick={() => onFilter(f)}
              className={`rounded-md px-2 py-1 text-xs ${
                filter === f ? "bg-sky-600 text-white" : "bg-slate-800 text-slate-300"
              }`}
            >
              {f || "ALL"}
            </button>
          ))}
        </div>
      </div>

      {open && (
        <div className="max-h-[28rem] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-slate-900 text-xs uppercase text-slate-500">
              <tr>
                <th className="px-3 py-2">#</th>
                <th className="px-3 py-2">File</th>
                <th className="px-3 py-2">Size</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Destination</th>
                <th className="px-3 py-2">AI note</th>
              </tr>
            </thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.id} className="border-t border-slate-800/60">
                  <td className="px-3 py-2 text-slate-500">{f.queue_seq}</td>
                  <td className="px-3 py-2">
                    <span className="truncate">{f.file_name || f.source_file_id}</span>
                    {f.last_error && (
                      <span className="block text-xs text-red-400/80">{f.last_error}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-slate-400">
                    {f.file_size ? formatBytes(f.file_size) : "—"}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs ${
                        STATUS_BADGE[f.status] ?? ""
                      }`}
                    >
                      {f.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-slate-400">{emailOf(f.destination_account_id)}</td>
                  <td className="px-3 py-2 text-slate-400">{f.ai_note ?? "—"}</td>
                </tr>
              ))}
              {items.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-6 text-center text-slate-500">
                    Nothing here yet. Connect an account and pick photos to build the queue.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
