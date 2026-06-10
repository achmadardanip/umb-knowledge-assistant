import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";

export const metadata: Metadata = {
  title: "UMB Knowledge Assistant",
  description: "Asisten informasi publik berbasis sumber resmi Universitas Mercu Buana"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body>
        {children}
        {/* Puter.js: keyless, free in-browser LLM (user-pays model). Powers the "puter" provider. */}
        <Script src="https://js.puter.com/v2/" strategy="afterInteractive" />
      </body>
    </html>
  );
}

