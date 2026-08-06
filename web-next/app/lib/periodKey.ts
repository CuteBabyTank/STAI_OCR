export type TopGranularity = "month" | "year";

export function periodKey(granularity: TopGranularity, now: Date): string {
  const year = now.getFullYear();
  if (granularity === "year") return String(year);
  return `${year}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
