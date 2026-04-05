from django.contrib import admin
from .models import WhatsAppContact, ConversationSession, MessageLog, ScheduledReminder


@admin.register(WhatsAppContact)
class WhatsAppContactAdmin(admin.ModelAdmin):
    list_display = ["phone", "patient", "opt_in", "opt_in_at", "opt_out_at", "created_at"]
    list_filter = ["opt_in"]
    search_fields = ["phone", "patient__full_name"]
    raw_id_fields = ["patient"]
    readonly_fields = ["opt_in_at", "opt_out_at", "created_at"]


@admin.register(ConversationSession)
class ConversationSessionAdmin(admin.ModelAdmin):
    list_display = ["contact", "state", "expires_at", "created_at"]
    list_filter = ["state"]
    search_fields = ["contact__phone"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ["contact", "direction", "message_type", "content_preview", "created_at"]
    list_filter = ["direction", "message_type"]
    search_fields = ["contact__phone", "content_preview"]
    raw_id_fields = ["contact", "appointment"]
    readonly_fields = ["created_at"]


@admin.register(ScheduledReminder)
class ScheduledReminderAdmin(admin.ModelAdmin):
    list_display = ["appointment", "reminder_type", "status", "sent_at", "created_at"]
    list_filter = ["reminder_type", "status"]
    raw_id_fields = ["appointment"]
    readonly_fields = ["created_at"]
