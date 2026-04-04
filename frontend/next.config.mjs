/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Django DRF URL patterns require trailing slashes. Next.js rewrites always
  // strip trailing slashes before proxying, which breaks DRF. We use a
  // catch-all API route (app/api/[...path]/route.ts) instead of rewrites —
  // it explicitly preserves trailing slashes when forwarding to Django.
  skipTrailingSlashRedirect: true,
};

export default nextConfig;
