// Owner-only Profile tab: the on-device record from GET /api/users/{owner_id}, read-only.
import { Suspense } from "react";
import ProfilePage from "@/components/ProfilePage";

export default function ProfileRoute() {
  return (
    <Suspense fallback={<main><p className="muted">Loading…</p></main>}>
      <ProfilePage />
    </Suspense>
  );
}
