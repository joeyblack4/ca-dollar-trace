import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CA Dollar Trace",
  description:
    "Follow your California tax dollar — and see exactly where the trail goes dark. Every number cited to its government source.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrains.variable}`}>
      <body className="min-h-screen antialiased">
        <header className="border-b border-rule">
          <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
            <Link href="/" className="font-semibold tracking-tight">
              CA <span className="text-poppy">Dollar</span> Trace
            </Link>
            <div className="flex gap-5 text-sm text-fog">
              <Link href="/grants/" className="hover:text-ink">
                Grants
              </Link>
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl px-6 py-10">{children}</main>
        <footer className="border-t border-rule">
          <div className="mx-auto max-w-5xl px-6 py-6 text-xs text-fog">
            Every number on this site links to its government source and shows when it was
            published. Where the data ends, we say so — a gap is never shown as a zero.
          </div>
        </footer>
      </body>
    </html>
  );
}
