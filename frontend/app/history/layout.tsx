// History segment layout — keeps /history registered as its own App Router tree.
export default function HistoryLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
