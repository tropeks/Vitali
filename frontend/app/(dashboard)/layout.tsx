import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import DashboardShell from "@/components/layout/DashboardShell";
import type { UserDTO } from "@/lib/auth";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = cookies();
  const raw = cookieStore.get("vitali_user")?.value;

  if (!raw) {
    redirect("/login");
  }

  let user: UserDTO | null = null;
  try {
    user = JSON.parse(raw) as UserDTO;
  } catch {
    redirect("/login");
  }

  if (!user?.id) {
    redirect("/login");
  }

  return <DashboardShell user={user}>{children}</DashboardShell>;
}
