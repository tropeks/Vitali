/**
 * Auth gate for every /portal/* protected page.
 *
 * Server-side check: the user must have a `vitali_user` cookie (set on
 * login) AND a `PatientPortalAccess` row in `active` state. The second
 * check happens implicitly when the page renders — calling
 * `portalApi.getMyProfile()` server-side would also do, but the existing
 * dashboard pattern is "check cookie here, let each page re-fetch its
 * data client-side", and we mirror that for parity.
 *
 * A staff user with no PatientPortalAccess will pass the cookie check
 * but every `/portal/me/*` call will return 403, and the client-side
 * api helper redirects to `/portal/login`.
 */

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import PortalShell from "@/components/portal/PortalShell";
import type { UserDTO } from "@/lib/auth";

export default async function PortalProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const cookieStore = await cookies();
  const raw = cookieStore.get("vitali_user")?.value;
  if (!raw) {
    redirect("/portal/login");
  }

  let user: UserDTO | null = null;
  try {
    user = JSON.parse(raw) as UserDTO;
  } catch {
    redirect("/portal/login");
  }

  if (!user?.id) {
    redirect("/portal/login");
  }

  return <PortalShell userName={user.full_name || "Paciente"}>{children}</PortalShell>;
}
