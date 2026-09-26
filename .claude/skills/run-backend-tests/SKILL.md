---
name: run-backend-tests
description: Roda a suíte pytest do backend do Vitali NA LAB (contexto docker `lab`, contêiner efêmero sem porta publicada), contra o código do checkout, pelo `scripts/pytest.sh`. Nunca na forge, nunca com compose. Use sempre que for rodar, reproduzir ou depurar teste de backend do Vitali, ou rodar ruff/mypy na imagem de teste.
---

# Rodar teste de backend do Vitali

## A regra

**A forge não roda compose do Vitali** (regra do Imediato, 17/09/2026). Nem para rodar a
suíte, nem "só um minuto". Em 17/09 um `docker compose up` na forge publicou redis sem senha,
postgres e django em `0.0.0.0` para a LAN por 1h46. Porta publicada por Docker entra pelo hook
FORWARD depois do DNAT e nunca passa pelo `input` com policy drop do nftables. A forge guarda
segredos que não são do Vitali.

Teste de backend roda **no CI** (jobs `Backend — Lint & Types` e `Backend — Tests`) ou **na
lab**, por este wrapper.

## Comando

A partir da raiz do checkout:

```bash
scripts/pytest.sh apps/core/tests/test_auth.py          # um alvo
scripts/pytest.sh apps/core/tests/test_auth.py -x -k 023
scripts/pytest.sh                                        # a suíte inteira (~1h30)
PYTEST_NO_BUILD=1 scripts/pytest.sh <alvo>               # reusa as imagens já construídas
PYTEST_CMD="ruff check apps/ vitali/" scripts/pytest.sh  # outro comando na mesma imagem
```

Recibo de ordem: `maestro evidence --record --label order-NN -- scripts/pytest.sh`.

O wrapper:

1. descarta `DOCKER_HOST`/`DOCKER_CONTEXT` e fala **só** com `docker --context lab`;
2. reexecuta a si mesmo sob `sg docker` quando a sessão é anterior à entrada no grupo;
3. constrói `vitali-test:x` (`INSTALL_DEV=true`, a partir de `./backend`) e o overlay
   `vitali-test:x-full`, com `scripts/` em `/scripts` e os arquivos de compose de dev em `/`;
4. roda um contêiner `--rm` com `--name vpytest-<data>-<pid>` na rede `v018net`, onde postgres
   e redis vivem sem porta publicada, com `COVERAGE_FILE=/tmp/.coverage`.

## Por que cada peça é obrigatória

| peça | sem ela |
|---|---|
| `--context lab` | o teste roda na forge |
| overlay de `scripts/` | as 5 falhas de `test_drill_metric` **não** são ambientais: ele executa `/scripts/drill_metric.sh` |
| compose no overlay | `test_compose_exposure` reprova por arquivo ausente (de propósito: guarda que se pula é verde falso) |
| `COVERAGE_FILE=/tmp/.coverage` | `INTERNALERROR` do pytest-cov (uid 1001 contra 1000) |
| `--name` único | depois de uma queda, confira `docker --context lab ps -a --filter name=vpytest` antes de relançar |

## O que este skill mandava antes, e por que era perigoso

Até a ordem 027 (26/09/2026), o `master` trazia um wrapper que fazia
`sudo -n docker run --network vitali_default ...` **no daemon local**, contra a rede de uma
stack de compose de pé. Seguido na forge, ele exigia exatamente o `docker compose up` que
expôs a LAN. Se encontrar esse texto em algum branch antigo, não o siga.

## Gotchas vizinhos

- **`docker compose exec django pytest` mente**: o contêiner roda a imagem baked, sem o bind
  do checkout, e testa código velho. Além disso, exige compose de pé.
- **Teste que constrói schema real** leva de 1 a 3 min cada. Dois provisionamentos reais na
  mesma transação de teste esbarram em `pending trigger events`; o contorno é
  `SET CONSTRAINTS ALL IMMEDIATE` entre os dois (ordem 022).
- **Permissão nova em `DEFAULT_ROLES` não propaga** para tenant já provisionado: rode
  `create_default_roles --overwrite` por tenant, ou a feature nasce invisível no menu.
