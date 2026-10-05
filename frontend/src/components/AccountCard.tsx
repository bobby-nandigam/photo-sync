import { useState } from "react";
import type { Account } from "../types";
import { api } from "../api";
import { StorageBar } from "./StorageBar";

const STATUS_STYLE: Record<string, string> = {
  CONNECTED: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  ERROR: "bg-red-500/15 text-red-300 border-red-500/30",
  DISCONNECTED: "bg-slate-500/15 text-slate-300 border-slate-500/30",
};

export function AccountCard({
  account,
  isCurrentDestination,
  onChange,
}: {
  account: Account;
  isCurrentDestination: boolean;
  onChange: () => void;
}) {
  const [picking, setPicking] = useState<string>("");
  const [busy, setBusy] = useState(false);

  async function pickPhotos() {
    try {
      setBusy(true);
      setPicking("Opening Google Photos picker…");
      const session = await api.createPickerSession(account.id);
      window.open(session.picker_uri, "_blank", "noopener");
      setPicking("Waiting for you to pick photos in the Google tab…");

      // Poll until the user finishes selecting.
      const interval = Math.max(session.poll_interval_seconds, 2) * 1000;
      let done = false;
      for (let i = 0; i < 300 && !done; i++) {
        await new Promise((r) => setTimeout(r, interval));
        const s = await api.pollPickerSession(session.session_id, account.id);
        done = s.media_items_set;
      }
      if (!done) {
        setPicking("Timed out waiting for selection. Try again.");
        return;
      }
      setPicking("Importing your selection…");
      const res = await api.importPicked(account.id, session.session_id);
      setPicking(
        `Added ${res.imported} photo(s) to the queue (${res.already_tracked} already tracked).`
      );
      onChange();
    } catch (e) {
      setPicking(`Error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!confirm(`Disconnect ${account.email}? Tokens will be revoked.`)) return;
    await api.disconnect(account.id);
    onChange();
  }

  async function refresh() {
    setBusy(true);
    try {
      await api.refreshAccount(account.id);
      onChange();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold">{account.email}</p>
          <p className="text-xs text-slate-500">
            Priority {account.priority}
            {account.can_be_destination ? " · destination" : " · source only"}
            {isCurrentDestination && (
              <span className="ml-1 text-sky-400">· receiving now</span>
            )}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${
            STATUS_STYLE[account.status] ?? STATUS_STYLE.DISCONNECTED
          }`}
        >
          {account.status}
        </span>
      </div>

      <StorageBar account={account} />

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          onClick={pickPhotos}
          disabled={busy || account.status !== "CONNECTED"}
          className="rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium hover:bg-sky-500 disabled:opacity-40"
        >
          Select photos to sync
        </button>
        <button
          onClick={refresh}
          disabled={busy}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800 disabled:opacity-40"
        >
          Refresh storage
        </button>
        <button
          onClick={disconnect}
          className="rounded-lg border border-red-900/60 px-3 py-1.5 text-sm text-red-300 hover:bg-red-950/40"
        >
          Disconnect
        </button>
      </div>

      {picking && <p className="text-xs text-slate-400">{picking}</p>}
    </div>
  );
}
