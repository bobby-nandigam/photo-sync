import type { Account } from "../types";
import { formatBytes } from "../api";

export function StorageBar({ account }: { account: Account }) {
  const pct = Math.round(account.storage_fraction * 100);
  const unlimited = account.storage_limit === 0;

  const barColor = account.is_full
    ? "bg-red-500"
    : account.near_full
    ? "bg-amber-400"
    : "bg-emerald-500";

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-slate-400">
        <span>
          {formatBytes(account.storage_usage)} /{" "}
          {unlimited ? "unlimited" : formatBytes(account.storage_limit)}
        </span>
        {!unlimited && <span>{pct}%</span>}
      </div>
      <div className="h-2.5 w-full overflow-hidden rounded-full bg-slate-800">
        <div
          className={`h-full ${barColor} transition-all`}
          style={{ width: `${unlimited ? 0 : pct}%` }}
        />
      </div>
      {account.is_full ? (
        <p className="text-xs font-medium text-red-400">
          ⛔ Full — the router will skip this account.
        </p>
      ) : account.near_full ? (
        <p className="text-xs font-medium text-amber-400">
          ⚠ Nearly full — {formatBytes(account.storage_free)} free left.
        </p>
      ) : (
        <p className="text-xs text-slate-500">{formatBytes(account.storage_free)} free</p>
      )}
    </div>
  );
}
