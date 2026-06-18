'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const TABS = [
  { label: 'Cockpit', href: '/farmacia' },
  { label: 'Dispensar', href: '/farmacia/dispense' },
  { label: 'Estoque', href: '/farmacia/stock' },
  { label: 'Catálogo', href: '/farmacia/catalog' },
  { label: 'Compras', href: '/farmacia/compras' },
]

export default function FarmaciaLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#24292F]">Farmácia</h1>
        <p className="text-sm text-[#8C959F] mt-1">Catálogo, estoque e dispensação</p>
      </div>
      <nav className="flex gap-1 overflow-x-auto border-b border-slate-200 whitespace-nowrap">
        {TABS.map(tab => {
          const active = tab.href === '/farmacia'
            ? pathname === '/farmacia'
            : pathname.startsWith(tab.href)
          return (
            <Link
              key={tab.href}
              href={tab.href}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                active
                  ? 'border-blue-600 text-[#0066A1]'
                  : 'border-transparent text-[#8C959F] hover:text-[#57606A]'
              }`}
            >
              {tab.label}
            </Link>
          )
        })}
      </nav>
      <div>{children}</div>
    </div>
  )
}
