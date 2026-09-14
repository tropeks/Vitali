# Aditiva: os dois campos que faltavam em TISSGuideItem para emitir
# <procedimentosExecutados> (ct_procedimentoExecutadoInt) na guia de resumo de
# internação. Sem backfill, de propósito — ver o comentário dos campos em
# apps/billing/models.py:
#
#   * execution_date fica NULL nas linhas antigas porque nenhuma fonte honesta
#     diz em que dia elas foram executadas; a emissão do XML falha alto nelas em
#     vez de carimbar uma data;
#   * reduction_increase_factor nasce 1.00 (o NEUTRO do fator), o que mantém
#     total_value idêntico em todas as linhas já gravadas.
import decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("billing", "0035_guide_tipo_faturamento"),
    ]

    operations = [
        migrations.AddField(
            model_name="tissguideitem",
            name="execution_date",
            field=models.DateField(
                blank=True,
                help_text=(
                    "dataExecucao (ct_procedimentoExecutadoInt) — dia em que ESTE item foi "
                    "executado, na data local da clínica. Vazio só em linhas anteriores à "
                    "Onda 4; sem ela a guia de resumo de internação não gera XML."
                ),
                null=True,
                verbose_name="Data de execução",
            ),
        ),
        migrations.AddField(
            model_name="tissguideitem",
            name="reduction_increase_factor",
            field=models.DecimalField(
                decimal_places=2,
                default=decimal.Decimal("1.00"),
                help_text=(
                    "reducaoAcrescimo (ct_procedimentoExecutadoInt) / fatorReducaoAcrescimo "
                    "(ct_procedimentoExecutado) — multiplicador aplicado ao valor da linha. "
                    "1.00 = sem redução nem acréscimo; 0.50 = metade; 1.30 = 30% a mais. "
                    "Faixa do XSD: 0,00 a 9,99."
                ),
                max_digits=3,
                verbose_name="Fator de redução/acréscimo (TISS)",
            ),
        ),
    ]
