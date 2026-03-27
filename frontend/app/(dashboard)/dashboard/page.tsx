import { Calendar, Users, BedDouble, AlertTriangle } from "lucide-react";

interface MetricCard {
  title: string;
  value: string | number;
  subtitle: string;
  icon: React.ElementType;
  color: string;
}

const MOCK_METRICS: MetricCard[] = [
  {
    title: "Consultas hoje",
    value: 24,
    subtitle: "8 confirmadas, 16 agendadas",
    icon: Calendar,
    color: "bg-blue-500",
  },
  {
    title: "Pacientes ativos",
    value: "1.847",
    subtitle: "+12 este mês",
    icon: Users,
    color: "bg-green-500",
  },
  {
    title: "Ocupação de leitos",
    value: "73%",
    subtitle: "44 / 60 leitos ocupados",
    icon: BedDouble,
    color: "bg-amber-500",
  },
  {
    title: "Alertas de estoque",
    value: 3,
    subtitle: "2 críticos, 1 atenção",
    icon: AlertTriangle,
    color: "bg-red-500",
  },
];

export default function DashboardPage() {
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
        <p className="text-slate-500 text-sm mt-1">
          Visão geral do dia —{" "}
          {new Date().toLocaleDateString("pt-BR", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
          })}
        </p>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {MOCK_METRICS.map((metric) => {
          const Icon = metric.icon;
          return (
            <div
              key={metric.title}
              className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm"
            >
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm text-slate-500">{metric.title}</p>
                  <p className="text-3xl font-bold text-slate-900 mt-1">{metric.value}</p>
                  <p className="text-xs text-slate-400 mt-1">{metric.subtitle}</p>
                </div>
                <div className={`${metric.color} p-2.5 rounded-xl`}>
                  <Icon size={20} className="text-white" />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Placeholder sections */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Próximas consultas */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
          <h2 className="font-semibold text-slate-900 mb-4">Próximas consultas</h2>
          <div className="space-y-3">
            {["09:00 — Maria Silva", "09:30 — João Santos", "10:00 — Ana Oliveira"].map(
              (item) => (
                <div
                  key={item}
                  className="flex items-center gap-3 py-2 border-b border-slate-100 last:border-0"
                >
                  <div className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                  <span className="text-sm text-slate-700">{item}</span>
                </div>
              )
            )}
          </div>
          <p className="text-xs text-slate-400 mt-3 text-right">Dados simulados — Sprint 1</p>
        </div>

        {/* Alertas de estoque */}
        <div className="bg-white rounded-2xl border border-slate-200 p-5 shadow-sm">
          <h2 className="font-semibold text-slate-900 mb-4">Alertas de estoque</h2>
          <div className="space-y-3">
            {[
              { drug: "Dipirona 500mg", level: "Crítico", color: "text-red-600 bg-red-50" },
              { drug: "Amoxicilina 250mg", level: "Crítico", color: "text-red-600 bg-red-50" },
              { drug: "Paracetamol 750mg", level: "Atenção", color: "text-amber-600 bg-amber-50" },
            ].map((item) => (
              <div
                key={item.drug}
                className="flex items-center justify-between py-2 border-b border-slate-100 last:border-0"
              >
                <span className="text-sm text-slate-700">{item.drug}</span>
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${item.color}`}>
                  {item.level}
                </span>
              </div>
            ))}
          </div>
          <p className="text-xs text-slate-400 mt-3 text-right">Dados simulados — Sprint 1</p>
        </div>
      </div>
    </div>
  );
}
