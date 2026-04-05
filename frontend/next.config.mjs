// @ts-check
import { withSentryConfig } from "@sentry/nextjs";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Django DRF URL patterns require trailing slashes. Next.js rewrites always
  // strip trailing slashes before proxying, which breaks DRF. We use a
  // catch-all API route (app/api/[...path]/route.ts) instead of rewrites —
  // it explicitly preserves trailing slashes when forwarding to Django.
  skipTrailingSlashRedirect: true,
};

export default withSentryConfig(nextConfig, {
  // Sentry organization and project (set in CI or .env.local for local builds).
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,

  // Auth token for uploading source maps — required for readable stack traces.
  // Set SENTRY_AUTH_TOKEN in GitHub Secrets / .env.local.
  authToken: process.env.SENTRY_AUTH_TOKEN,

  // Upload source maps to Sentry and delete them from the build output so they
  // are not served publicly (prevents reverse-engineering of client code).
  hideSourceMaps: true,

  // Suppress verbose Sentry CLI output during builds.
  silent: true,

  // Automatically create Sentry releases tied to the git commit SHA.
  // This powers "Suspect Commits" in the Sentry UI.
  automaticVercelMonitors: false,
});
