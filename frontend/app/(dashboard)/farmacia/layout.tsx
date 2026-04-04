'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const TABS = [
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
        <h1 className="text-2xl font-semibold text-gray-900">Farmácia</h1>
        <p className="text-sm text-gray-500 mt-1">Catálogo, estoque e dispensação</p>
      </div>
      <nav className="flex gap-1 border-b border-gray-200">
        {TABS.map(tab => (
          <Link
            key={tab.href}
            href={tab.href}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              pathname.startsWith(tab.href)
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab.label}
          </Link>
        ))}
      </nav>
      <div>{children}</div>
    </div>
  )
}
