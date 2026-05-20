/**
 * Outer wrapper for everything under /portal/*.
 *
 * Public pages (login, activate) live here directly; protected pages
 * live under (protected)/ with their own auth-checking layout. Both
 * inherit the brand background from this wrapper.
 */
export default function PortalRootLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen bg-slate-50">{children}</div>;
}
