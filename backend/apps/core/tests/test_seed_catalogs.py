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

import textwrap
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

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

    databases: set[str] = set()

    def setUp(self) -> None:
        import tempfile

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


class ManifestoDoRepoTests(SimpleTestCase):
    """O manifesto versionado tem de ser legível e coerente com o repo."""

    databases: set[str] = set()

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
