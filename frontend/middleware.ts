import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Free ngrok returns an interstitial HTML page for browser User-Agents unless
 * this header is present. The Next rewrite forwards request headers upstream,
 * so EventSource and fetch to /api/* both need it or Set-Cookie never lands.
 */
export function middleware(request: NextRequest) {
  const headers = new Headers(request.headers);
  headers.set("ngrok-skip-browser-warning", "1");
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: "/api/:path*",
};
