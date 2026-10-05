import type { Account, SyncStatus } from "../types";
import { api } from "../api";

const STATE_STYLE: Record<string, string> = {
  RUNNING: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  PAUSED: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  IDLE: "bg-slate-500/15 text-slate-300 border-slate-500/30",
};

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`text-lg font-semibold ${tone ?? ""}`}>{value}</p>
    </div>
  );
}

export function ProgressPanel({
  status,
  accounts,
  onChange,
}: {
  status: SyncStatus;
  accounts: Account[];
  onChange: () => void;
}) {
  const t = status.totals;
  const dest = accounts.find((a) => a.id === status.current_destination_account_id);

  async function action(fn: () => Promise<{ message: string }>) {
    const res = await fn();
    if (res.message) console.log(res.message);
    onChange();
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
          Sync progress
        </h2>
        <span
          className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
            STATE_STYLE[status.state]
          }`}
        >
          {status.state}
        </span>
      </div>

      {/* Progress bar */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-slate-400">
          <span>
            {t.synced + t.skipped_duplicate} / {t.total} done
          </span>
          <span>{t.progress_pct}%</span>
        </div>
        <div className="h-3 w-full overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full bg-sky-500 transition-all"
            style={{ width: `${t.progress_pct}%` }}
          />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
        <Stat label="Total" value={t.total} />
        <Stat label="Synced" value={t.synced} tone="text-emerald-400" />
        <Stat label="Remaining" value={t.remaining} tone="text-sky-400" />
        <Stat label="Duplicates" value={t.skipped_duplicate} tone="text-slate-300" />
        <Stat label="Failed" value={t.failed} tone="text-red-400" />
        <Stat label="Processing" value={t.processing} tone="text-amber-400" />
      </div>

      {/* Current file */}
      <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-sm">
        {status.current_file ? (
          <p>
            <span className="text-slate-500">Now syncing:</span>{" "}
            <span className="font-medium">{status.current_file.file_name || "photo"}</span>
            {dest && <span className="text-slate-500"> → {dest.email}</span>}
          </p>
        ) : (
          <p className="text-slate-500">Idle — no file in flight.</p>
        )}
        {status.state === "PAUSED" && status.paused_reason && (
          <p className="mt-1 text-xs text-amber-400">⏸ {status.paused_reason}</p>
        )}
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-2">
        {status.state === "RUNNING" ? (
          <button
            onClick={() => action(api.pause)}
            className="rounded-lg bg-amber-600 px-3 py-1.5 text-sm font-medium hover:bg-amber-500"
          >
            Pause
          </button>
        ) : status.state === "PAUSED" ? (
          <button
            onClick={() => action(api.resume)}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium hover:bg-emerald-500"
          >
            Resume
          </button>
        ) : (
          <button
            onClick={() => action(api.start)}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium hover:bg-emerald-500"
          >
            Start sync
          </button>
        )}
        <button
          onClick={() => action(api.retryFailed)}
          disabled={t.failed === 0}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-800 disabled:opacity-40"
        >
          Retry failed ({t.failed})
        </button>
      </div>
    </div>
  );
}
