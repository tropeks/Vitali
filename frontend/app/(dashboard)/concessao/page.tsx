import Link from 'next/link'
import { ArrowRight, Boxes, FileText, PackageOpen, Truck, TrendingUp } from 'lucide-react'
import PageShell from '@/components/shared/PageShell'

interface AreaCard {
  href: string
  label: string
  description: string
  icon: React.ElementType
}

const AREAS: AreaCard[] = [
  {
    href: '/concessao/ativos',
    label: 'Ativos',
    description: 'Cadastro e ciclo de vida dos equipamentos em comodato junto aos clientes.',
    icon: Boxes,
  },
  {
    href: '/concessao/contratos',
    label: 'Contratos',
    description: 'Termos de concessão, vigência e condições comerciais firmadas por cliente.',
    icon: FileText,
  },
  {
    href: '/concessao/logistica',
    label: 'Logística',
    description: 'Remessas, instalações e retiradas de equipamentos em campo.',
    icon: Truck,
  },
  {
    href: '/concessao/pnl',
    label: 'P&L',
    description: 'Resultado financeiro da operação de concessão: receita, custo e margem.',
    icon: TrendingUp,
  },
]

export default function ConcessaoPage() {
  return (
    <PageShell variant="operational">
      <div className="flex items-center gap-3">
        <PackageOpen className="text-neu-inkSoft" size={28} />
        <div>
          <h1 className="text-xl font-bold text-neu-ink">Concessão</h1>
          <p className="mt-1 text-sm text-neu-inkMuted">
            Gestão do parque de equipamentos cedidos em comodato: ativos, contratos, logística e
            o resultado financeiro (P&L) da operação de concessão.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {AREAS.map((area) => {
          const Icon = area.icon
          return (
            <Link
              key={area.href}
              href={area.href}
              className="group neu-panel flex flex-col gap-2 p-4 transition-shadow hover:shadow-neu-btn"
            >
              <div className="flex items-center gap-2">
                <Icon size={18} className="shrink-0 text-neu-inkSoft" />
                <p className="text-sm font-semibold text-neu-ink">{area.label}</p>
              </div>
              <p className="text-xs text-neu-inkMuted">{area.description}</p>
              <span className="mt-auto inline-flex items-center gap-1 text-xs font-semibold text-neu-inkSoft">
                Acessar
                <ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          )
        })}
      </div>
    </PageShell>
  )
}
