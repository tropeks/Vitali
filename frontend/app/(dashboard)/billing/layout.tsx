import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import type { UserDTO } from '@/lib/auth';

export default function BillingLayout({ children }: { children: React.ReactNode }) {
  const cookieStore = cookies();
  const raw = cookieStore.get('vitali_user')?.value;

  if (!raw) {
    redirect('/login');
  }

  let user: UserDTO | null = null;
  try {
    user = JSON.parse(raw) as UserDTO;
  } catch {
    redirect('/login');
  }

  if (!user?.id) {
    redirect('/login');
  }

  if (!user.active_modules.includes('billing')) {
    redirect('/dashboard');
  }

  return <div>{children}</div>;
}
