# Guia do Usuário — Vitali

Bem-vindo ao Vitali, a plataforma de saúde para clínicas e consultórios. Este guia cobre as principais funcionalidades do sistema.

---

## 1. Primeiros Passos — Configuração Inicial

Ao acessar o Vitali pela primeira vez, você será direcionado ao **Assistente de Configuração**.

### Passo 1: Dados da Clínica
Informe o nome da clínica, CNPJ, endereço e telefone de contato.

### Passo 2: Profissionais
Cadastre os profissionais de saúde. Para cada um, informe:
- Nome completo
- Conselho (CRM, CRO, CRN etc.) e número de registro
- Especialidade
- Dias e horários de atendimento

### Passo 3: Agenda
Defina o padrão de horários: horário de início, fim, duração dos slots (ex: 30 min) e intervalo de almoço.

### Passo 4: Pagamentos (PIX)
Configure a integração com a Asaas para cobrança via PIX. Você precisará de uma chave de API Asaas (acesse sandbox.asaas.com para testes).

### Passo 5: Conclusão
Após concluir o assistente, sua agenda já está pronta para uso.

---

## 2. Gerenciamento de Pacientes

Acesse **Pacientes** no menu lateral.

### Cadastrar novo paciente
1. Clique em **Novo Paciente**
2. Preencha nome completo, data de nascimento, sexo, telefone e e-mail
3. Informe dados do plano de saúde (opcional)
4. Clique em **Salvar**

### Buscar paciente
Use a barra de busca no topo da lista. A busca funciona por nome, CPF ou telefone.

### Prontuário eletrônico
Clique no nome do paciente para acessar o prontuário completo, incluindo histórico de consultas, prescrições e exames.

---

## 3. Agenda e Consultas

Acesse **Agenda** no menu lateral.

### Visualização
- **Desktop**: grade semanal com todos os horários disponíveis
- **Mobile**: lista diária com cards por paciente

### Agendar consulta
1. Clique em um horário vazio na grade (desktop) ou no botão **Agendar** (mobile)
2. Selecione o paciente, profissional, tipo de consulta e duração
3. Clique em **Confirmar**

### Alterar status da consulta
Clique na consulta e use os botões de ação:
- **Confirmar** — paciente confirmou presença
- **Aguardando** — paciente chegou na clínica
- **Iniciar** — consulta em andamento
- **Concluir** — consulta finalizada
- **Não compareceu** — paciente faltou
- **Cancelar** — consulta cancelada

---

## 4. Pagamentos via PIX

Acesse a consulta agendada e clique em **Cobrar via PIX**.

### Fluxo de cobrança
1. O sistema gera um QR Code e o código "Copia e Cola" do PIX
2. Compartilhe com o paciente (via WhatsApp ou exibindo na tela)
3. Após o pagamento, o sistema confirma automaticamente a consulta
4. O paciente recebe e-mail de confirmação

### No celular
O código "Copia e Cola" aparece em destaque para facilitar o compartilhamento. O QR Code fica disponível abaixo.

### Validade
O PIX expira em 30 minutos por padrão. Clique em **Gerar novo PIX** para recriar a cobrança.

---

## 5. Prontuário Eletrônico (EMR)

Acesse **Consultas** no menu lateral durante ou após o atendimento.

### Estrutura da nota clínica (SOAP)
- **Subjetivo (S)**: queixa principal do paciente com suas próprias palavras
- **Objetivo (O)**: sinais vitais, exame físico
- **Avaliação (A)**: diagnóstico e impressão clínica
- **Plano (P)**: conduta, prescrições, retorno

### Prescrições
1. Na aba **Prescrições** da consulta, clique em **Nova Prescrição**
2. Busque o medicamento pelo nome ou código TUSS
3. Informe posologia e duração
4. Clique em **Salvar e Imprimir**

### Encaminhamentos
Use a aba **Encaminhamentos** para registrar referências a especialistas ou exames.

---

## 6. Faturamento e TISS

Acesse **Faturamento** no menu lateral.

### Guias TISS
Para planos de saúde, o Vitali gera automaticamente guias TISS após a conclusão da consulta.

1. Acesse **Guias** → **Nova Guia**
2. Selecione o paciente, a consulta e o procedimento (código TUSS)
3. Clique em **Gerar XML** para exportar para a operadora

### Lotes
Agrupe guias em lotes mensais por operadora em **Lotes** → **Novo Lote**.

### Glosas
Gerencie glosas recebidas em **Glosas**. Para cada glosa, você pode registrar recurso e acompanhar o resultado.

---

## 7. Farmácia / Estoque

Acesse **Farmácia** no menu lateral.

### Controle de estoque
- Cadastre medicamentos e produtos com código TUSS/EAN
- Registre entradas de estoque via **Pedidos de Compra**
- O sistema alerta quando o estoque está abaixo do mínimo configurado

### Dispensação
Ao concluir uma prescrição eletrônica, o sistema solicita a confirmação da dispensação (saída do estoque).

---

## 8. WhatsApp — Lembretes e Confirmações

Acesse **Configurações → WhatsApp** no menu lateral.

### Conectar WhatsApp
1. Clique em **Conectar**
2. Escaneie o QR Code com o WhatsApp do número da clínica
3. O status ficará **Conectado** quando concluído

### Lembretes automáticos
O sistema envia lembretes automáticos 24 horas antes de cada consulta confirmada. Os pacientes podem confirmar respondendo ao lembrete.

### Histórico de conversas
Na aba **Conversas**, visualize o histórico de mensagens com cada paciente.

---

## 9. Relatórios e Analytics

Acesse **Analytics** no menu lateral.

### Painel principal
- **Taxa de comparecimento**: percentual de pacientes que comparecem às consultas
- **Faturamento mensal**: evolução da receita por período
- **Procedimentos mais realizados**: ranking de TUSS

### Exportar dados
Clique em **Exportar** em qualquer tabela para baixar em CSV ou PDF.

---

## 10. AI em breve

O Vitali está desenvolvendo funcionalidades de Inteligência Artificial para auxiliar os profissionais de saúde:

- **Sugestão de CID-10**: preenchimento automático de diagnósticos baseado na anamnese
- **Revisão de prescrições**: alertas de interação medicamentosa e contraindicações
- **Resumo de prontuário**: síntese automática do histórico clínico do paciente
- **Transcrição de consulta**: conversão de áudio em nota clínica estruturada (SOAP)

Estas funcionalidades estarão disponíveis nas próximas versões. Entre em contato com suporte@vitali.app para acesso antecipado.

---

## Suporte

Em caso de dúvidas ou problemas, entre em contato:
- **E-mail**: suporte@vitali.app
- **Documentação técnica**: `/docs/DEVELOPMENT.md`
- **Relatar problema**: abra uma issue no repositório do projeto
