"use client";

import { useEffect, useState } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Overview {
  today: {
    appointments_total: number;
    appointments_completed: number;
    appointments_waiting: number;
    appointments_cancelled: number;
    new_patients: number;
    encounters_open: number;
    encounters_signed: number;
  };
  month: {
    appointments_total: number;
    new_patients: number;
    encounters_signed: number;
    cancellation_rate: number;
  };
}

interface DayRow {
  date: string;
  total: number;
  completed: number;
  cancelled: number;
}

interface StatusRow {
  status: string;
  label: string;
  count: number;
}

interface MonthRow {
  month: string;
  label: string;
  count: number;
}

interface Professional {
  professional_id: string;
  name: string;
  specialty: string;
  completed: number;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const PIE_COLORS = [
  "#3b82f6", // blue-500
  "#22c55e", // green-500
  "#facc15", // yellow-400
  "#f87171", // red-400
  "#a78bfa", // violet-400
  "#fb923c", // orange-400
  "#94a3b8", // slate-400
];

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KPICard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: number | string;
  sub?: string;
  color: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-gray-200 rounded ${className ?? ""}`} />
  );
}

function KPISkeleton() {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm space-y-3">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-9 w-20" />
      <Skeleton className="h-3 w-40" />
    </div>
  );
}

function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div
      className="animate-pulse bg-gray-200 rounded-xl"
      style={{ height }}
    />
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [byDay, setByDay] = useState<DayRow[]>([]);
  const [byStatus, setByStatus] = useState<StatusRow[]>([]);
  const [byMonth, setByMonth] = useState<MonthRow[]>([]);
  const [professionals, setProfessionals] = useState<Professional[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = async () => {
    const token =
      typeof window !== "undefined"
        ? localStorage.getItem("access_token")
        : null;
    if (!token) {
      setError("Sessão expirada. Faça login novamente.");
      setLoading(false);
      return;
    }

    const headers = { Authorization: `Bearer ${token}` };

    try {
      const [ovRes, dayRes, statusRes, monthRes, proRes] = await Promise.all([
        fetch(`${API_BASE}/api/v1/analytics/overview/`, { headers }),
        fetch(`${API_BASE}/api/v1/analytics/appointments-by-day/?days=30`, {
          headers,
        }),
        fetch(`${API_BASE}/api/v1/analytics/appointments-by-status/`, {
          headers,
        }),
        fetch(`${API_BASE}/api/v1/analytics/patients-by-month/?months=6`, {
          headers,
        }),
        fetch(`${API_BASE}/api/v1/analytics/top-professionals/?limit=5`, {
          headers,
        }),
      ]);

      if (!ovRes.ok) throw new Error("Falha ao carregar dados");

      const [ovData, dayData, statusData, monthData, proData] =
        await Promise.all([
          ovRes.json(),
          dayRes.json(),
          statusRes.json(),
          monthRes.json(),
          proRes.json(),
        ]);

      setOverview(ovData);
      setByDay(dayData);
      setByStatus(statusData);
      setByMonth(monthData);
      setProfessionals(proData);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erro desconhecido");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 60_000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const dateLabel = new Date().toLocaleDateString("pt-BR", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  if (!loading && error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-slate-500 text-sm mt-1">{dateLabel}</p>
        </div>
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl p-5">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* ── Header ── */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
        <p className="text-slate-500 text-sm mt-1">
          Visão geral do dia — {dateLabel}
        </p>
      </div>

      {/* ── KPI Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => <KPISkeleton key={i} />)
        ) : (
          <>
            <KPICard
              label="Consultas Hoje"
              value={overview?.today.appointments_total ?? 0}
              sub={`${overview?.today.appointments_completed ?? 0} concluídas · ${overview?.today.appointments_waiting ?? 0} aguardando`}
              color="text-blue-500"
            />
            <KPICard
              label="Pacientes Aguardando"
              value={overview?.today.appointments_waiting ?? 0}
              sub={`${overview?.today.appointments_cancelled ?? 0} cancelamentos hoje`}
              color="text-yellow-500"
            />
            <KPICard
              label="Novas Consultas Mês"
              value={overview?.month.appointments_total ?? 0}
              sub={`${overview?.month.new_patients ?? 0} novos pacientes`}
              color="text-green-500"
            />
            <KPICard
              label="Taxa de Cancelamento"
              value={`${overview?.month.cancellation_rate ?? 0}%`}
              sub="No mês atual"
              color="text-red-500"
            />
          </>
        )}
      </div>

      {/* ── Charts Row 1: Line + Donut ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Line chart — Consultas por Dia */}
        <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <h2 className="font-semibold text-slate-900 mb-4">
            Consultas por Dia{" "}
            <span className="text-xs text-slate-400 font-normal">
              (últimos 30 dias)
            </span>
          </h2>
          {loading ? (
            <ChartSkeleton height={240} />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart
                data={byDay}
                margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                  tickFormatter={(v: string) => {
                    const d = new Date(v + "T00:00:00");
                    return `${d.getDate()}/${d.getMonth() + 1}`;
                  }}
                  interval={4}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                  allowDecimals={false}
                />
                <Tooltip
                  labelFormatter={(v: string) =>
                    new Date(v + "T00:00:00").toLocaleDateString("pt-BR")
                  }
                />
                <Legend
                  wrapperStyle={{ fontSize: 12 }}
                  formatter={(value: string) =>
                    value === "total"
                      ? "Total"
                      : value === "completed"
                      ? "Concluídas"
                      : "Canceladas"
                  }
                />
                <Line
                  type="monotone"
                  dataKey="total"
                  stroke="#3b82f6"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="completed"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="cancelled"
                  stroke="#f87171"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Donut chart — Status das Consultas */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <h2 className="font-semibold text-slate-900 mb-4">
            Status das Consultas{" "}
            <span className="text-xs text-slate-400 font-normal">
              (mês atual)
            </span>
          </h2>
          {loading ? (
            <ChartSkeleton height={240} />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie
                  data={byStatus}
                  dataKey="count"
                  nameKey="label"
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={90}
                  paddingAngle={2}
                >
                  {byStatus.map((_, idx) => (
                    <Cell
                      key={idx}
                      fill={PIE_COLORS[idx % PIE_COLORS.length]}
                    />
                  ))}
                </Pie>
                <Tooltip formatter={(value: number) => [value, "Consultas"]} />
                <Legend
                  wrapperStyle={{ fontSize: 11 }}
                  iconType="circle"
                  iconSize={8}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Charts Row 2: Bar + Table ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Bar chart — Novos Pacientes por Mês */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <h2 className="font-semibold text-slate-900 mb-4">
            Novos Pacientes por Mês{" "}
            <span className="text-xs text-slate-400 font-normal">
              (últimos 6 meses)
            </span>
          </h2>
          {loading ? (
            <ChartSkeleton height={220} />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={byMonth}
                margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                  allowDecimals={false}
                />
                <Tooltip formatter={(value: number) => [value, "Pacientes"]} />
                <Bar
                  dataKey="count"
                  name="Pacientes"
                  fill="#3b82f6"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Table — Top Profissionais */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <h2 className="font-semibold text-slate-900 mb-4">
            Top Profissionais{" "}
            <span className="text-xs text-slate-400 font-normal">
              (consultas concluídas este mês)
            </span>
          </h2>
          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100">
                    <th className="text-left py-2 pr-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                      Profissional
                    </th>
                    <th className="text-left py-2 pr-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                      Especialidade
                    </th>
                    <th className="text-right py-2 text-xs font-medium text-gray-500 uppercase tracking-wide">
                      Concluídas
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {professionals.length === 0 ? (
                    <tr>
                      <td
                        colSpan={3}
                        className="py-6 text-center text-gray-400 text-sm"
                      >
                        Nenhum dado disponível
                      </td>
                    </tr>
                  ) : (
                    professionals.map((p) => (
                      <tr key={p.professional_id} className="hover:bg-gray-50">
                        <td className="py-2.5 pr-3 font-medium text-slate-800 truncate max-w-[140px]">
                          {p.name}
                        </td>
                        <td className="py-2.5 pr-3 text-slate-500 truncate max-w-[120px]">
                          {p.specialty || "—"}
                        </td>
                        <td className="py-2.5 text-right">
                          <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-blue-50 text-blue-600 font-semibold text-xs">
                            {p.completed}
                          </span>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
