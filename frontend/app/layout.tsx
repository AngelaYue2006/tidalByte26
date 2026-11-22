import type { Metadata } from "next";
import { Suspense } from "react";
import Header from "@/components/Header";
import "./globals.css";
import "./studio.css";

export const metadata: Metadata = {
  title: "LifeLine",
  description: "LifeLine dashboard — live appointment booking trail",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Suspense
          fallback={
            <header className="site-header">
              <span className="brand">LifeLine</span>
            </header>
          }
        >
          <Header />
        </Suspense>
        <div className="wrap">{children}</div>
      </body>
    </html>
  );
}
