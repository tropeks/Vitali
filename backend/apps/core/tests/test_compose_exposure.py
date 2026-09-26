"""
Guarda do compose de dev (ordem 027, regra da forge de 17/09/2026).

Em 17/09 um ``docker compose up`` na forge publicou redis sem senha, postgres e
django em ``0.0.0.0`` para a LAN por 1h46. O firewall da forge não protegia:
porta publicada por Docker entra pelo hook FORWARD depois do DNAT e nunca passa
pelo ``input`` com policy drop. O #221 fechou postgres, redis e django no
``master``. Esta guarda impede que a correção se perca (a ``onda0`` não a tinha)
e cobre os serviços que o #221 deixou de fora.

O alvo é o par que ``docker compose up`` carrega sem ``-f``:
``docker-compose.yml`` e ``docker-compose.override.yml``. Staging e produção
ficam fora: o nginx de produção publica 80/443 por projeto, e o staging roda na
lab atrás do túnel.

A guarda lê o YAML parseado, nunca conta texto. No CI a raiz do repositório é
``parents[4]`` deste arquivo. Na lab, ``scripts/pytest.sh`` põe os arquivos de
compose na raiz do overlay. Arquivo ausente reprova: guarda que se pula em
silêncio é verde falso.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from django.test import SimpleTestCase

_RAIZ = Path(__file__).resolve().parents[4]
_ARQUIVOS_DEV = ("docker-compose.yml", "docker-compose.override.yml")
_LOOPBACK = "127.0.0.1"


def _carregar(nome: str) -> dict:
    caminho = _RAIZ / nome
    if not caminho.is_file():
        raise AssertionError(
            f"{caminho} não existe. No CI a raiz é o checkout; na lab, rode pelo "
            "scripts/pytest.sh, que põe os arquivos de compose no overlay."
        )
    return yaml.safe_load(caminho.read_text()) or {}


def _bind_da_porta(porta) -> str | None:
    """O endereço de bind no host de uma entrada de ``ports``, ou None se não há.

    Sintaxe curta: ``"HOST_IP:HOST:CONTAINER"`` tem bind; ``"HOST:CONTAINER"`` e
    ``"CONTAINER"`` publicam em todas as interfaces. Sintaxe longa: ``host_ip``.
    """
    if isinstance(porta, dict):
        return porta.get("host_ip")
    texto = str(porta).split("/", 1)[0]  # tira "/udp"
    # ${VAR:-x} pode conter ":"; resolva os padrões antes de contar os campos.
    partes: list[str] = []
    atual, profundidade = "", 0
    for ch in texto:
        if ch == "{":
            profundidade += 1
        elif ch == "}":
            profundidade -= 1
        if ch == ":" and profundidade == 0:
            partes.append(atual)
            atual = ""
        else:
            atual += ch
    partes.append(atual)
    return partes[0] if len(partes) == 3 else None


def _servicos():
    """(arquivo, serviço, definição) de cada serviço dos arquivos de dev."""
    for nome in _ARQUIVOS_DEV:
        for servico, definicao in (_carregar(nome).get("services") or {}).items():
            yield nome, servico, definicao or {}


def _ambiente(servico: dict) -> dict[str, str]:
    env = servico.get("environment") or {}
    if isinstance(env, list):
        return dict(item.split("=", 1) if "=" in item else (item, "") for item in env)
    return {k: "" if v is None else str(v) for k, v in env.items()}


class ComposeDevPublicaSoEmLoopbackTests(SimpleTestCase):
    def test_toda_porta_publicada_tem_bind_em_loopback(self):
        expostas = [
            f"{nome}: {servico} {porta!r}"
            for nome, servico, definicao in _servicos()
            for porta in definicao.get("ports") or []
            if _bind_da_porta(porta) != _LOOPBACK
        ]
        self.assertEqual(
            expostas,
            [],
            "porta publicada fora do loopback (a forge não filtra porta de Docker):\n  "
            + "\n  ".join(expostas),
        )


class ComposeDevRedisExigeSenhaTests(SimpleTestCase):
    def setUp(self):
        self.servicos: dict[str, list[tuple[str, dict]]] = {}
        for nome, servico, definicao in _servicos():
            self.servicos.setdefault(servico, []).append((nome, definicao))

    def test_redis_sobe_com_requirepass_que_falha_alto_sem_a_variavel(self):
        definicoes = self.servicos.get("redis")
        self.assertTrue(definicoes, "serviço redis sumiu do compose de dev")
        comandos = [(nome, d["command"]) for nome, d in definicoes if "command" in d]
        self.assertTrue(comandos, "redis sem command: sobe sem senha")
        for nome, comando in comandos:
            texto = comando if isinstance(comando, str) else " ".join(map(str, comando))
            self.assertIn(
                "--requirepass ${REDIS_PASSWORD:?",
                texto,
                f"{nome}: redis sem --requirepass ${{REDIS_PASSWORD:?...}}",
            )

    def test_healthcheck_do_redis_autentica(self):
        for nome, definicao in self.servicos.get("redis", []):
            teste = (definicao.get("healthcheck") or {}).get("test")
            if teste is None:
                continue
            texto = teste if isinstance(teste, str) else " ".join(map(str, teste))
            self.assertIn("REDIS_PASSWORD", texto, f"{nome}: healthcheck do redis sem senha")

    def test_toda_url_de_redis_carrega_a_senha(self):
        sem_senha = [
            f"{nome}: {servico} {chave}={valor}"
            for nome, servico, definicao in _servicos()
            for chave, valor in _ambiente(definicao).items()
            if chave in ("REDIS_URL", "REDIS_URI")
            and valor.startswith("redis://")
            and ":${REDIS_PASSWORD}@" not in valor
        ]
        self.assertEqual(sem_senha, [], "URL de redis sem senha:\n  " + "\n  ".join(sem_senha))
