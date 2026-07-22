'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

const tabs = [
  ['/administracao/organizacao', 'Estrutura organizacional'],
  ['/administracao/mpi', 'Identidade de pacientes'],
  ['/administracao/aprovacoes', 'Aprovações'],
  ['/administracao/compras', 'Conciliação de compras'],
] as const

export default function AdminTabs() {
  const pathname = usePathname()
  return (
    <nav aria-label="Seções da administração" className="flex flex-wrap gap-2">
      {tabs.map(([href, label]) => (
        <Link key={href} href={href} className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${pathname === href ? 'border-neu-brand/30 bg-neu-brand/10 text-neu-brand shadow-neu-inset' : 'border-white bg-neu-panel text-neu-inkSoft shadow-neu-panel hover:text-neu-ink'}`}>
          {label}
        </Link>
      ))}
    </nav>
  )
}
