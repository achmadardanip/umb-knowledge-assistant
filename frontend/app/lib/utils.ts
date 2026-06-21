import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** shadcn/ui class merge helper. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Deterministic, locale-independent date formatter (YYYY-MM-DD). Used instead of
 * `toLocaleDateString()` so server- and client-rendered output match exactly —
 * `toLocaleDateString` uses the runtime's default locale, which differs between
 * the Node SSR process and the browser and caused React hydration mismatches.
 */
export function formatDate(value?: string | number | Date | null): string {
  if (value == null) return "—";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "—";
  return d.toISOString().slice(0, 10);
}
