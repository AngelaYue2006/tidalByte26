// Root layout: expressive type, colorful wash, role picker in the header.
import type { Metadata } from "next";
import { Fraunces, Outfit } from "next/font/google";
import { Suspense } from "react";
import Header from "@/components/Header";
import "./globals.css";

const outfit = Outfit({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

const fraunces = Fraunces({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-display",
});

export const metadata: Metadata = {
  title: "LifeLine",
  description: "LifeLine dashboard — live appointment booking trail",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${outfit.variable} ${fraunces.variable}`}>
      <body>
        <div className="bg-blobs" aria-hidden>
          <span className="blob blob-a" />
          <span className="blob blob-b" />
          <span className="blob blob-c" />
        </div>
        <div className="wrap">
          <Suspense
            fallback={
              <header className="site-header">
                <span className="brand">LifeLine</span>
              </header>
            }
          >
            <Header />
          </Suspense>
          {children}
        </div>
      </body>
    </html>
  );
}
