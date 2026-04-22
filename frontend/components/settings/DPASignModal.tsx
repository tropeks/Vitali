'use client';

import { useState } from 'react';
import { X, Loader2 } from 'lucide-react';

interface DPASignModalProps {
  onConfirm: () => void;
  onClose: () => void;
  loading: boolean;
}

export function DPASignModal({ onConfirm, onClose, loading }: DPASignModalProps) {
  const [agreed, setAgreed] = useState(false);

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/40">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-900">
            Acordo de Processamento de Dados (DPA)
          </h2>
          <button
            onClick={onClose}
            disabled={loading}
            className="text-slate-400 hover:text-slate-600 transition-colors disabled:opacity-40"
            aria-label="Fechar"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 text-sm text-slate-700">
          <p>
            Este Acordo de Processamento de Dados (&quot;DPA&quot;) é celebrado entre a clínica
            (&quot;Controladora&quot;) e a Vitali Saúde Tecnologia Ltda. (&quot;Operadora&quot;),
            nos termos da Lei Geral de Proteção de Dados Pessoais (LGPD — Lei n.º 13.709/2018).
          </p>

          <div>
            <h3 className="font-semibold text-slate-800 mb-1">1. Objeto</h3>
            <p>
              O presente DPA regula o tratamento de dados pessoais sensíveis de saúde realizado
              pela Operadora em nome da Controladora, especificamente no contexto do módulo de
              Inteligência Artificial (IA Clínica), que utiliza transcrições de consultas médicas
              para geração automática de documentação clínica (SOAP).
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 mb-1">2. Suboperador</h3>
            <p>
              Para viabilizar o processamento de linguagem natural, a Operadora utiliza os
              serviços da Anthropic, PBC (&quot;Suboperador&quot;), com sede nos Estados Unidos.
              O tratamento é regido pelos Termos de Uso e Política de Privacidade da Anthropic,
              incluindo salvaguardas para transferência internacional de dados pessoais conforme
              o Art. 33 da LGPD.
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 mb-1">3. Finalidade</h3>
            <p>
              Os dados de transcrição são processados exclusivamente para: (i) geração de
              notas clínicas estruturadas (SOAP); (ii) melhoria contínua dos modelos de IA
              mediante anonimização prévia. Nenhum dado identificado é retido pelo Suboperador
              por prazo superior ao necessário para prestação do serviço.
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 mb-1">4. Segurança</h3>
            <p>
              A Operadora adota medidas técnicas e organizacionais adequadas para proteger os
              dados contra acesso não autorizado, destruição, perda, alteração ou divulgação
              indevida, incluindo criptografia em repouso (AES-256) e em trânsito (TLS 1.3).
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 mb-1">5. Direitos dos Titulares</h3>
            <p>
              A Controladora é responsável por atender às solicitações dos titulares de dados
              (pacientes) nos termos do Art. 18 da LGPD. A Operadora prestará assistência
              técnica necessária para viabilizar o exercício desses direitos.
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 mb-1">6. Vigência</h3>
            <p>
              Este DPA entra em vigor na data de assinatura e permanece válido enquanto durar
              a relação contratual entre as partes. O término do contrato principal implica
              o encerramento deste DPA, com exclusão segura dos dados processados.
            </p>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 mb-1">7. Responsabilidade</h3>
            <p>
              Ao assinar este DPA, a Controladora declara ter lido, compreendido e concordado
              com todos os termos aqui estabelecidos, assumindo a responsabilidade pelo uso
              adequado do módulo de IA Clínica em conformidade com a LGPD.
            </p>
          </div>
        </div>

        <div className="px-5 py-4 border-t border-slate-200 space-y-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              disabled={loading}
              className="mt-0.5 h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500 disabled:opacity-40"
            />
            <span className="text-sm text-slate-700">
              Li e concordo com os termos do DPA
            </span>
          </label>

          <div className="flex gap-3">
            <button
              onClick={onClose}
              disabled={loading}
              className="flex-1 px-4 py-2.5 text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors disabled:opacity-40"
            >
              Cancelar
            </button>
            <button
              onClick={onConfirm}
              disabled={!agreed || loading}
              className="flex-1 inline-flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {loading && <Loader2 size={16} className="animate-spin" />}
              Confirmar Assinatura
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
