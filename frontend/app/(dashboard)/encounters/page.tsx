'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { format } from 'date-fns';
import { ptBR } from 'date-fns/locale';

interface Encounter {
  id: string;
  patient: string;
  patient_name: string;
  patient_mrn: string;
  professional: string;
  professional_name: string;
  encounter_date: string;
  status: 'open' | 'signed' | 'cancelled';
  status_display: string;
  chief_complaint: string;
}

const STATUS_STYLES: Record<string, string> = {
  open: 'bg-yellow-100 text-yellow-800',
  signed: 'bg-green-100 text-green-800',
  cancelled: 'bg-gray-100 text-gray-500',
};

async function apiFetch(path: string) {
  const token = localStorage.getItem('access_token');
  const res = await fetch(`/api/v1${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

async function apiPost(path: string, body: Record<string, unknown>) {
  const token = localStorage.getItem('access_token');
  const res = await fetch(`/api/v1${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

export default function EncountersPage() {
  const router = useRouter();
  const [encounters, setEncounters] = useState<Encounter[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [dateFilter, setDateFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [patients, setPatients] = useState<{ id: string; full_name: string; medical_record_number: string }[]>([]);
  const [professionals, setProfessionals] = useState<{ id: string; user_name: string }[]>([]);
  const [form, setForm] = useState({ patient: '', professional: '', chief_complaint: '' });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter) params.set('status', statusFilter);
      if (dateFilter) params.set('date', dateFilter);
      const data = await apiFetch(`/encounters/?${params}`);
      setEncounters(Array.isArray(data) ? data : data.results ?? []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [statusFilter, dateFilter]);

  useEffect(() => { load(); }, [load]);

  const openModal = async () => {
    setShowModal(true);
    try {
      const [pats, profs] = await Promise.all([
        apiFetch('/patients/?page_size=200'),
        apiFetch('/professionals/'),
      ]);
      setPatients(Array.isArray(pats) ? pats : pats.results ?? []);
      setProfessionals(Array.isArray(profs) ? profs : profs.results ?? []);
    } catch { /* ignore */ }
  };

  const createEncounter = async () => {
    if (!form.patient || !form.professional) return;
    setSaving(true);
    try {
      const enc = await apiPost('/encounters/', form);
      setShowModal(false);
      setForm({ patient: '', professional: '', chief_complaint: '' });
      router.push(`/encounters/${enc.id}`);
    } catch {
      alert('Erro ao criar consulta');
    } finally { setSaving(false); }
  };

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Consultas</h1>
        <button
          onClick={openModal}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 text-sm font-medium"
        >
          + Nova Consulta
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={statusFilter}
          onChange={e => setStatusFilter(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
        >
          <option value="">Todos os status</option>
          <option value="open">Em Aberto</option>
          <option value="signed">Assinada</option>
          <option value="cancelled">Cancelada</option>
        </select>
        <input
          type="date"
          value={dateFilter}
          onChange={e => setDateFilter(e.target.value)}
          className="border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
        />
        {(statusFilter || dateFilter) && (
          <button
            onClick={() => { setStatusFilter(''); setDateFilter(''); }}
            className="text-sm text-gray-500 hover:text-gray-700 underline"
          >
            Limpar filtros
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden shadow-sm">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Paciente', 'Profissional', 'Data', 'Status', 'Queixa Principal'].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={5} className="text-center py-10 text-gray-400 text-sm">Carregando...</td></tr>
            ) : encounters.length === 0 ? (
              <tr><td colSpan={5} className="text-center py-10 text-gray-400 text-sm">Nenhuma consulta encontrada</td></tr>
            ) : encounters.map(enc => (
              <tr
                key={enc.id}
                onClick={() => router.push(`/encounters/${enc.id}`)}
                className="hover:bg-blue-50 cursor-pointer transition-colors"
              >
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900 text-sm">{enc.patient_name}</div>
                  <div className="text-xs text-gray-400">{enc.patient_mrn}</div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-700">{enc.professional_name}</td>
                <td className="px-4 py-3 text-sm text-gray-600">
                  {format(new Date(enc.encounter_date), "dd/MM/yyyy HH:mm", { locale: ptBR })}
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-flex px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[enc.status] ?? ''}`}>
                    {enc.status_display}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600 max-w-xs truncate">{enc.chief_complaint || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* New Encounter Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-900">Nova Consulta</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Paciente *</label>
                <select
                  value={form.patient}
                  onChange={e => setForm(f => ({ ...f, patient: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                >
                  <option value="">Selecione o paciente...</option>
                  {patients.map(p => (
                    <option key={p.id} value={p.id}>{p.full_name} — {p.medical_record_number}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Profissional *</label>
                <select
                  value={form.professional}
                  onChange={e => setForm(f => ({ ...f, professional: e.target.value }))}
                  className="w-full border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 outline-none"
                >
                  <option value="">Selecione o profissional...</option>
                  {professionals.map(p => (
                    <option key={p.id} value={p.id}>{p.user_name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Queixa principal</label>
                <textarea
                  value={form.chief_complaint}
                  onChange={e => setForm(f => ({ ...f, chief_complaint: e.target.value }))}
                  rows={2}
                  className="w-full border rounded-lg px-3 py-2 text-sm resize-none focus:ring-2 focus:ring-blue-500 outline-none"
                  placeholder="Motivo da consulta..."
                />
              </div>
            </div>
            <div className="flex gap-2 justify-end pt-2">
              <button
                onClick={() => setShowModal(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800"
              >
                Cancelar
              </button>
              <button
                onClick={createEncounter}
                disabled={!form.patient || !form.professional || saving}
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {saving ? 'Criando...' : 'Criar Consulta'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
