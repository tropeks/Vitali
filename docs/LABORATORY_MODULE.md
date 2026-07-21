# Módulo de exames laboratoriais

## Escopo entregue

O primeiro corte operacional cobre o fluxo interno de exames laboratoriais:

1. catálogo de exames por tenant;
2. pedido vinculado a paciente e, opcionalmente, atendimento;
3. registro de coleta;
4. lançamento do resultado por item, com sinalizador de anormalidade;
5. validação nominal do resultado;
6. consulta do histórico de pedidos do paciente.

O corte concretiza a lacuna entre as primitivas já existentes de solicitação/laudo
FHIR (`ServiceRequest` e `DiagnosticReport`) e uma operação laboratorial utilizável.

## Limites de interoperabilidade

O módulo é o sistema operacional interno do Vitali; ele **não é um LIS** e ainda
não possui interface certificada com analisadores. Não envie mensagens de produção
diretamente para estes endpoints:

- HL7 v2 (por exemplo, ORM/OML, ORU e ACK) exige um motor de integração que faça
  mapeamento de identificadores, vocabulários, unidades, estados e confirmação de
  entrega. O Vitali ainda não recebe nem emite essas mensagens;
- ASTM E1381/E1394 é um protocolo de equipamentos e também não está implementado.
  A conexão futura deve ficar em um adaptador isolado, com fila, idempotência,
  reconciliação e quarentena de mensagens inválidas;
- os códigos do catálogo inicial são identificadores locais estáveis, não códigos
  LOINC, TUSS ou CBHPM. A instituição deve manter o de/para homologado antes de uma
  integração externa;
- resultados importados futuramente não poderão ser validados automaticamente:
  identidade, amostra, método, unidade, faixa e autoria precisam ser preservados e
  reconciliados antes da liberação clínica.

Imagem diagnóstica não pertence ao laboratório: solicitações de raio-X,
ultrassom, tomografia e ressonância devem seguir o fluxo RIS/PACS. DICOM,
Orthanc/OHIF e laudos de imagem permanecem separados; o laboratório não deve
armazenar imagens ou fingir compatibilidade PACS.

### Contexto cruzado com RIS/PACS

Quando um estudo de imagem for clinicamente relacionado a um item do pedido, o
registro `DicomStudy` pode guardar `related_lab_item`. É uma referência opcional
para navegação e rastreabilidade: ela não transforma o exame em categoria
laboratorial, não cria um pedido RIS e não envia nada ao Orthanc.

Com o módulo `imaging` habilitado e permissão `imaging.read`, estudos podem ser
consultados por `GET /api/v1/imaging/studies/?lab_order={uuid}` ou
`?lab_order_item={uuid}`. O vínculo só é aceito quando estudo e pedido pertencem
ao mesmo paciente. Um `report_document` opcional aponta para um
`ClinicalDocument` do tipo `report` do mesmo paciente/atendimento; a resposta de
imaging expõe apenas metadados e estado de assinatura, nunca o conteúdo do laudo.

Sem `ORTHANC_URL` e sem `orthanc_study_id`, o registro continua útil como índice
clínico e aparece como “Aguardando PACS”. O Vitali não presume que Orthanc/OHIF
estejam disponíveis e só oferece o visualizador quando há pixel data vinculada.

## Fora deste corte

- integração bidirecional com LIS/equipamentos (HL7 v2/ASTM) e cadastro do de/para;
- assinatura ICP-Brasil e emissão de PDF do laudo laboratorial;
- portal do paciente e notificações de liberação;
- regras automáticas de referência por idade, sexo, gestação, método ou laboratório;
- bancada de microbiologia/antibiograma, macroscopia/histologia e cadeia de custódia;
- agendamento de exames e faturamento/TISS automático;
- imagem, DICOM, Orthanc e OHIF, que pertencem ao módulo PACS.

Esses itens continuam como evolução pós-MVP. O sinalizador de anormalidade deste
corte é informado pelo operador; o Vitali não deve inferir decisão clínica a partir
de uma faixa textual.

## Catálogo inicial

Execute no host Django:

```bash
python manage.py seed_lab_catalog --tenant demo --dry-run
python manage.py seed_lab_catalog --tenant demo
```

O comando é idempotente: cria códigos ausentes e atualiza os metadados conhecidos.
Ele não desativa exames adicionais do tenant. O catálogo cobre hematologia,
bioquímica, coagulação, imunologia/sorologia, hormônios, urinálise, parasitologia,
microbiologia, toxicologia, biologia molecular/genética, anatomia patológica e
testes rápidos. Catálogos compostos representam o pedido; seus analitos/componentes
devem ser cadastrados e liberados individualmente quando a operação exigir.

Os códigos são deliberadamente locais (inclusive os mnemônicos legados do catálogo
MVP) e não alegam equivalência com um padrão externo. Adoção de LOINC/TUSS/CBHPM
exige curadoria e versionamento do mapeamento pelo responsável técnico; por isso o
seed deixa `loinc_code` vazio.

As faixas de referência ficam vazias de propósito. Antes do uso assistencial, um
responsável técnico deve cadastrar as faixas validadas pelo laboratório, levando em
conta método, população, idade e sexo. O catálogo inicial não é fonte de conduta.

## API

Base autenticada: `/api/v1/`.

| Operação | Endpoint |
|---|---|
| Listar/criar catálogo | `GET/POST lab-tests/` |
| Atualizar/inativar exame | `PATCH/DELETE lab-tests/{id}/` |
| Listar/criar pedidos | `GET/POST lab-orders/` |
| Filtrar pedidos | `GET lab-orders/?patient={id}&status={status}` |
| Registrar coleta | `POST lab-orders/{id}/collect/` |
| Lançar resultado | `POST lab-orders/{id}/items/{item_id}/result/` |
| Validar resultado | `POST lab-orders/{id}/items/{item_id}/validate/` |
| Cancelar pedido | `POST lab-orders/{id}/cancel/` |

Leitura exige `emr.read`; mutações exigem `emr.write`. Dados clínicos sensíveis
permanecem no schema do tenant e os campos narrativos/resultados são criptografados
em repouso. A API registra auditoria nas transições clínicas relevantes.

### Exemplo de pedido

```json
{
  "patient": "<uuid>",
  "encounter": "<uuid-opcional>",
  "clinical_indication": "Acompanhamento clínico",
  "test_ids": ["<uuid-do-exame>"]
}
```

### Exemplo de resultado

```json
{
  "result_value": "5.4",
  "abnormal_flag": "normal",
  "result_notes": ""
}
```

Valores aceitos em `abnormal_flag`: `normal`, `low`, `high`, `critical` e
`undetermined`.

## Operação segura

- Validar identidade do paciente e a amostra fora do sistema antes de registrar a coleta.
- Registrar tipo de amostra, método e identificadores de coleta conforme o POP local.
- Conferir unidade e faixa de referência capturadas no item do pedido.
- Validar resultados somente com profissional autorizado.
- Corrigir resultados por fluxo auditável; não sobrescrever histórico diretamente no admin.
- Tratar resultados críticos conforme o protocolo institucional — este MVP não notifica automaticamente.
- Resultados qualitativos, culturas, antibiogramas, genética e patologia exigem
  formulários e revisão próprios; texto livre genérico não substitui esses fluxos.
