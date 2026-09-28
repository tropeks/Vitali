"""Prova da ordem 035 — sonda HTTP que roda DENTRO da rede do projeto efêmero.

Sem porta publicada: a sonda é um contêiner na rede do compose e fala com o
serviço ``django`` pelo nome, com o ``Host`` da clínica de prova e
``X-Forwarded-Proto: https`` (o mesmo que o healthcheck do staging manda).

Modo ``lista`` (padrão): ``GET /api/v1/portal/access/`` como admin da clínica,
a cada 0,2 s, até receber SIGTERM. Cada amostra sai numa linha JSON com o
relógio do host da lab (o mesmo dos eventos do docker, que o ``analise.py``
usa para saber quem servia cada amostra): ``{"t": ..., "s": 200}`` ou
``{"t": ..., "s": "erro:ConnectionRefusedError"}``. A lista lê a tabela que a
0004 da 033 muda: com o código novo e o schema velho ela responde 500.

Modo ``ativa``: um ``POST /api/v1/portal/access/activate/`` como o paciente,
com o token do convite gravado pela release anterior. Uma linha JSON e sai.
"""

import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

BASE = "http://django:8000/api/v1/portal/access/"
parar = False


def _para(*_):
    global parar
    parar = True


def _pede(url, token, corpo=None):
    dados = None if corpo is None else json.dumps(corpo).encode()
    req = urllib.request.Request(
        url,
        data=dados,
        headers={
            "Host": os.environ["SONDA_HOST"],
            "X-Forwarded-Proto": "https",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")
    except Exception as err:  # conexão recusada, nome sumido: a troca de contêiner
        return f"erro:{type(err).__name__}", ""


def _linha(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def lista():
    signal.signal(signal.SIGTERM, _para)
    token = os.environ["SONDA_TOKEN"]
    while not parar:
        t = time.time()
        status, _ = _pede(BASE, token)
        _linha({"t": t, "s": status})
        time.sleep(0.2)


def ativa():
    status, corpo = _pede(
        BASE + "activate/",
        os.environ["SONDA_TOKEN"],
        {"invite_token": os.environ["SONDA_CONVITE"]},
    )
    _linha({"t": time.time(), "s": status, "corpo": corpo[:300]})


{"lista": lista, "ativa": ativa}[os.environ.get("SONDA_MODO", "lista")]()
