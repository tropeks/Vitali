# Remessa DATASUS (BPA-Magnético/APAC/AIH) — distância vs. layout oficial

Este documento consolida, **a partir do código** de
`backend/apps/billing/services/sus_remessa.py`, a lista de divergências
conhecidas entre o layout posicional gerado pelo Vitali e o layout
byte-exato oficial do DATASUS (manuais BPA-Magnético/SISAIH). Objetivo:
tornar a distância **mensurável**, não folclórica.

Não existe XSD/spec formal do DATASUS versionado neste repositório para
validar contra (ao contrário do TISS, que tem os XSDs da ANS em
`backend/apps/billing/schemas/`). Por isso o entregável de teste é diferente
do 2.4: em vez de "validar contra o schema oficial", o teste em
`backend/apps/billing/tests/test_sus_remessa_golden.py` é uma **regressão de
layout** — gera a remessa a partir de dados fixos e compara byte-a-byte com
um arquivo de referência versionado (`backend/apps/billing/tests/golden/`),
garantindo que o layout atual não muda por acidente. Isso NÃO afirma
conformidade DATASUS; só constância do que já existe.

## Premissa de design (documentada no próprio módulo)

O módulo já se autodeclara, no docstring de topo e em `gerar_remessa_aih`:
> "coherent, documented, structurally-faithful" layout — **NOT** o mapa de
> campos byte-exato oficial DATASUS.

Isto é: header + linhas de detalhe tipadas, largura fixa, padding
zero/espaço, campo de controle — mas offsets/larguras/algoritmos são uma
convenção interna coerente, não reconciliada campo-a-campo com o manual
oficial DATASUS.

## Divergências explicitamente documentadas no código

1. **Campo `controle` do header** (`_header_line`, todos os tipos de
   remessa): `(Σ quantidades das linhas de detalhe + nº de linhas) mod
   10000`. É um checksum determinístico e documentado, mas **não** o
   algoritmo de controle oficial do BPA-Magnético/SISAIH.
2. **Número da AIH** (`gerar_remessa_aih` docstring): a remessa SISAIH
   oficial exige o número de 13 dígitos emitido pelo gestor SUS. A ponte
   AI2 (Admission→AIH) pode gerar um número **provisório** interno
   (`AAAAMM` + sequência) antes da reconciliação; números provisórios não
   passam em conformidade real-DATASUS. A geração não é bloqueada por isso
   — o layout é estruturalmente-fiel para efeito de contrato
   frontend/download, mas o conteúdo do campo pode não ser o número oficial.
3. **`motivo_saida` (AIH)** — `AIH_MOTIVO_CODIGO` mapeia os 5 rótulos
   internos (`AihAutorizacao.MotivoSaida`) para um código posicional de 2
   dígitos (`11`/`12`/`31`/`41`/`51`, dezena = classe do desfecho). A tabela
   oficial SISAIH tem subcódigos mais granulares (variações de alta,
   diferentes causas de óbito, tipos de transferência); a tabela atual é uma
   **redução estruturalmente-fiel**, não a tabela completa. Motivo
   vazio/desconhecido cai em `"00"`.

## Divergências inferidas ao ler o código (não documentadas explicitamente antes deste levantamento)

4. **Truncamento silencioso em overflow.** `_num`/`_code`/`_centavos`
   (helpers de padding) truncam pela esquerda quando o valor excede a
   largura do campo (`s[-width:]`), e `_txt` trunca pela direita
   (`s[:width]`) — nenhum dos dois levanta erro. Um valor real que não
   caiba na largura fixa (ex.: quantidade > 999999, CNES com mais de 7
   dígitos por erro de cadastro) é **silenciosamente cortado**, não
   rejeitado. Isso é uma escolha deliberada para nunca quebrar a geração da
   remessa, mas é uma divergência de robustez em relação a um validador
   DATASUS real, que rejeitaria o registro.
5. **Sem linha de rodapé/trailer.** Os layouts oficiais BPA-Magnético/SISAIH
   tradicionalmente têm um registro de fechamento (contagem final) além do
   cabeçalho. Este módulo só emite `TIPO_HEADER` (tipo `01`) no início; não
   há `TIPO_TRAILER` nem equivalente ao final do arquivo.
6. **CBO opcional no BPA-I.** `BpaIndividualizado.cbo` é `null=True`; quando
   ausente, `gerar_remessa_bpa` escreve o campo CBO (6 posições) como
   espaços em branco (`_txt(bi.cbo.code if bi.cbo_id else "", ...)`) em vez
   de recusar a linha. Não há confirmação de que o layout oficial aceita CBO
   em branco numa linha BPA-I.
7. **CNS/CID sem validação de formato/dígito verificador.** `_scrub` remove
   apenas caracteres de controle (proteção contra injeção de linha, CSO
   2026-07-28 finding #1) — não valida o dígito verificador do CNS (15
   dígitos, algoritmo específico) nem o formato do CID-10 (letra + dígitos).
   Um CNS/CID malformado é truncado/preenchido como qualquer texto livre.
8. **Origem do CNES do header.** `_cnes_of` lê
   `competencia.establishment.cnes_code` — que pode ser a FK governada
   (`core.CNESEstablishment`) OU o texto legado não reconciliado
   (`legacy_cnes_text`, ver `apps/organization/models.py` Facility). Um CNES
   legado nunca reconciliado com o catálogo governado entra na remessa sem
   aviso.

## O que ESTÁ coberto pelo teste de regressão

`test_sus_remessa_golden.py` cobre os quatro tipos de remessa pedidos,
cada um com header + linha(s) de detalhe + (quando aplicável) linha
secundária, comparados byte-a-byte contra um arquivo golden:

| Tipo | Teste | Golden |
|---|---|---|
| BPA-C + BPA-I | `RemessaBpaLayoutRegressionTests` | `golden/remessa_bpa_golden.txt` |
| APAC + secundário | `RemessaApacLayoutRegressionTests` | `golden/remessa_apac_golden.txt` |
| AIH + secundário | `RemessaAihLayoutRegressionTests` | `golden/remessa_aih_golden.txt` |

Os arquivos golden foram gerados chamando as próprias funções puras do
módulo (`gerar_remessa_bpa`/`gerar_remessa_apac`/`gerar_remessa_aih`) fora do
Django, com objetos equivalentes aos criados nos testes — não foram
digitados à mão, para eliminar erro de transcrição.

Qualquer mudança futura, intencional, ao layout deve regenerar os arquivos
golden na mesma revisão (e idealmente vir acompanhada de uma nota aqui, se
reduzir alguma das divergências acima).
