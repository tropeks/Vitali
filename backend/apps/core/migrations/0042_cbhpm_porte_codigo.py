"""O porte da CBHPM vira código, e a valoração muda de campo (ordem 013).

``CBHPMItem.porte`` nasceu ``DecimalField`` rotulado "quantidade de CH". Na CBHPM
publicada pela AMB o porte é **classe hierárquica** (``3B``, ``13C``) e, em toda a
Medicina Laboratorial, **fração de classe** (``0,01 de 1A``). Das 4.883 linhas da
edição 2022 rev. ago/2023, **zero** têm porte numérico.

**O dado existente não se perde e a valoração não muda de resultado.** O decimal que
estava em ``porte`` sempre significou a quantidade de CH — é literalmente o que o
``help_text`` dizia —, então ele é copiado para o campo novo ``porte_ch``, que passa a
ser o multiplicador de ``valor()``. ``porte`` fica vazio: a classe publicada é
informação que o banco nunca teve, e inventá-la a partir do número seria fabricar
dado clínico-contratual (INTENT §Limites).

A reversão desfaz o mesmo caminho, sem inventar: ``porte`` volta a receber o decimal
que veio de ``porte_ch``.
"""

from django.db import migrations, models


def porte_para_porte_ch(apps, schema_editor):
    """Move o decimal antigo para o campo de valoração, preservando honorários."""
    CBHPMItem = apps.get_model("core", "CBHPMItem")
    for item in CBHPMItem.objects.exclude(porte_antigo=None).iterator():
        item.porte_ch = item.porte_antigo
        item.save(update_fields=["porte_ch"])


def porte_ch_para_porte(apps, schema_editor):
    CBHPMItem = apps.get_model("core", "CBHPMItem")
    for item in CBHPMItem.objects.iterator():
        item.porte_antigo = item.porte_ch
        item.save(update_fields=["porte_antigo"])


class Migration(migrations.Migration):
    dependencies = [("core", "0041_role_tenant")]

    operations = [
        # 1. O decimal antigo é renomeado, não apagado — assim o dado atravessa a
        #    migration sob os olhos de quem lê o diff, em vez de sumir e reaparecer.
        migrations.RenameField(model_name="cbhpmitem", old_name="porte", new_name="porte_antigo"),
        # 2. Entra o campo de valoração contratada.
        migrations.AddField(
            model_name="cbhpmitem",
            name="porte_ch",
            field=models.DecimalField(
                decimal_places=4,
                default=0,
                help_text=(
                    "Quantidade de CH correspondente ao porte, vinda da tabela de "
                    "valoração contratada. Zero = sem valoração — e aí valor() é zero."
                ),
                max_digits=10,
                verbose_name="Porte em CH (quantidade)",
            ),
        ),
        # 3. O dado se muda.
        migrations.RunPython(porte_para_porte_ch, porte_ch_para_porte),
        # 4. E só então o decimal antigo sai.
        migrations.RemoveField(model_name="cbhpmitem", name="porte_antigo"),
        # 5. Entra o porte-classe.
        migrations.AddField(
            model_name="cbhpmitem",
            name="porte",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text=(
                    "Classe de porte como publicada na CBHPM (ex.: '3B', '13C', "
                    "'0,01 de 1A'). Vazio = não informado. NÃO é valor monetário."
                ),
                max_length=32,
                verbose_name="Porte (classe CBHPM)",
            ),
        ),
    ]
