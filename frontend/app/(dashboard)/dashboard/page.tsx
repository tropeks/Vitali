"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "@/lib/api";
import OnboardingWidget from "@/components/OnboardingWidget";
import WaitTimeCard from "@/components/dashboard/WaitTimeCard";
import { AlertTriangle, ArrowRight, ClipboardCheck, Clock3 } from "lucide-react";
import { buildDashboardActionQueue, type OperationalTone } from "@/lib/operational-ui";
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

type Period = "today" | "week" | "month";

interface Overview {
  period: Period;
  since: string;
  appointments_total: number;
  appointments_completed: number;
  appointments_confirmed: number;
  appointments_waiting: number;
  appointments_cancelled: number;
  appointments_no_show: number;
  cancellation_rate: number;
  no_show_rate: number;
  new_patients: number;
  encounters_open: number;
  encounters_signed: number;
  revenue: string | number;
  wait_time_avg_min: number | null;
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

const ANALYTICS_BASE = "/api/v1/analytics";

const PIE_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#facc15",
  "#f87171",
  "#a78bfa",
  "#fb923c",
  "#94a3b8",
];

const PERIOD_LABELS: Record<Period, string> = {
  today: "Hoje",
  week: "Semana",
  month: "Mês",
};

const ACTION_TONE_CLASSES: Record<OperationalTone, string> = {
  neutral: "border-slate-200 bg-white text-slate-700",
  info: "border-blue-200 bg-blue-50 text-blue-800",
  attention: "border-yellow-200 bg-yellow-50 text-yellow-800",
  success: "border-green-200 bg-green-50 text-green-800",
  critical: "border-red-200 bg-red-50 text-red-800",
};

const ACTION_VALUE_CLASSES: Record<OperationalTone, string> = {
  neutral: "text-slate-700",
  info: "text-blue-700",
  attention: "text-yellow-800",
  success: "text-green-700",
  critical: "text-red-700",
};

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
    <div className="bg-white rounded-lg border border-slate-200 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${color}`}>{value}</p>
      {sub && <p className="mt-1 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ className }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-slate-200 rounded ${className ?? ""}`} />
  );
}

function KPISkeleton() {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-3">
      <Skeleton className="h-4 w-32" />
      <Skeleton className="h-9 w-20" />
      <Skeleton className="h-3 w-40" />
    </div>
  );
}

function ChartSkeleton({ height = 240 }: { height?: number }) {
  return (
    <div
      className="animate-pulse bg-slate-200 rounded-lg"
      style={{ height }}
    />
  );
}

function ChartEmpty({ label }: { label: string }) {
  return (
    <div className="flex h-full min-h-[220px] items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50 text-sm text-slate-500">
      {label}
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [period, setPeriod] = useState<Period>("month");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [byDay, setByDay] = useState<DayRow[]>([]);
  const [byStatus, setByStatus] = useState<StatusRow[]>([]);
  const [byMonth, setByMonth] = useState<MonthRow[]>([]);
  const [professionals, setProfessionals] = useState<Professional[]>([]);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [chartsLoading, setChartsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dateLabel, setDateLabel] = useState("Operação de hoje");

  const fetchOverview = useCallback(async (p: Period) => {
    // Migrated to apiFetch (T12): JWT header injected automatically;
    // PASSWORD_CHANGE_REQUIRED 403 triggers redirect without reaching catch.
    setOverviewLoading(true);
    try {
      const data = await apiFetch<Overview>(`${ANALYTICS_BASE}/overview/?period=${p}`);
      setOverview(data);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) {
        // apiFetch already redirects for PASSWORD_CHANGE_REQUIRED;
        // other 403s (e.g. missing module) — fail silently
        setOverviewLoading(false);
        return;
      }
      setError(e instanceof Error ? e.message : "Erro desconhecido");
    } finally {
      setOverviewLoading(false);
    }
  }, []);

  const fetchCharts = useCallback(async (showLoading = false) => {
    if (showLoading) setChartsLoading(true);
    try {
      const [dayData, statusData, monthData, proData] = await Promise.all([
        apiFetch<DayRow[]>(`${ANALYTICS_BASE}/appointments-by-day/?days=30`).catch(() => []),
        apiFetch<StatusRow[]>(`${ANALYTICS_BASE}/appointments-by-status/`).catch(() => []),
        apiFetch<MonthRow[]>(`${ANALYTICS_BASE}/patients-by-month/?months=6`).catch(() => []),
        apiFetch<Professional[]>(`${ANALYTICS_BASE}/top-professionals/?limit=5`).catch(() => []),
      ]);
      setByDay(dayData);
      setByStatus(statusData);
      setByMonth(monthData);
      setProfessionals(proData);
    } catch {
      // fail-open: charts show empty state
    } finally {
      setChartsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCharts(true);
    const interval = setInterval(() => fetchCharts(false), 60_000);
    return () => clearInterval(interval);
  }, [fetchCharts]);

  useEffect(() => {
    fetchOverview(period);
  }, [period, fetchOverview]);

  useEffect(() => {
    setDateLabel(
      new Date().toLocaleDateString("pt-BR", {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      })
    );
  }, []);

  const fmtRevenue = (val: string | number | undefined) => {
    const n = parseFloat(String(val ?? 0));
    return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
  };

  const actionQueue = buildDashboardActionQueue(overview);

  if (!overviewLoading && !chartsLoading && error) {
    return (
      <div className="space-y-6">
        <OnboardingWidget />
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Centro operacional</h1>
          <p className="text-slate-500 text-sm mt-1">{dateLabel}</p>
        </div>
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg p-5">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Centro operacional</h1>
          <p className="text-sm text-slate-500 mt-1">
            {dateLabel} · status clínico, agenda e pendências em uma visão
          </p>
        </div>

        {/* Period toggle */}
        <div className="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
          {(["today", "week", "month"] as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                period === p
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </div>

      <OnboardingWidget />

      {/* ── Operational Queue ── */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        {overviewLoading
          ? Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="rounded-lg border border-slate-200 bg-white p-4">
                <Skeleton className="h-4 w-28" />
                <Skeleton className="mt-3 h-8 w-12" />
                <Skeleton className="mt-2 h-3 w-40" />
              </div>
            ))
          : actionQueue.map((item) => {
              const Icon =
                item.tone === "critical"
                  ? AlertTriangle
                  : item.id === "open-encounters"
                    ? ClipboardCheck
                    : Clock3;
              return (
                <Link
                  key={item.id}
                  href={item.href}
                  className={`group rounded-lg border p-4 transition-colors hover:bg-white ${ACTION_TONE_CLASSES[item.tone]}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <Icon size={16} className="shrink-0" />
                        <p className="truncate text-xs font-semibold uppercase tracking-wide">
                          {item.label}
                        </p>
                      </div>
                      <p className={`mt-2 text-3xl font-bold ${ACTION_VALUE_CLASSES[item.tone]}`}>
                        {item.value}
                      </p>
                      <p className="mt-1 text-xs opacity-80">{item.detail}</p>
                    </div>
                    <span className="mt-1 inline-flex items-center gap-1 text-xs font-semibold">
                      {item.actionLabel}
                      <ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" />
                    </span>
                  </div>
                </Link>
              );
            })}
      </div>

      {/* ── KPI Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
        {overviewLoading ? (
          Array.from({ length: 5 }).map((_, i) => <KPISkeleton key={i} />)
        ) : (
          <>
            <KPICard
              label={`Consultas — ${PERIOD_LABELS[period]}`}
              value={overview?.appointments_total ?? 0}
              sub={`${overview?.appointments_completed ?? 0} concluídas · ${overview?.appointments_waiting ?? 0} aguardando`}
              color="text-blue-600"
            />
            <KPICard
              label="Novos Pacientes"
              value={overview?.new_patients ?? 0}
              sub={`${overview?.cancellation_rate ?? 0}% cancelamento · ${overview?.no_show_rate ?? 0}% faltas`}
              color="text-green-600"
            />
            <KPICard
              label="Consultas Assinadas"
              value={overview?.encounters_signed ?? 0}
              sub={`${overview?.encounters_open ?? 0} em aberto`}
              color="text-slate-700"
            />
            <KPICard
              label="Receita (guias pagas)"
              value={fmtRevenue(overview?.revenue)}
              sub={`Período: ${PERIOD_LABELS[period].toLowerCase()}`}
              color="text-emerald-600"
            />
            <WaitTimeCard waitTimeAvgMin={overview?.wait_time_avg_min} loading={overviewLoading} />
          </>
        )}
      </div>

      {/* ── Charts Row 1: Line + Donut ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-white rounded-lg border border-slate-200 p-5">
          <h2 className="font-semibold text-slate-900 mb-4">
            Consultas por Dia{" "}
            <span className="text-xs text-slate-400 font-normal">(últimos 30 dias)</span>
          </h2>
          {chartsLoading ? (
            <ChartSkeleton height={240} />
          ) : byDay.length === 0 ? (
            <ChartEmpty label="Sem consultas no período para montar tendência." />
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={byDay} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
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
                <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} allowDecimals={false} />
                <Tooltip
                  labelFormatter={(v: string) =>
                    new Date(v + "T00:00:00").toLocaleDateString("pt-BR")
                  }
                />
                <Legend
                  wrapperStyle={{ fontSize: 12 }}
                  formatter={(value: string) =>
                    value === "total" ? "Total" : value === "completed" ? "Concluídas" : "Canceladas"
                  }
                />
                <Line type="monotone" dataKey="total" stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="completed" stroke="#22c55e" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="cancelled" stroke="#f87171" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-white rounded-lg border border-slate-200 p-5">
          <h2 className="font-semibold text-slate-900 mb-4">
            Status das Consultas{" "}
            <span className="text-xs text-slate-400 font-normal">(mês atual)</span>
          </h2>
          {chartsLoading ? (
            <ChartSkeleton height={240} />
          ) : byStatus.length === 0 ? (
            <ChartEmpty label="Sem status de consulta para exibir." />
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
                    <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(value: number) => [value, "Consultas"]} />
                <Legend wrapperStyle={{ fontSize: 11 }} iconType="circle" iconSize={8} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Charts Row 2: Bar + Table ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg border border-slate-200 p-5">
          <h2 className="font-semibold text-slate-900 mb-4">
            Novos Pacientes por Mês{" "}
            <span className="text-xs text-slate-400 font-normal">(últimos 6 meses)</span>
          </h2>
          {chartsLoading ? (
            <ChartSkeleton height={220} />
          ) : byMonth.length === 0 ? (
            <ChartEmpty label="Sem novos pacientes nos últimos meses." />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={byMonth} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#94a3b8" }} />
                <YAxis tick={{ fontSize: 11, fill: "#94a3b8" }} allowDecimals={false} />
                <Tooltip formatter={(value: number) => [value, "Pacientes"]} />
                <Bar dataKey="count" name="Pacientes" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="bg-white rounded-lg border border-slate-200 p-5">
          <h2 className="font-semibold text-slate-900 mb-4">
            Top Profissionais{" "}
            <span className="text-xs text-slate-400 font-normal">(consultas concluídas este mês)</span>
          </h2>
          {chartsLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-100">
                    <th className="text-left py-2 pr-3 text-xs font-medium text-slate-500 uppercase tracking-wide">
                      Profissional
                    </th>
                    <th className="text-left py-2 pr-3 text-xs font-medium text-slate-500 uppercase tracking-wide">
                      Especialidade
                    </th>
                    <th className="text-right py-2 text-xs font-medium text-slate-500 uppercase tracking-wide">
                      Concluídas
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {professionals.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="py-6 text-center text-slate-400 text-sm">
                        Nenhum dado disponível
                      </td>
                    </tr>
                  ) : (
                    professionals.map((p) => (
                      <tr key={p.professional_id} className="hover:bg-slate-50">
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
