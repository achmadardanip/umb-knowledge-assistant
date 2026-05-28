"use client";

const PROMPTS = [
  "Bagaimana cara daftar mahasiswa baru?",
  "Apa itu SSO Universitas Mercu Buana?",
  "Bagaimana jika tidak bisa login SIA?",
  "Di mana informasi perpustakaan UMB?",
  "Apa saja program akademik yang tersedia?"
];

export function ExamplePrompts({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {PROMPTS.map((prompt) => (
        <button key={prompt} className="rounded border border-line bg-white px-3 py-3 text-left text-sm transition hover:border-brand" onClick={() => onPick(prompt)}>
          {prompt}
        </button>
      ))}
    </div>
  );
}

