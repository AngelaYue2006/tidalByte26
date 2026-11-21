// Root layout: large type, high contrast, role picker (owner Mary / contact Sarah) in the header.
import type { Metadata } from "next";
import { Nunito } from "next/font/google";
import { Suspense } from "react";
import Header from "@/components/Header";
import "./globals.css";

const nunito = Nunito({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "LifeLine",
  description: "LifeLine dashboard — live appointment booking trail",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={nunito.variable}>
      <body>
        <div className="wrap">
          <Suspense fallback={<header className="site-header"><span className="brand">LifeLine</span></header>}>
            <Header />
          </Suspense>
          {children}
        </div>
      </body>
    </html>
  );
}
