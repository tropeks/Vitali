import { ModuleGate } from '@/components/layout/ModuleGate';

export default async function ConcessaoLayout({ children }: { children: React.ReactNode }) {
  return <ModuleGate module="diagnostic_concession">{children}</ModuleGate>;
}
