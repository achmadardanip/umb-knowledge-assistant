"use client";
import * as React from "react";
import { motion } from "framer-motion";
import { Search, Network, FileSearch, Sparkles, Check, Loader2 } from "lucide-react";
import { Skeleton } from "./ui/skeleton";

const STAGES = [
  { label: "Searching knowledge base…", Icon: Search },
  { label: "Resolving entities…", Icon: Network },
  { label: "Retrieving official sources…", Icon: FileSearch },
  { label: "Generating response…", Icon: Sparkles },
];

/** Animated staged loader shown while the assistant is thinking. */
export function RetrievalLoading() {
  const [stage, setStage] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), 1200);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        {STAGES.map(({ label, Icon }, i) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: i <= stage ? 1 : 0.4, x: 0 }}
            className="flex items-center gap-2 text-sm"
          >
            <span className={i < stage ? "text-success" : i === stage ? "text-primary" : "text-muted-foreground"}>
              {i < stage ? <Check className="h-4 w-4" /> : i === stage ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
            </span>
            <span className={i <= stage ? "text-foreground" : "text-muted-foreground"}>{label}</span>
          </motion.div>
        ))}
      </div>
      <div className="space-y-2 pt-1">
        <Skeleton className="h-3 w-[90%]" />
        <Skeleton className="h-3 w-[80%]" />
        <Skeleton className="h-3 w-[60%]" />
      </div>
    </div>
  );
}
