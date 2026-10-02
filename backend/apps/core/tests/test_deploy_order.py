"""
Ordem 035 — o deploy migra com a imagem nova ANTES de subir o código novo.

Até a 033, ``docs/DEPLOY.md`` mandava ``pull`` → ``up -d`` → ``migrate_schemas``.
Com isso, todo ``AddField`` de tenant tinha uma janela em que o código novo já
servia e consultava uma coluna que ainda não existia: na 033, o portal inteiro de
um tenant ainda não migrado responderia 500, porque ``IsPortalSelfAccess`` lê o
model em todo request. Isso contradiz a premissa de ``docs/TENANT_MIGRATIONS.md``:
migration de tenant é só aditiva (fase 1 de 2) para que a release ANTERIOR rode
contra o schema novo, e não o contrário.

A ordem certa é o expand/contract no deploy: a imagem nova migra num contêiner
descartável (``compose run --rm``), com a release anterior ainda no ar, e só
depois o ``up`` troca o código. Migrar por ``exec`` não serve: ``exec`` roda no
contêiner que está no ar, ou seja, na imagem ANTERIOR, que não conhece as
migrations novas.

Aqui o ``scripts/deploy.sh`` roda de verdade, com um ``docker`` falso no PATH
que só registra cada chamada (a forge não roda compose do Vitali). A prova com
docker de verdade, imagens reais antes e depois da 033 e a release anterior
servindo durante a migração está em ``scripts/lab-deploy-prova/``.

Os arquivos vêm da raiz do repositório: no CI, ``parents[4]`` deste arquivo; na
lab, ``scripts/pytest.sh`` põe ``scripts/`` e os docs de deploy no overlay.
Arquivo ausente reprova: guarda que se pula em silêncio é verde falso.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

_RAIZ = Path(__file__).resolve().parents[4]
_DEPLOY_SH = "scripts/deploy.sh"
_MIGRATE_SH = "scripts/migrate_schemas.sh"
_DOCS = ("docs/DEPLOY.md", "docs/TENANT_MIGRATIONS.md")
_INFRA = {"postgres", "redis"}
_FLAGS_COM_VALOR = {"-p", "--project-name", "-f", "--file", "--env-file", "--profile"}

_DOCKER_FALSO = """#!{python}
import json, os, sys
argv = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps({{"argv": argv, "IMAGE_TAG": os.environ.get("IMAGE_TAG")}}) + "\\n")
if "config" in argv and "--images" in argv:
    padrao = "ghcr.io/tropeks/vitali-backend:" + os.environ.get("IMAGE_TAG", "")
    # Como o compose de verdade: `config --images <serviços>` inclui as dependências.
    print("postgres:16-alpine")
    print("redis:7-alpine")
    print(os.environ.get("FAKE_DOCKER_IMAGEM", padrao))
falha = os.environ.get("FAKE_DOCKER_FALHA")
if falha and falha in argv:
    sys.exit(1)
# "chave:n" = a chave falha nas n primeiras chamadas e passa nas seguintes.
vezes = os.environ.get("FAKE_DOCKER_FALHA_VEZES")
if vezes:
    chave, n = vezes.rsplit(":", 1)
    if chave in argv:
        contador = os.environ["FAKE_DOCKER_LOG"] + ".contador"
        feitas = int(open(contador).read()) if os.path.exists(contador) else 0
        open(contador, "w").write(str(feitas + 1))
        if feitas < int(n):
            sys.exit(1)
"""


def _arquivo(relativo: str) -> Path:
    caminho = _RAIZ / relativo
    if not caminho.is_file():
        raise AssertionError(
            f"{caminho} não existe. No CI a raiz é o checkout; na lab, rode pelo "
            "scripts/pytest.sh, que põe scripts/ e os docs de deploy no overlay."
        )
    return caminho


def _subcomando(argv: list[str]) -> tuple[str | None, list[str]]:
    """``["compose", "-p", "x", "run", "--rm", "django", ...]`` -> ``("run", [...])``."""
    if not argv or argv[0] != "compose":
        return None, argv
    resto = argv[1:]
    i = 0
    while i < len(resto):
        arg = resto[i]
        if arg in _FLAGS_COM_VALOR:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            return arg, resto[i + 1 :]
    return None, []


def _servicos_do_up(args: list[str]) -> set[str]:
    return {a for a in args if not a.startswith("-")}


class _Chamadas:
    def __init__(self, linhas: list[dict]):
        self.linhas = linhas

    def indices(self, pred) -> list[int]:
        return [i for i, linha in enumerate(self.linhas) if pred(linha)]

    def migracoes(self) -> list[int]:
        return self.indices(lambda linha: "migrate_schemas" in linha["argv"])

    def ups_da_aplicacao(self) -> list[int]:
        def pred(linha):
            sub, args = _subcomando(linha["argv"])
            return sub == "up" and not (_servicos_do_up(args) and _servicos_do_up(args) <= _INFRA)

        return self.indices(pred)


class DeployShTests(SimpleTestCase):
    def _roda(self, **env_extra) -> tuple[subprocess.CompletedProcess, _Chamadas]:
        script = _arquivo(_DEPLOY_SH)
        tmp = Path(tempfile.mkdtemp(prefix="deploy035-"))
        docker = tmp / "docker"
        docker.write_text(_DOCKER_FALSO.format(python=sys.executable))
        docker.chmod(docker.stat().st_mode | stat.S_IEXEC)
        log = tmp / "chamadas.jsonl"
        env = {
            **os.environ,
            "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_DOCKER_LOG": str(log),
            "COMPOSE_PROJECT_NAME": "vitali-staging",
            "COMPOSE_FILE": "docker-compose.staging.yml",
            "COMPOSE_ENV_FILE": ".env.staging",
            "IMAGE_TAG": "sha-nova",
            "GHCR_REPO": "tropeks",
            **env_extra,
        }
        proc = subprocess.run(
            ["bash", str(script)],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        linhas = [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []
        return proc, _Chamadas(linhas)

    def test_migra_antes_de_subir_o_codigo_novo(self):
        proc, chamadas = self._roda()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        migracoes, ups = chamadas.migracoes(), chamadas.ups_da_aplicacao()
        self.assertTrue(migracoes, "deploy.sh não roda migrate_schemas")
        self.assertTrue(ups, "deploy.sh não sobe a aplicação")
        self.assertLess(
            max(migracoes),
            min(ups),
            "o código novo sobe antes de o schema estar migrado: é a janela da coluna inexistente",
        )

    def test_migra_num_conteiner_descartavel_da_imagem_nova_nunca_por_exec(self):
        _, chamadas = self._roda()
        for i in chamadas.migracoes():
            linha = chamadas.linhas[i]
            sub, args = _subcomando(linha["argv"])
            self.assertEqual(sub, "run", f"migrate_schemas fora de `compose run`: {linha['argv']}")
            self.assertIn("--rm", args)
            self.assertEqual(linha["IMAGE_TAG"], "sha-nova")

    def test_shared_depois_tenant_depois_particoes_e_tudo_antes_do_up(self):
        _, chamadas = self._roda()

        def primeira(*palavras):
            achadas = chamadas.indices(lambda linha: all(p in linha["argv"] for p in palavras))
            self.assertTrue(achadas, f"deploy.sh não roda {palavras}")
            return achadas[0]

        shared = primeira("migrate_schemas", "--shared")
        tenant = primeira("migrate_schemas", "--tenant")
        particoes = primeira("ensure_audit_partitions")
        self.assertLess(shared, tenant)
        self.assertLess(tenant, particoes)
        self.assertLess(particoes, min(chamadas.ups_da_aplicacao()))

    def test_pull_vem_antes_da_migracao(self):
        _, chamadas = self._roda()
        pulls = chamadas.indices(lambda linha: _subcomando(linha["argv"])[0] == "pull")
        self.assertTrue(pulls)
        self.assertLess(min(pulls), min(chamadas.migracoes()))

    def test_migracao_que_falha_nao_sobe_o_codigo_novo(self):
        """Tenant 47 de 200 falhou: a release anterior continua no ar, contra os
        schemas já migrados e os ainda não migrados (é o que a fase 1 garante)."""
        proc, chamadas = self._roda(FAKE_DOCKER_FALHA="--tenant")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(chamadas.ups_da_aplicacao(), [])

    def test_imagem_fixada_por_overlay_recusa_antes_de_tocar_em_qualquer_coisa(self):
        """Revisão da 035: o docker-compose.lab.yml fixa as imagens por digest e
        ignora IMAGE_TAG. Sem a conferência, o deploy migraria e subiria a imagem
        VELHA e terminaria dizendo que a release nova está no ar."""
        proc, chamadas = self._roda(
            FAKE_DOCKER_IMAGEM="ghcr.io/tropeks/vitali-backend@sha256:velho"
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RECUSADO", proc.stderr)
        subcomandos = [_subcomando(linha["argv"])[0] for linha in chamadas.linhas]
        self.assertEqual(subcomandos, ["config"])

    def test_digest_em_image_tag_casa_com_o_pin(self):
        proc, chamadas = self._roda(
            IMAGE_TAG="sha256:novo",
            FAKE_DOCKER_IMAGEM="ghcr.io/tropeks/vitali-backend@sha256:novo",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(chamadas.ups_da_aplicacao())

    def test_sem_imagem_do_backend_recusa(self):
        proc, _ = self._roda(FAKE_DOCKER_IMAGEM="busybox:latest")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("vitali-backend", proc.stderr)

    def test_confere_a_imagem_antes_do_pull(self):
        _, chamadas = self._roda()
        subcomandos = [_subcomando(linha["argv"])[0] for linha in chamadas.linhas]
        self.assertEqual(subcomandos[0], "config")
        self.assertIn("--images", chamadas.linhas[0]["argv"])

    def test_up_espera_a_aplicacao_ficar_saudavel(self):
        _, chamadas = self._roda()
        for i in chamadas.ups_da_aplicacao():
            self.assertIn("--wait", chamadas.linhas[i]["argv"])

    def test_compose_recebe_projeto_arquivos_e_env_file(self):
        _, chamadas = self._roda(COMPOSE_FILE="docker-compose.staging.yml:docker-compose.lab.yml")
        self.assertTrue(chamadas.linhas)
        for linha in chamadas.linhas:
            argv = linha["argv"]
            self.assertEqual(argv[0], "compose")
            self.assertIn("vitali-staging", argv)
            self.assertIn("docker-compose.lab.yml", argv)
            self.assertIn(".env.staging", argv)


def _linhas_logicas(texto: str) -> list[str]:
    """Junta as continuações ``\\`` de shell numa linha só."""
    return texto.replace("\\\n", " ").splitlines()


_EXEC_MIGRA = re.compile(r"\bexec\b.*\bmigrate_schemas\b")


class DocsDoDeployTests(SimpleTestCase):
    def test_nenhum_doc_nem_script_migra_pelo_conteiner_no_ar(self):
        """``exec`` roda na imagem que está no ar — no deploy, a ANTERIOR."""
        for relativo in (*_DOCS, _MIGRATE_SH):
            for linha in _linhas_logicas(_arquivo(relativo).read_text()):
                self.assertIsNone(
                    _EXEC_MIGRA.search(linha),
                    f"{relativo}: migrate_schemas por exec: {linha.strip()}",
                )

    def test_deploy_md_manda_o_deploy_pelo_script(self):
        texto = _arquivo("docs/DEPLOY.md").read_text()
        secao = texto.split("## Release Pipeline", 1)[1].split("\n## ", 1)[0]
        self.assertIn("scripts/deploy.sh", secao)
        for bloco in re.findall(r"```(?:bash)?\n(.*?)```", secao, re.S):
            self.assertNotIn(
                "up -d", bloco, "o Release Pipeline sobe o código à mão, fora da ordem"
            )


class DeployBackfillTests(SimpleTestCase):
    """Ordem 038 — o deploy de um banco com trilha antiga parava no
    ``ensure_audit_partitions`` (as linhas legadas vão para a DEFAULT) e exigia o
    ``backfill_audit_partitions --execute`` à mão, mais um segundo deploy. Achado
    do ship de 28/09; produção bate no mesmo ponto."""

    def _roda(self, **env_extra):
        return DeployShTests("test_migra_antes_de_subir_o_codigo_novo")._roda(**env_extra)

    def _idx(self, chamadas, *palavras):
        return chamadas.indices(lambda linha: all(p in linha["argv"] for p in palavras))

    def test_ensure_que_acusa_default_dispara_o_backfill_e_repete_o_ensure(self):
        proc, chamadas = self._roda(FAKE_DOCKER_FALHA_VEZES="ensure_audit_partitions:1", DEPLOY_AUTO_BACKFILL="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ensures = self._idx(chamadas, "ensure_audit_partitions")
        backfills = self._idx(chamadas, "backfill_audit_partitions", "--execute")
        self.assertEqual(len(ensures), 2, "o ensure tem de repetir depois do backfill")
        self.assertEqual(len(backfills), 1)
        self.assertLess(ensures[0], backfills[0])
        self.assertLess(backfills[0], ensures[1])
        self.assertLess(ensures[1], min(chamadas.ups_da_aplicacao()))

    def test_backfill_roda_em_conteiner_descartavel_da_imagem_nova(self):
        _, chamadas = self._roda(FAKE_DOCKER_FALHA_VEZES="ensure_audit_partitions:1", DEPLOY_AUTO_BACKFILL="1")
        (i,) = self._idx(chamadas, "backfill_audit_partitions", "--execute")
        sub, args = _subcomando(chamadas.linhas[i]["argv"])
        self.assertEqual(sub, "run")
        self.assertIn("--rm", args)
        self.assertEqual(chamadas.linhas[i]["IMAGE_TAG"], "sha-nova")

    def test_sem_linha_na_default_nao_ha_backfill(self):
        proc, chamadas = self._roda()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self._idx(chamadas, "backfill_audit_partitions"), [])
        self.assertEqual(len(self._idx(chamadas, "ensure_audit_partitions")), 1)

    def test_ensure_que_continua_falhando_depois_do_backfill_aborta_o_deploy(self):
        proc, chamadas = self._roda(FAKE_DOCKER_FALHA_VEZES="ensure_audit_partitions:2", DEPLOY_AUTO_BACKFILL="1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(chamadas.ups_da_aplicacao(), [])
        self.assertEqual(len(self._idx(chamadas, "backfill_audit_partitions", "--execute")), 1)

    def test_dry_run_do_backfill_vem_antes_do_execute(self):
        _, chamadas = self._roda(FAKE_DOCKER_FALHA_VEZES="ensure_audit_partitions:1", DEPLOY_AUTO_BACKFILL="1")
        todas = self._idx(chamadas, "backfill_audit_partitions")
        (execute,) = self._idx(chamadas, "backfill_audit_partitions", "--execute")
        self.assertEqual(len(todas), 2)
        self.assertLess(todas[0], execute)

    def test_migracao_de_tenant_que_falha_nao_chega_ao_ensure_nem_ao_backfill(self):
        proc, chamadas = self._roda(FAKE_DOCKER_FALHA="--tenant")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._idx(chamadas, "ensure_audit_partitions"), [])
        self.assertEqual(self._idx(chamadas, "backfill_audit_partitions"), [])

    def test_backfill_que_falha_aborta_o_deploy(self):
        proc, chamadas = self._roda(
            FAKE_DOCKER_FALHA_VEZES="ensure_audit_partitions:1",
            FAKE_DOCKER_FALHA="--execute",
            DEPLOY_AUTO_BACKFILL="1"
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(chamadas.ups_da_aplicacao(), [])

    def test_deploy_md_documenta_o_backfill_automatico(self):
        texto = _arquivo("docs/DEPLOY.md").read_text()
        passo3 = texto.split("`scripts/migrate_schemas.sh`:", 1)[1].split("4. `up -d --wait`", 1)[0]
        self.assertIn("backfill_audit_partitions --execute", passo3)
        self.assertIn("order 038", passo3)
        self.assertIn("DEPLOY_AUTO_BACKFILL=1", passo3)
        self.assertIn("off by default", passo3)
        self.assertIn("writes to `core_auditlog`", passo3)

    def test_por_padrao_o_backfill_automatico_esta_desligado(self):
        """ADR-0001: rodar o backfill em staging/produção é decisão posterior, a
        medir antes e fora do pico. Sem a flag, o deploy avisa e aborta antes do up."""
        proc, chamadas = self._roda(FAKE_DOCKER_FALHA_VEZES="ensure_audit_partitions:1")
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._idx(chamadas, "backfill_audit_partitions"), [])
        self.assertEqual(chamadas.ups_da_aplicacao(), [])
        self.assertIn("DEPLOY_AUTO_BACKFILL", proc.stderr)

    def test_flag_diferente_de_1_continua_desligada(self):
        proc, chamadas = self._roda(
            FAKE_DOCKER_FALHA_VEZES="ensure_audit_partitions:1", DEPLOY_AUTO_BACKFILL="0"
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(self._idx(chamadas, "backfill_audit_partitions"), [])
