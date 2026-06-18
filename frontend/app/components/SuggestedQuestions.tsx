"use client";
import { motion } from "framer-motion";
import { GraduationCap, KeyRound, Award, FileText, MapPin } from "lucide-react";
import { Card } from "./ui/card";

const SUGGESTIONS = [
  { q: "Siapa Dekan FEB?", Icon: GraduationCap },
  { q: "Bagaimana cara login SIA?", Icon: KeyRound },
  { q: "Apa akreditasi Teknik Informatika?", Icon: Award },
  { q: "Bagaimana cara mengisi KRS?", Icon: FileText },
  { q: "Di mana lokasi kampus Meruya?", Icon: MapPin },
];

export function SuggestedQuestions({ onSelect }: { onSelect: (q: string) => void }) {
  return (
    <div className="mx-auto grid w-full max-w-2xl grid-cols-1 gap-2.5 sm:grid-cols-2">
      {SUGGESTIONS.map(({ q, Icon }, i) => (
        <motion.button
          key={q}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: i * 0.05, duration: 0.25 }}
          onClick={() => onSelect(q)}
          className="text-left"
        >
          <Card className="flex items-center gap-3 p-3 transition-colors hover:border-primary/60 hover:bg-accent">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Icon className="h-4 w-4" />
            </span>
            <span className="text-sm text-foreground">{q}</span>
          </Card>
        </motion.button>
      ))}
    </div>
  );
}
