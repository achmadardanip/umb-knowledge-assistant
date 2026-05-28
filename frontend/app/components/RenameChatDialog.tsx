"use client";

import { useState } from "react";

export function RenameChatDialog({ currentTitle, onCancel, onConfirm }: { currentTitle: string; onCancel: () => void; onConfirm: (title: string) => void }) {
  const [title, setTitle] = useState(currentTitle);
  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-black/20 p-4">
      <div className="w-full max-w-sm rounded border border-line bg-white p-4 shadow-lg">
        <h2 className="mb-3 text-base font-semibold">Ganti Nama Chat</h2>
        <input className="mb-4 w-full rounded border border-line px-3 py-2 outline-none focus:border-brand" value={title} onChange={(event) => setTitle(event.target.value)} />
        <div className="flex justify-end gap-2">
          <button className="rounded border border-line px-3 py-2 text-sm" onClick={onCancel}>
            Batal
          </button>
          <button className="rounded bg-brand px-3 py-2 text-sm text-white" onClick={() => onConfirm(title)}>
            Simpan
          </button>
        </div>
      </div>
    </div>
  );
}

