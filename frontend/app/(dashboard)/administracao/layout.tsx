import AdminTabs from '@/components/admin/AdminTabs'

export default function AdministrationLayout({ children }: { children: React.ReactNode }) {
  return <div className="space-y-5"><AdminTabs />{children}</div>
}
