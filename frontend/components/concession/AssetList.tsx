'use client'

import { StatusBadge } from '@/components/shared'
import {
  ASSET_STATUS_META,
  OWNERSHIP_LABEL,
  formatBRL,
  facilityName,
  type Asset,
  type FacilityOption,
} from './assetMeta'

interface AssetListProps {
  assets: Asset[]
  facilities: FacilityOption[]
  onEdit: (asset: Asset) => void
  onMove: (asset: Asset) => void
  onHistory: (asset: Asset) => void
}

const HEADERS = ['Tag', 'Nome', 'Modelo', 'Status', 'Propriedade', 'Localização', 'Depreciação/mês', '']

export default function AssetList({ assets, facilities, onEdit, onMove, onHistory }: AssetListProps) {
  return (
    <div className="bg-neu-panel rounded-lg border border-white overflow-x-auto">
      <table className="w-full text-sm min-w-[900px]">
        <thead>
          <tr className="border-b border-white bg-neu-panel">
            {HEADERS.map((h, i) => (
              <th
                key={h || `col-${i}`}
                className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wide text-neu-inkMuted"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {assets.map((asset) => (
            <tr key={asset.id} className="border-b border-white hover:bg-neu-panelAlt">
              <td className="px-4 py-3 font-mono text-xs text-neu-ink">{asset.asset_tag}</td>
              <td className="px-4 py-3 font-medium text-neu-ink">{asset.name || '—'}</td>
              <td className="px-4 py-3 text-neu-inkSoft">{asset.model || '—'}</td>
              <td className="px-4 py-3">
                <StatusBadge meta={ASSET_STATUS_META[asset.status]} />
              </td>
              <td className="px-4 py-3 text-neu-inkSoft">{OWNERSHIP_LABEL[asset.ownership]}</td>
              <td className="px-4 py-3 text-neu-inkSoft">
                {facilityName(asset.current_location, facilities)}
              </td>
              <td className="px-4 py-3 text-neu-inkSoft tabular-nums">
                {formatBRL(asset.monthly_depreciation)}
              </td>
              <td className="px-4 py-3">
                <div className="flex gap-2 justify-end">
                  <button
                    type="button"
                    onClick={() => onMove(asset)}
                    className="text-xs font-medium text-neu-brand hover:underline"
                  >
                    Movimentar
                  </button>
                  <button
                    type="button"
                    onClick={() => onHistory(asset)}
                    className="text-xs font-medium text-neu-inkSoft hover:underline"
                  >
                    Histórico
                  </button>
                  <button
                    type="button"
                    onClick={() => onEdit(asset)}
                    className="text-xs font-medium text-neu-inkSoft hover:underline"
                  >
                    Editar
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
