import { ModuleGate } from '@/components/layout/ModuleGate';

export default async function BillingLayout({ children }: { children: React.ReactNode }) {
  return <ModuleGate module="billing">{children}</ModuleGate>;
}
