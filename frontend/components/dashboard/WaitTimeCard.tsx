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
    <div className="bg-[#F4F7FA] p-4 rounded-xl shadow-[inset_0_1px_2px_rgba(255,255,255,0.8),_0_2px_8px_rgba(0,0,0,0.03)] border border-white">
      <p className="text-[11px] font-bold text-[#57606A] uppercase tracking-wide">Tempo de Espera</p>
      <p className="text-3xl font-bold mt-1 text-violet-600">{value}</p>
      <p className="text-xs text-slate-400 mt-1">Média chegada → atendimento</p>
    </div>
  );
}
