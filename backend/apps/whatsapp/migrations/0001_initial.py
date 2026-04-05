import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("emr", "0007_appointment_satisfaction_rating"),
    ]

    operations = [
        migrations.CreateModel(
            name="WhatsAppContact",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("phone", models.CharField(db_index=True, max_length=20, unique=True)),
                ("patient", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="whatsapp_contacts",
                    to="emr.patient",
                )),
                ("opt_in", models.BooleanField(default=False)),
                ("opt_in_at", models.DateTimeField(blank=True, null=True)),
                ("opt_out_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "WhatsApp Contact", "verbose_name_plural": "WhatsApp Contacts", "ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="ConversationSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contact", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="session",
                    to="whatsapp.whatsappcontact",
                )),
                ("state", models.CharField(
                    choices=[
                        ("IDLE", "Idle"),
                        ("PENDING_OPTIN", "Pending opt-in"),
                        ("SELECTING_SELF_OR_OTHER", "Selecting self or other"),
                        ("CAPTURING_NAME", "Capturing other person name"),
                        ("CAPTURING_CPF", "Capturing other person CPF"),
                        ("SELECTING_SPECIALTY", "Selecting specialty"),
                        ("SELECTING_PROFESSIONAL", "Selecting professional"),
                        ("SELECTING_DATE", "Selecting date"),
                        ("SELECTING_TIME", "Selecting time"),
                        ("CONFIRMING", "Confirming booking"),
                        ("CONFIRMED", "Booking confirmed"),
                        ("FALLBACK_HUMAN", "Fallback to human"),
                        ("OPTED_OUT", "Opted out"),
                    ],
                    default="IDLE",
                    max_length=30,
                )),
                ("context", models.JSONField(default=dict)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "Conversation Session"},
        ),
        migrations.AddIndex(
            model_name="conversationsession",
            index=models.Index(fields=["expires_at"], name="whatsapp_co_expires_idx"),
        ),
        migrations.CreateModel(
            name="MessageLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("contact", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="message_logs",
                    to="whatsapp.whatsappcontact",
                )),
                ("direction", models.CharField(
                    choices=[("inbound", "Inbound"), ("outbound", "Outbound")],
                    max_length=10,
                )),
                ("content_preview", models.CharField(max_length=200)),
                ("message_type", models.CharField(
                    choices=[
                        ("text", "Text"),
                        ("button_reply", "Button reply"),
                        ("template", "Template"),
                        ("list_reply", "List reply"),
                    ],
                    default="text",
                    max_length=20,
                )),
                ("appointment", models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="message_logs",
                    to="emr.appointment",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={"verbose_name": "Message Log", "verbose_name_plural": "Message Logs", "ordering": ["-created_at"]},
        ),
        migrations.AddIndex(
            model_name="messagelog",
            index=models.Index(fields=["contact", "created_at"], name="whatsapp_ml_contact_ts_idx"),
        ),
        migrations.CreateModel(
            name="ScheduledReminder",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("appointment", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="scheduled_reminders",
                    to="emr.appointment",
                )),
                ("reminder_type", models.CharField(
                    choices=[
                        ("24h", "24h reminder"),
                        ("2h", "2h reminder"),
                        ("satisfaction", "Post-visit satisfaction survey"),
                    ],
                    max_length=20,
                )),
                ("status", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("sent", "Sent"),
                        ("failed", "Failed"),
                        ("responded", "Responded"),
                        ("skipped", "Skipped"),
                    ],
                    db_index=True,
                    default="pending",
                    max_length=20,
                )),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"verbose_name": "Scheduled Reminder", "verbose_name_plural": "Scheduled Reminders"},
        ),
        migrations.AddConstraint(
            model_name="scheduledreminder",
            constraint=models.UniqueConstraint(
                fields=["appointment", "reminder_type"],
                name="unique_reminder_per_appointment_type",
            ),
        ),
        migrations.AddIndex(
            model_name="scheduledreminder",
            index=models.Index(fields=["status", "created_at"], name="whatsapp_sr_status_idx"),
        ),
    ]
