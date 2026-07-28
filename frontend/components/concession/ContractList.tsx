'use client'

import Link from 'next/link'
import StatusBadge from '@/components/shared/StatusBadge'
import {
  contractStatusMeta,
  formatBRL,
  formatDate,
  type ConcessionContract,
} from './contractMeta'

interface ContractListProps {
  contracts: ConcessionContract[]
  onEdit: (contract: ConcessionContract) => void
}

const TH = 'px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500'
const TD = 'px-3 py-2 text-sm text-slate-700'

export default function ContractList({ contracts, onEdit }: ContractListProps) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-100">
        <thead className="bg-slate-50">
          <tr>
            <th className={TH}>Contrato</th>
            <th className={TH}>Cliente</th>
            <th className={TH}>Unidades</th>
            <th className={TH}>Valor mensal</th>
            <th className={TH}>Vigência</th>
            <th className={TH}>Status</th>
            <th className={TH}>
              <span className="sr-only">Ações</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {contracts.map((c) => (
            <tr key={c.id} className="hover:bg-slate-50">
              <td className={`${TD} font-medium text-slate-900`}>
                <Link href={`/concessao/contratos/${c.id}`} className="text-neu-brand hover:underline">
                  {c.name}
                </Link>
              </td>
              <td className={TD}>{c.client_name || '—'}</td>
              <td className={TD}>{c.units?.length ?? 0}</td>
              <td className={TD}>{formatBRL(c.monthly_value)}</td>
              <td className={TD}>
                {formatDate(c.start_date)} – {formatDate(c.end_date)}
              </td>
              <td className={TD}>
                <StatusBadge meta={contractStatusMeta(c.status)} />
              </td>
              <td className={`${TD} text-right`}>
                <button
                  type="button"
                  onClick={() => onEdit(c)}
                  className="rounded-lg border border-slate-200 px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-100"
                >
                  Editar
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
