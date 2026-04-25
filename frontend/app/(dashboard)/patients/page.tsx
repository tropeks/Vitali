'use client'

import { useState, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'

export default function PatientsPage() {
  const router = useRouter()
  const [search, setSearch] = useState('')
  const [patients, setPatients] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [count, setCount] = useState(0)

  const fetchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchPatientsNow = useCallback(async (q: string) => {
    setLoading(true)
    try {
      const res = await fetch(`/api/v1/patients?search=${q}&ordering=full_name`)
      const data = await res.json()
      setPatients(data.results ?? [])
      setCount(data.count ?? 0)
    } finally { setLoading(false) }
  }, [])

  const fetchPatients = useCallback((q: string) => {
    if (fetchTimerRef.current) clearTimeout(fetchTimerRef.current)
    fetchTimerRef.current = setTimeout(() => fetchPatientsNow(q), 300)
  }, [fetchPatientsNow])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Pacientes</h1>
          <p className="text-sm text-gray-500 mt-1">{count} paciente{count !== 1 ? 's' : ''}</p>
        </div>
        <button onClick={() => router.push('/patients/new')}
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
          + Novo Paciente
        </button>
      </div>
      <input type="text" placeholder="Buscar por nome, prontuário, WhatsApp..."
        className="w-full px-4 py-2.5 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        value={search} onChange={e => { setSearch(e.target.value); fetchPatients(e.target.value) }} />
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              {['Paciente','Prontuário','Nasc.','Telefone','Alergias','Status'].map(h => (
                <th key={h} className="text-left px-4 py-3 font-medium text-gray-600">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading ? (
              Array.from({length:5}).map((_,i) => (
                <tr key={i}><td colSpan={6} className="px-4 py-3">
                  <div className="h-4 bg-gray-100 rounded animate-pulse w-3/4"/>
                </td></tr>
              ))
            ) : patients.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-12 text-center text-gray-400">
                {search ? 'Nenhum resultado.' : 'Nenhum paciente cadastrado ainda.'}
              </td></tr>
            ) : patients.map((p: any) => (
              <tr key={p.id} className="hover:bg-blue-50 cursor-pointer"
                onClick={() => router.push(`/patients/${p.id}`)}>
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{p.full_name}</div>
                  {p.social_name && <div className="text-xs text-gray-400">({p.social_name})</div>}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-gray-600">{p.medical_record_number}</td>
                <td className="px-4 py-3 text-gray-600">
                  {p.birth_date ? new Date(p.birth_date+'T00:00:00').toLocaleDateString('pt-BR') : '—'}
                  {p.age != null && <span className="text-xs text-gray-400 ml-1">({p.age}a)</span>}
                </td>
                <td className="px-4 py-3 text-gray-600">{p.phone || p.whatsapp || '—'}</td>
                <td className="px-4 py-3">
                  {p.active_allergies_count > 0
                    ? <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">{p.active_allergies_count} alergia{p.active_allergies_count !== 1 ? 's' : ''}</span>
                    : <span className="text-gray-400">—</span>}
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs ${p.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                    {p.is_active ? 'Ativo' : 'Inativo'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
