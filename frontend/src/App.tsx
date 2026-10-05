import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { FileRow, SyncStatus } from "./types";
import { AccountCard } from "./components/AccountCard";
import { ProgressPanel } from "./components/ProgressPanel";
import { QueueTable } from "./components/QueueTable";

export default function App() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [queue, setQueue] = useState<{ items: FileRow[]; total: number }>({ items: [], total: 0 });
  const [filter, setFilter] = useState("");
  const [toast, setToast] = useState<string>("");
  const [error, setError] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      const [s, q] = await Promise.all([api.status(), api.queue(filter || undefined)]);
      setStatus(s);
      setQueue(q);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }, [filter]);

  // Initial + polling
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 2500);
    return () => clearInterval(id);
  }, [refresh]);

  // One-time: surface ?connected / ?error from the OAuth redirect.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("connected")) setToast(`Connected ${p.get("connected")}`);
    if (p.get("error")) setToast(`Connect failed: ${p.get("error")}`);
    if (p.get("connected") || p.get("error")) {
      window.history.replaceState({}, "", window.location.pathname);
      setTimeout(() => setToast(""), 5000);
    }
  }, []);

  const accounts = status?.accounts ?? [];
  const canAddMore = accounts.length < 3;

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Multi-Gmail Photo Sync Router</h1>
          <p className="text-sm text-slate-400">
            Resumable, storage-aware sync across up to 3 Google accounts.
          </p>
        </div>
        <button
          onClick={() => api.connect()}
          disabled={!canAddMore}
          className="rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium hover:bg-sky-500 disabled:opacity-40"
          title={canAddMore ? "" : "Maximum of 3 accounts"}
        >
          + Connect Google account
        </button>
      </header>

      {toast && (
        <div className="mb-4 rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-2 text-sm text-sky-200">
          {toast}
        </div>
      )}
      {error && (
        <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-200">
          Backend error: {error}
        </div>
      )}

      {status && (
        <div className="space-y-6">
          <ProgressPanel status={status} accounts={accounts} onChange={refresh} />

          <section>
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-400">
              Connected accounts ({accounts.length}/3)
            </h2>
            {accounts.length === 0 ? (
              <div className="rounded-xl border border-dashed border-slate-700 bg-slate-900/40 p-8 text-center text-slate-400">
                No accounts yet. Click <b>Connect Google account</b> to begin.
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {accounts.map((a) => (
                  <AccountCard
                    key={a.id}
                    account={a}
                    isCurrentDestination={a.id === status.current_destination_account_id}
                    onChange={refresh}
                  />
                ))}
              </div>
            )}
          </section>

          <QueueTable
            items={queue.items}
            accounts={accounts}
            total={queue.total}
            filter={filter}
            onFilter={setFilter}
          />
        </div>
      )}

      {!status && !error && (
        <p className="text-slate-400">Loading…</p>
      )}
    </div>
  );
}
