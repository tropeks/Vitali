'use client'

import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Loader2, Search, X } from 'lucide-react'
import { apiFetch } from '@/lib/api'

type Page<T> = { results?: T[]; next?: string | null }

interface Props<T> {
  label: string
  endpoint: string
  value: T | null
  getKey: (item: T) => string
  getLabel: (item: T) => string
  onChange: (item: T | null) => void
  placeholder?: string
  allLabel?: string
  disabled?: boolean
}

export default function RemoteCombobox<T>({
  label, endpoint, value, getKey, getLabel, onChange, placeholder = 'Buscar...',
  allLabel, disabled,
}: Props<T>) {
  const id = useId()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const request = useRef(0)
  const [query, setQuery] = useState('')
  const [items, setItems] = useState<T[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (term: string, nextUrl?: string) => {
    const current = ++request.current
    setLoading(true)
    try {
      const url = nextUrl ?? `${endpoint}${endpoint.includes('?') ? '&' : '?'}search=${encodeURIComponent(term)}&page_size=20`
      const data = await apiFetch<Page<T> | T[]>(url)
      if (current !== request.current) return
      const results = Array.isArray(data) ? data : data.results ?? []
      setItems(previous => nextUrl ? [...previous, ...results] : results)
      setNext(Array.isArray(data) ? null : data.next ?? null)
      setOpen(true)
    } catch {
      if (current !== request.current) return
      setItems([])
      setNext(null)
      setOpen(true)
    } finally {
      if (current === request.current) setLoading(false)
    }
  }, [endpoint])

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  const changeQuery = (term: string) => {
    setQuery(term)
    if (value) onChange(null)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => void load(term), 300)
  }

  const display = value ? getLabel(value) : query

  return (
    <div className="relative">
      <label htmlFor={id} className="sr-only">{label}</label>
      <Search aria-hidden size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
      <input
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-options`}
        aria-autocomplete="list"
        autoComplete="off"
        disabled={disabled}
        value={display}
        placeholder={placeholder}
        onFocus={() => { if (!items.length) void load(query); else setOpen(true) }}
        onChange={event => changeQuery(event.target.value)}
        className="w-full rounded-lg border border-slate-200 py-2 pl-8 pr-9 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-slate-50"
      />
      {loading ? (
        <Loader2 aria-label="Buscando" size={15} className="absolute right-3 top-1/2 -translate-y-1/2 animate-spin text-blue-500" />
      ) : (value || query) ? (
        <button type="button" aria-label={`Limpar ${label}`} onClick={() => { onChange(null); setQuery(''); setOpen(false) }} className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400">
          <X size={14} />
        </button>
      ) : null}
      {open && (
        <div id={`${id}-options`} role="listbox" className="absolute z-50 mt-1 max-h-64 w-full overflow-auto rounded-lg border border-slate-200 bg-white shadow-lg">
          {allLabel && (
            <button type="button" role="option" aria-selected={!value} onMouseDown={event => event.preventDefault()} onClick={() => { onChange(null); setQuery(''); setOpen(false) }} className="w-full px-3 py-2 text-left text-sm hover:bg-blue-50">{allLabel}</button>
          )}
          {items.map(item => (
            <button key={getKey(item)} type="button" role="option" aria-selected={value ? getKey(value) === getKey(item) : false} onMouseDown={event => event.preventDefault()} onClick={() => { onChange(item); setQuery(''); setOpen(false) }} className="w-full px-3 py-2 text-left text-sm hover:bg-blue-50">
              {getLabel(item)}
            </button>
          ))}
          {!loading && items.length === 0 && <p className="px-3 py-2 text-sm text-slate-500">Nenhum resultado encontrado.</p>}
          {next && <button type="button" onClick={() => void load(query, next)} className="w-full border-t px-3 py-2 text-sm font-medium text-blue-600 hover:bg-blue-50">Carregar mais</button>}
        </div>
      )}
    </div>
  )
}
