"""
Guarda: a métrica do drill só é escrita se o drill passou E a limpeza foi verificada.

**Por que isto é um teste, e por que ele é sobre um script.** A ordem 011 põe o drill de
restore para rodar toda noite e faz o smoke reprovar quando o drill está velho ou vermelho.
Isso só vale se a métrica for verdadeira: métrica escrita antes da hora afirma uma
restauração que não houve — e alerta que mente é pior que alerta nenhum, porque some com a
dúvida de quem leria o log.

É a mesma disciplina que `scripts/backup.sh:177` já documenta para a métrica dele ("written
HERE, and only here: after pg_dump, encryption and the optional upload"), e a mesma família
de defeito que esta série vem perseguindo — o caminho de erro que reporta sucesso.

O portão vive DENTRO de `scripts/drill_metric.sh`, não no chamador: se morasse no
`run_restore_drill.sh`, bastaria alguém chamar o escritor direto para furá-lo.

Contra o código anterior à ordem 011 estes testes falham — o script não existe.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

_RAIZ = Path(__file__).resolve().parents[4]
_SCRIPT = _RAIZ / "scripts" / "drill_metric.sh"
_METRICA = "vitali_restore_drill_last_success_timestamp_seconds"


def _rodar(destino: Path, **kwargs: str) -> subprocess.CompletedProcess[str]:
    args = ["bash", str(_SCRIPT), "--metrics-dir", str(destino)]
    for chave, valor in kwargs.items():
        args += [f"--{chave.replace('_', '-')}", valor]
    return subprocess.run(args, capture_output=True, text=True, timeout=60)


class DrillMetricGateTests(SimpleTestCase):
    """O portão é do escritor, não do chamador."""

    def _recusa(self, r: subprocess.CompletedProcess[str], motivo: str) -> None:
        """Exige que a falha seja a RECUSA DO PORTÃO, não uma falha qualquer.

        Sem isto, os casos negativos passariam com o script ausente (`bash` sai 127)
        ou com argumento malformado (sai 2) — verde por motivo errado, que é o
        defeito que esta série de ordens vem catalogando. O código 1 é o do portão;
        127 e 2 são outra coisa.
        """
        self.assertEqual(
            r.returncode,
            1,
            f"esperava a recusa do portão (1), veio {r.returncode}. stderr: {r.stderr}",
        )
        self.assertIn(motivo, r.stderr, f"a recusa não diz o porquê. stderr: {r.stderr}")
        self.assertFalse(
            self._arquivo().exists(), "a métrica foi escrita apesar da recusa"
        )

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.destino = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _arquivo(self) -> Path:
        return self.destino / "vitali_restore_drill.prom"

    def test_escreve_quando_o_drill_passou_e_a_limpeza_esta_verificada(self) -> None:
        r = _rodar(
            self.destino,
            duration="12",
            fase1="ok",
            containers="0",
            claros_tmp="0",
            claros_work="0",
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        conteudo = self._arquivo().read_text(encoding="utf-8")
        self.assertIn(_METRICA, conteudo)
        self.assertIn("vitali_restore_drill_duration_seconds 12", conteudo)
        linha = [x for x in conteudo.splitlines() if x.startswith(_METRICA)][0]
        carimbo = int(linha.split()[-1])
        self.assertGreater(carimbo, 1_700_000_000, "o carimbo não parece um unix timestamp")

    def test_nao_escreve_quando_sobrou_texto_claro(self) -> None:
        """Um `.dump` em claro remanescente invalida o drill inteiro.

        Dado clínico em claro no disco é o risco que a ordem 003 existiu para fechar.
        Se sobrou, não houve drill limpo — e a métrica não pode dizer que houve.
        """
        r = _rodar(
            self.destino,
            duration="12",
            fase1="ok",
            containers="0",
            claros_tmp="1",
            claros_work="0",
        )
        self._recusa(r, "limpeza não verificada")

    def test_nao_escreve_quando_sobrou_container(self) -> None:
        r = _rodar(
            self.destino,
            duration="12",
            fase1="ok",
            containers="2",
            claros_tmp="0",
            claros_work="0",
        )
        self._recusa(r, "limpeza não verificada")

    def test_nao_escreve_quando_a_fase_1_reprovou(self) -> None:
        """Limpeza perfeita sobre um restore que falhou continua sendo fracasso."""
        r = _rodar(
            self.destino,
            duration="12",
            fase1="fail",
            containers="0",
            claros_tmp="0",
            claros_work="0",
        )
        self._recusa(r, "fase 1 não passou")

    def test_recusa_contador_ausente_em_vez_de_assumir_zero(self) -> None:
        """Argumento faltando é erro, não zero.

        Tratar ausência como sucesso é como ler `grep -c` sobre saída vazia e concluir
        que está tudo bem — o defeito que esta série encontrou três vezes.
        """
        r = _rodar(self.destino, duration="12", fase1="ok", containers="0")
        # Aqui o código é 2 — erro de uso, não recusa do portão —, e a distinção
        # importa: quem chama errado precisa saber que chamou errado.
        self.assertEqual(r.returncode, 2, f"stderr: {r.stderr}")
        self.assertIn("Ausência não é zero", r.stderr)
        self.assertFalse(self._arquivo().exists())
