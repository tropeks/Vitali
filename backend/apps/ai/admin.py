from django.contrib import admin
from .models import AIPromptTemplate, AIUsageLog, TUSSAISuggestion


@admin.register(AIPromptTemplate)
class AIPromptTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'is_active', 'updated_at']
    list_filter = ['is_active']
    search_fields = ['name']


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'model', 'tokens_in', 'tokens_out', 'latency_ms', 'created_at']
    list_filter = ['event_type', 'model']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']


@admin.register(TUSSAISuggestion)
class TUSSAISuggestionAdmin(admin.ModelAdmin):
    list_display = ['tuss_code', 'description', 'rank', 'accepted', 'guide_type', 'created_at']
    list_filter = ['accepted', 'guide_type']
    search_fields = ['tuss_code', 'description', 'input_text']
    readonly_fields = ['id', 'created_at', 'feedback_at']
    ordering = ['-created_at']
