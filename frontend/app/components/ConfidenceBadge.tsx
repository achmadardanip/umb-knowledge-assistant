"use client";
import { ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { cn } from "../lib/utils";

type Level = "high" | "medium" | "low" | null | undefined;

const MAP: Record<string, { label: string; pct: number; variant: "success" | "warning" | "error"; Icon: typeof ShieldCheck }> = {
  high: { label: "High Confidence", pct: 96, variant: "success", Icon: ShieldCheck },
  medium: { label: "Medium Confidence", pct: 70, variant: "warning", Icon: ShieldAlert },
  low: { label: "Low Confidence", pct: 35, variant: "error", Icon: ShieldQuestion },
};

export function ConfidenceBadge({ level, withBar = false, className }: { level: Level; withBar?: boolean; className?: string }) {
  if (!level) return null;
  const c = MAP[level];
  if (!c) return null;
  const indicator = c.variant === "success" ? "bg-success" : c.variant === "warning" ? "bg-warning" : "bg-destructive";
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <Badge variant={c.variant}>
        <c.Icon className="h-3 w-3" />
        {c.label} · {c.pct}%
      </Badge>
      {withBar && <Progress value={c.pct} indicatorClassName={indicator} className="h-1.5 w-20" />}
    </div>
  );
}
