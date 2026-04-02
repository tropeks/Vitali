'use client';

interface AccuracyRow {
  insurer_ans_code: string;
  insurer_name: string;
  total_predictions: number;
  predicted_high: number;
  was_denied: number;
  true_positives: number;
  precision: number | null;
  recall: number | null;
}

interface Props {
  data: AccuracyRow[];
  minPredictions?: number;
}

const MIN_PER_INSURER = 10;

function pct(val: number | null): string {
  if (val === null) return '—';
  return `${(val * 100).toFixed(1)}%`;
}

export default function GlosaAccuracyTable({ data, minPredictions = MIN_PER_INSURER }: Props) {
  if (data.length === 0) {
    return (
      <div className="text-sm text-gray-500 py-4">
        <p className="font-medium mb-1">A IA de Glosa está aprendendo.</p>
        <p className="text-gray-400">
          Acompanhe a precisão após {minPredictions} previsões por convênio. Crie guias TISS para começar.
        </p>
      </div>
    );
  }

  const readyRows = data.filter(r => r.total_predictions >= minPredictions);
  const warmingRows = data.filter(r => r.total_predictions < minPredictions);

  return (
    <div className="space-y-4">
      {warmingRows.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {warmingRows.map(r => (
            <span
              key={r.insurer_ans_code}
              className="inline-flex items-center px-2.5 py-1 rounded-full text-xs bg-gray-100 text-gray-600"
            >
              {r.insurer_name}: {r.total_predictions}/{minPredictions} previsões
            </span>
          ))}
        </div>
      )}

      {readyRows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-2 pr-4 font-medium text-gray-500">Convênio</th>
                <th className="text-right py-2 pr-4 font-medium text-gray-500">Previsões</th>
                <th className="text-right py-2 pr-4 font-medium text-gray-500">Alto risco %</th>
                <th className="text-right py-2 pr-4 font-medium text-gray-500">Glosado real %</th>
                <th className="text-right py-2 font-medium text-gray-500">Precisão</th>
              </tr>
            </thead>
            <tbody>
              {readyRows.map(r => {
                const highRatePct =
                  r.total_predictions > 0
                    ? `${((r.predicted_high / r.total_predictions) * 100).toFixed(1)}%`
                    : '—';
                const denialRatePct =
                  r.total_predictions > 0
                    ? `${((r.was_denied / r.total_predictions) * 100).toFixed(1)}%`
                    : '—';
                return (
                  <tr key={r.insurer_ans_code} className="border-b border-gray-50">
                    <td className="py-2 pr-4 text-gray-900">{r.insurer_name}</td>
                    <td className="py-2 pr-4 text-right text-gray-600">{r.total_predictions}</td>
                    <td className="py-2 pr-4 text-right text-gray-600">{highRatePct}</td>
                    <td className="py-2 pr-4 text-right text-gray-600">{denialRatePct}</td>
                    <td className="py-2 text-right font-medium text-gray-900">{pct(r.precision)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
