#!/usr/bin/env python3
"""Prova da ordem 035 — lê as amostras da sonda e os eventos do docker e dá o veredito.

Roda na forge, só sobre arquivos: não fala com docker nem com banco.

    analise.py quebra  <sonda.jsonl>
        o controle: o código novo no ar antes do migrate. Passa se a sonda viu 5xx;
        sem 5xx a sonda não enxerga o defeito, e a prova do deploy não valeria nada.
    analise.py tudo200 <sonda.jsonl>
        toda amostra é 200 (e há amostra).
    analise.py deploy  <sonda.jsonl> <eventos.jsonl>
        a sonda ligada durante o scripts/deploy.sh. Os eventos do docker (mesmo
        relógio da sonda: os dois vêm do host da lab) dizem quem servia cada amostra:
          - nenhum 5xx, e nenhum status que não seja 200;
          - erro de conexão só na troca de contêiner (do fim do django anterior ao
            healthcheck do novo): é o intervalo do recreate, não o do schema;
          - a release anterior respondeu 200 depois do migrate de tenant e antes
            da troca: ela serve contra o schema novo (a fase 1 da TENANT_MIGRATIONS);
          - a release nova respondeu 200 depois de saudável.
"""

from __future__ import annotations

import json
import sys

FOLGA = 0.5  # s: a amostra carimba o início do pedido; o evento, o fim do passo


def _diz(texto: str, saida=sys.stdout) -> None:
    """Saída do veredito: este é um CLI, e o recibo é o que ele escreve."""
    saida.write(texto + "\n")


def _jsonl(caminho: str) -> list[dict]:
    with open(caminho) as arq:
        return [json.loads(linha) for linha in arq if linha.strip().startswith("{")]


def _e_5xx(s) -> bool:
    return isinstance(s, int) and s >= 500


def quebra(amostras: list[dict]) -> list[str]:
    falhas = [a for a in amostras if _e_5xx(a["s"])]
    _diz(f"controle: {len(falhas)} de {len(amostras)} amostras com 5xx")
    return [] if falhas else ["a sonda não viu 5xx com o código novo antes do migrate"]


def tudo200(amostras: list[dict]) -> list[str]:
    outras = [a for a in amostras if a["s"] != 200]
    _diz(f"{len(amostras) - len(outras)} de {len(amostras)} amostras com 200")
    if not amostras:
        return ["nenhuma amostra"]
    return [f"amostra não-200: {a}" for a in outras[:5]]


def _marcos(eventos: list[dict]) -> dict[str, float]:
    """Os instantes do deploy, tirados dos eventos dos contêineres do serviço django."""
    django = [
        e
        for e in eventos
        if e.get("Actor", {}).get("Attributes", {}).get("com.docker.compose.service") == "django"
    ]
    django.sort(key=lambda e: e["timeNano"])

    def quando(e):
        return e["timeNano"] / 1e9

    def avulso(e):
        return e["Actor"]["Attributes"].get("com.docker.compose.oneoff") == "True"

    # Os eventos são capturados ao vivo, de logo antes do deploy.sh até o fim dele: os
    # únicos avulsos na janela são os três do migrate_schemas.sh, nesta ordem (shared,
    # tenant, partições; o script é sequencial). Qualquer outro número reprova.
    # Ordem 038: em banco com trilha legada o caminho muda (ensure, dry-run, backfill, ensure) e
    # sobem mais avulsos; esta prova roda em banco limpo e precisa continuar assim.
    avulsos = [e["Actor"]["ID"] for e in django if avulso(e) and e["Action"] == "start"]
    if len(avulsos) != 3:
        raise SystemExit(f"esperava 3 contêineres de migração (shared, tenant, partições): {avulsos}")
    fim_migracao = max(
        quando(e) for e in django if e["Actor"]["ID"] in avulsos and e["Action"] == "die"
    )
    fim_tenant = next(
        quando(e) for e in django if e["Actor"]["ID"] == avulsos[1] and e["Action"] == "die"
    )
    servico = [e for e in django if not avulso(e)]
    anterior_cai = next(
        quando(e)
        for e in servico
        if e["Action"] in ("kill", "stop", "die") and quando(e) >= fim_migracao
    )
    nova_saudavel = next(
        quando(e)
        for e in servico
        if e["Action"] == "health_status: healthy" and quando(e) > anterior_cai
    )
    inicio_migracao = next(
        quando(e) for e in django if e["Actor"]["ID"] == avulsos[0] and e["Action"] == "start"
    )
    return {
        "inicio_migracao": inicio_migracao,
        "fim_tenant": fim_tenant,
        "anterior_cai": anterior_cai,
        "nova_saudavel": nova_saudavel,
    }


def deploy(amostras: list[dict], eventos: list[dict]) -> list[str]:
    m = _marcos(eventos)
    erros: list[str] = []

    def conta(ini, fim):
        return sum(1 for a in amostras if a["s"] == 200 and ini <= a["t"] < fim)

    troca = (m["anterior_cai"] - FOLGA, m["nova_saudavel"] + FOLGA)
    for a in amostras:
        s = a["s"]
        if isinstance(s, str) and troca[0] <= a["t"] <= troca[1]:
            continue
        if s != 200:
            erros.append(f"amostra {a} fora do esperado")
    na_troca = sum(1 for a in amostras if isinstance(a["s"], str))
    faixas = {
        "anterior, antes do migrate": conta(0, m["inicio_migracao"]),
        "anterior, durante o migrate": conta(m["inicio_migracao"], m["fim_tenant"]),
        "anterior, schema já migrado": conta(m["fim_tenant"], m["anterior_cai"]),
        "nova, saudável": conta(m["nova_saudavel"], float("inf")),
    }
    _diz(
        "marcos (s desde o início do migrate): "
        + ", ".join(f"{k}={v - m['inicio_migracao']:.1f}" for k, v in m.items())
    )
    for nome, n in faixas.items():
        _diz(f"  200 com a release {nome}: {n}")
    _diz(f"  sem resposta na troca de contêiner (recreate): {na_troca}")
    _diz(f"  5xx: {sum(1 for a in amostras if _e_5xx(a['s']))} de {len(amostras)} amostras")
    for nome in ("anterior, schema já migrado", "nova, saudável"):
        if not faixas[nome]:
            erros.append(f"nenhuma amostra 200 com a release {nome}")
    return erros[:10]


def main(argv: list[str]) -> int:
    modo, *arquivos = argv
    if modo == "quebra":
        erros = quebra(_jsonl(arquivos[0]))
    elif modo == "tudo200":
        erros = tudo200(_jsonl(arquivos[0]))
    elif modo == "deploy":
        erros = deploy(_jsonl(arquivos[0]), _jsonl(arquivos[1]))
    else:
        raise SystemExit(f"modo desconhecido: {modo}")
    for erro in erros:
        _diz(f"FALHA: {erro}", sys.stderr)
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
