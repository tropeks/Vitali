import Link from 'next/link';

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-neu-outer text-neu-ink font-sans flex flex-col items-center">
      {/* Header Clínico Corporativo */}
      <div className="w-full bg-neu-brand h-12 flex items-center px-6 shadow-sm border-b border-neu-brandDeep">
        <span className="text-white font-semibold text-sm tracking-wide">Vitali EMR Solutions | Portal de Privacidade</span>
      </div>

      <div className="w-full max-w-5xl mt-6 px-4">
        {/* Container tipo "Folha de Prontuário" */}
        <div className="bg-white border border-neu-app rounded-sm shadow-sm overflow-hidden">
          <div className="bg-neu-panelAlt border-b border-neu-app px-6 py-3 flex justify-between items-center">
            <h2 className="text-lg font-bold text-neu-brand">Política de Privacidade Institucional</h2>
            <span className="text-xs text-slate-500 font-mono">DOC-PRIV-2026-V1.0</span>
          </div>

          <div className="p-8 text-sm leading-relaxed space-y-6">
            <section>
              <h3 className="text-neu-brand font-bold border-b border-neu-app pb-1 mb-2">1. Escopo e Finalidade</h3>
              <p className="text-slate-700">
                A presente política estabelece as diretrizes de governança de dados operadas pela solução Vitali EMR,
                garantindo a estrita conformidade com a Lei Geral de Proteção de Dados (LGPD) e normativas do Conselho Federal de Medicina (CFM).
                Os dados aqui tramitados possuem finalidade exclusiva de prestação de assistência à saúde e auditoria clínica.
              </p>
            </section>

            <section>
              <h3 className="text-neu-brand font-bold border-b border-neu-app pb-1 mb-2">2. Custódia e Criptografia</h3>
              <p className="text-slate-700">
                Informações de Caráter Pessoal (PII) e Dados Sensíveis de Saúde (PHI) são anonimizados e encriptados em repouso (AES-256).
                A trilha de auditoria é imutável, registrando de forma inalterável o timestamp, identificador do usuário (CRM/COREN/Login) e 
                a natureza da transação (Visualização, Inserção, Alteração de Prontuário).
              </p>
            </section>

            <section>
              <h3 className="text-neu-brand font-bold border-b border-neu-app pb-1 mb-2">3. Direitos do Titular</h3>
              <p className="text-slate-700">
                O acesso, retificação, portabilidade ou eliminação (sujeito aos prazos de guarda legal de prontuários médicos de 20 anos)
                deve ser solicitado formalmente via Portal do Paciente ou diretamente à administração da clínica detentora da licença.
              </p>
            </section>
          </div>

          <div className="bg-neu-panelAlt border-t border-neu-app px-6 py-3 flex items-center">
            <Link href="/" className="px-4 py-1.5 bg-white border border-neu-app text-neu-ink hover:bg-slate-50 rounded-sm text-xs font-semibold transition-colors">
              &larr; Retornar à Tela de Autenticação
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
