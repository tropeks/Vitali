interface WaitTimeCardProps {
  waitTimeAvgMin: number | null | undefined;
  loading?: boolean;
}

export default function WaitTimeCard({ waitTimeAvgMin, loading }: WaitTimeCardProps) {
  const value =
    loading
      ? "..."
      : waitTimeAvgMin == null
      ? "—"
      : `${waitTimeAvgMin} min`;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm">
      <p className="text-sm text-slate-500">Tempo de Espera</p>
      <p className="text-3xl font-bold mt-1 text-violet-600">{value}</p>
      <p className="text-xs text-slate-400 mt-1">Média chegada → atendimento</p>
    </div>
  );
}
