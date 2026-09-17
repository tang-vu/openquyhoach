import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OpenQuyHoach — Vietnam planning data",
  description:
    "Open, provenance-first planning-data infrastructure for Vietnam. Every geometry traces to its source.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
