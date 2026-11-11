// How durations, ages and shares read on screen. A leaf module: it imports nothing.

/** A duration as "840 ms", "2.4 s" or "1 min 5 s". */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) {
    const s = ms / 1000;
    return `${s < 10 ? s.toFixed(1) : Math.round(s)} s`;
  }
  const total = Math.round(ms / 1000);
  return `${Math.floor(total / 60)} min ${total % 60} s`;
}

/** An age as "12 min", "5 h" or "3 d". */
export function formatAge(ms: number): string {
  const min = Math.max(0, Math.floor(ms / 60_000));
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  return h < 48 ? `${h} h` : `${Math.floor(h / 24)} d`;
}

/** A share as "43%". */
export const formatPercent = (share: number) => `${Math.round(share * 100)}%`;

/** A failure category as words: "infra_error" reads "Infra error". */
export function formatCategory(category: string): string {
  const words = category.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
