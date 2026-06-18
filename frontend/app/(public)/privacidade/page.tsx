import Link from 'next/link';

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8">
      <div className="sm:mx-auto sm:w-full sm:max-w-4xl">
        <h2 className="mt-6 text-center text-3xl font-extrabold text-gray-900">
          Política de Privacidade
        </h2>
        <div className="mt-8 bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
          <div className="prose prose-blue max-w-none text-gray-700">
            <h3>1. Introdução</h3>
            <p>
              Esta Política de Privacidade descreve como coletamos, usamos e protegemos suas informações pessoais.
              <strong>[REVISÃO JURÍDICA PENDENTE]</strong>
            </p>

            <h3>2. Coleta de Dados</h3>
            <p>
              Coletamos os dados necessários para o funcionamento da plataforma hospitalar, em conformidade com a LGPD.
            </p>

            <h3>3. Cookies</h3>
            <p>
              Utilizamos cookies para melhorar a experiência do usuário, manter sessões ativas e por razões de segurança.
            </p>

            <h3>4. Seus Direitos</h3>
            <p>
              Você tem direito a acessar, corrigir e solicitar a exclusão de seus dados, conforme os regulamentos aplicáveis.
            </p>

            <div className="mt-8 pt-5 border-t border-gray-200">
              <Link href="/" className="text-blue-600 hover:text-blue-500 font-medium">
                &larr; Voltar para a página inicial
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
