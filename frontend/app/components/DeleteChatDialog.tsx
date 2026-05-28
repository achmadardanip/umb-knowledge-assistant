"use client";

export function DeleteChatDialog({ title, onCancel, onConfirm }: { title: string; onCancel: () => void; onConfirm: () => void }) {
  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-black/20 p-4">
      <div className="w-full max-w-sm rounded border border-line bg-white p-4 shadow-lg">
        <h2 className="mb-2 text-base font-semibold">Hapus Chat</h2>
        <p className="mb-4 text-sm text-neutral-700">Chat "{title}" akan diarsipkan dari daftar riwayat.</p>
        <div className="flex justify-end gap-2">
          <button className="rounded border border-line px-3 py-2 text-sm" onClick={onCancel}>
            Batal
          </button>
          <button className="rounded bg-red-700 px-3 py-2 text-sm text-white" onClick={onConfirm}>
            Hapus
          </button>
        </div>
      </div>
    </div>
  );
}

