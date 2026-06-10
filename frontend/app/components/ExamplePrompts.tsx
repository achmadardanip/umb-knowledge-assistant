"use client";

import { useEffect, useState } from "react";

const FALLBACK_PROMPTS = [
  "Bagaimana cara daftar mahasiswa baru di UMB?",
  "Berapa biaya kuliah di Universitas Mercu Buana?",
  "Apa saja program studi yang tersedia di UMB?",
  "Bagaimana cara login SSO dan SIA UMB?",
  "Di mana informasi perpustakaan UMB?",
  "Apa saja beasiswa yang tersedia di UMB?"
];

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function ExamplePrompts({ onPick }: { onPick: (prompt: string) => void }) {
  const [prompts, setPrompts] = useState<string[]>(FALLBACK_PROMPTS);

  useEffect(() => {
    let active = true;
    fetch(`${API_BASE}/faq/top?limit=6`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data && Array.isArray(data.questions) && data.questions.length > 0) {
          setPrompts(data.questions.slice(0, 6));
        }
      })
      .catch(() => {
        /* keep curated fallback when offline */
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {prompts.map((prompt) => (
        <button key={prompt} className="rounded border border-line bg-white px-3 py-3 text-left text-sm transition hover:border-brand" type="button" onClick={() => onPick(prompt)}>
          {prompt}
        </button>
      ))}
    </div>
  );
}
