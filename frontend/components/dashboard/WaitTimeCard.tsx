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
    <div className="neu-panel border border-white">
      <p className="text-[11px] font-bold text-neu-inkSoft uppercase tracking-wide">Tempo de Espera</p>
      <p className="text-3xl font-bold mt-1 text-violet-600">{value}</p>
      <p className="text-xs text-slate-400 mt-1">Média chegada → atendimento</p>
    </div>
  );
}
