"""
Tests for the ``seed_catalogs`` orchestrator (ordem 002 / Prioridade 2).

O comando não importa nada por conta própria: ele lê o manifesto versionado,
chama os ``import_*`` que já existem e confere a contagem. Então o que estes
testes protegem é o **contrato** dele, não o parsing de CSV — que é dos
importers e já tem teste próprio.

O caso central é o da versão ausente. O rótulo de versão diz QUAL release da
fonte oficial foi carregada; adivinhá-lo fabricaria proveniência, que
``.maestro/INTENT.md`` §Limites proíbe. Por isso ``version = ""`` tem de ser um
erro barulhento, com o nome do catálogo, e nunca um default silencioso — é a
única garantia de que ninguém "resolve" o problema pondo um valor plausível.

O segundo caso é a contagem abaixo do esperado. Em 31/07 o CID-O entrou
``partial`` com 772 de 816 linhas, o log de proveniência registrou, e ninguém
olhou. Um import que termina sem erro mas deixa o catálogo pela metade tem de
reprovar aqui.
"""

from __future__ import annotations

import tempfile
import textwrap
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from apps.test_utils import TenantTestCase

MANIFEST_UM_CATALOGO = """
[[catalog]]
key = "cid10"
command = "import_cid10"
source_arg = "--source"
version_arg = "--cid-version"
file = "cid10_full.csv"
etl = "etl_cid10_datasus.py"
model = "core.CID10Code"
expected_rows = 14233
version = {version}
"""


def _escreve_manifesto(tmp: Path, version: str = '""', extra: str = "") -> Path:
    caminho = tmp / "manifest.toml"
    caminho.write_text(
        textwrap.dedent(MANIFEST_UM_CATALOGO.format(version=version)) + extra,
        encoding="utf-8",
    )
    return caminho


class SeedCatalogsContratoTests(SimpleTestCase):
    """Contrato do orquestrador — nada aqui toca banco."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_manifesto_inexistente_falha_dizendo_o_caminho(self) -> None:
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_catalogs", "--manifest", str(self.tmp / "nao-existe.toml"), "--plan")
        self.assertIn("manifesto não encontrado", str(ctx.exception))

    def test_manifesto_sem_entrada_de_catalogo_falha(self) -> None:
        vazio = self.tmp / "manifest.toml"
        vazio.write_text('[meta]\nreadme = "x"\n', encoding="utf-8")
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_catalogs", "--manifest", str(vazio), "--plan")
        self.assertIn("sem nenhuma entrada", str(ctx.exception))

    def test_campo_obrigatorio_ausente_nomeia_o_catalogo_e_o_campo(self) -> None:
        parcial = self.tmp / "manifest.toml"
        parcial.write_text(
            '[[catalog]]\nkey = "cid10"\ncommand = "import_cid10"\n',
            encoding="utf-8",
        )
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_catalogs", "--manifest", str(parcial), "--plan")
        mensagem = str(ctx.exception)
        self.assertIn("cid10", mensagem)
        self.assertIn("expected_rows", mensagem)

    def test_versao_vazia_reprova_e_nao_ha_default(self) -> None:
        """O caso central: sem rótulo de versão, o comando recusa."""
        manifesto = _escreve_manifesto(self.tmp, version='""')
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_catalogs", "--manifest", str(manifesto), "--plan")
        self.assertIn("cid10", str(ctx.exception))

    def test_versao_so_com_espacos_conta_como_vazia(self) -> None:
        manifesto = _escreve_manifesto(self.tmp, version='"   "')
        with self.assertRaises(CommandError):
            call_command("seed_catalogs", "--manifest", str(manifesto), "--plan")

    def test_catalogo_bloqueado_e_pulado_sem_reprovar(self) -> None:
        """LOINC espera cadastro e CBHPM espera compra: fato registrado, não falha."""
        bloqueado = self.tmp / "manifest.toml"
        bloqueado.write_text(
            textwrap.dedent(
                """
                [[catalog]]
                key = "cbhpm"
                command = "import_cbhpm"
                source_arg = "--source"
                version_arg = "--cbhpm-version"
                file = "cbhpm_full.csv"
                model = "core.CBHPMItem"
                expected_rows = 0
                version = ""
                blocked = "tabela licenciada — decisao de compra"
                """
            ),
            encoding="utf-8",
        )
        call_command("seed_catalogs", "--manifest", str(bloqueado), "--plan")

    def test_only_desconhecido_lista_os_disponiveis(self) -> None:
        manifesto = _escreve_manifesto(self.tmp, version='"2008"')
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "seed_catalogs", "--manifest", str(manifesto), "--plan", "--only", "inexistente"
            )
        mensagem = str(ctx.exception)
        self.assertIn("inexistente", mensagem)
        self.assertIn("cid10", mensagem)

    def test_source_dir_obrigatorio_fora_do_modo_plan(self) -> None:
        manifesto = _escreve_manifesto(self.tmp, version='"2008"')
        with self.assertRaises(CommandError) as ctx:
            call_command("seed_catalogs", "--manifest", str(manifesto))
        self.assertIn("--source-dir", str(ctx.exception))

    # ── ordem 028: pending_source e sha256 ──────────────────────────────────

    def test_pending_source_e_pulado_sem_reprovar_mesmo_com_versao_vazia(self) -> None:
        """formulario_doses: version="" MAS pending_source preenchido não é a
        recusa central (SEM VERSÃO) — é fato registrado (fonte pendente)."""
        manifesto = self.tmp / "manifest.toml"
        manifesto.write_text(
            textwrap.dedent(
                """
                [[catalog]]
                key = "formulario_doses"
                command = "import_formulary"
                source_arg = "--file"
                version_arg = "--version"
                file = "formulario_doses.csv"
                model = "pharmacy.DoseRule"
                expected_rows = 0
                version = ""
                pending_source = "farmacêutico contratado"
                """
            ),
            encoding="utf-8",
        )
        # Não deve levantar CommandError (nenhuma falha) mesmo com version vazia.
        call_command("seed_catalogs", "--manifest", str(manifesto), "--plan")


class SeedCatalogsSha256Tests(TenantTestCase):
    """Ordem 028: conferência de sha256 — fora de SimpleTestCase porque
    ``count_rows`` (chamado antes da checagem de sha256) já toca o banco
    (``core.CID10Code.objects.count()``), mesmo sem nenhum import real
    acontecer aqui."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_sha256_divergente_falha_nomeando_o_catalogo(self) -> None:
        source_dir = self.tmp / "fontes"
        source_dir.mkdir()
        (source_dir / "cid10_full.csv").write_text("conteudo de teste", encoding="utf-8")

        wrong_digest = "0" * 64
        manifesto = _escreve_manifesto(
            self.tmp, version='"2008"', extra=f'sha256 = "{wrong_digest}"\n'
        )
        buffer = StringIO()
        with self.assertRaises(CommandError) as ctx:
            call_command(
                "seed_catalogs",
                "--manifest",
                str(manifesto),
                "--source-dir",
                str(source_dir),
                stdout=buffer,
            )
        self.assertIn("cid10", str(ctx.exception))
        self.assertIn("SHA256 DIVERGENTE", buffer.getvalue())

    def test_sha256_confere_prossegue_para_o_import_real(self) -> None:
        import hashlib

        source_dir = self.tmp / "fontes"
        source_dir.mkdir()
        source_file = source_dir / "cid10_full.csv"
        source_file.write_text("conteudo de teste", encoding="utf-8")
        digest = hashlib.sha256(source_file.read_bytes()).hexdigest()

        manifesto = _escreve_manifesto(self.tmp, version='"2008"', extra=f'sha256 = "{digest}"\n')
        buffer = StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "seed_catalogs",
                "--manifest",
                str(manifesto),
                "--source-dir",
                str(source_dir),
                stdout=buffer,
            )
        # The sha256 check passed (not the failure) — it fails further along,
        # inside the real import_cid10 command, on the fabricated CSV content.
        self.assertNotIn("SHA256 DIVERGENTE", buffer.getvalue())


class ManifestoDoRepoTests(SimpleTestCase):
    """O manifesto versionado tem de ser legível e coerente com o repo."""

    @property
    def manifesto(self) -> Path:
        # backend/apps/core/tests/ -> repo root
        return Path(__file__).resolve().parents[4] / "scripts" / "catalogs" / "manifest.toml"

    def test_manifesto_versionado_carrega_e_nao_tem_versao_preenchida(self) -> None:
        """Versão preenchida no repo seria proveniência inventada para todo ambiente."""
        import tomllib

        if not self.manifesto.is_file():
            self.skipTest("manifesto fora da imagem (scripts/ não é copiado para o container)")
        dados = tomllib.load(self.manifesto.open("rb"))
        entradas = dados["catalog"]
        self.assertTrue(entradas)
        for entrada in entradas:
            self.assertEqual(
                str(entrada.get("version", "")).strip(),
                "",
                f"{entrada['key']}: manifesto do repo não pode trazer versão preenchida",
            )

    def test_todo_comando_do_manifesto_existe(self) -> None:
        import tomllib

        from django.core.management import get_commands

        if not self.manifesto.is_file():
            self.skipTest("manifesto fora da imagem (scripts/ não é copiado para o container)")
        disponiveis = set(get_commands())
        for entrada in tomllib.load(self.manifesto.open("rb"))["catalog"]:
            self.assertIn(entrada["command"], disponiveis, f"{entrada['key']}: comando inexistente")
