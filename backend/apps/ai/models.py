"""
AI app models — S-030 LLM Integration Layer, S-031 TUSS Auto-Coding
"""
import uuid

from django.db import models
from django.conf import settings


class AIPromptTemplate(models.Model):
    """
    Versioned prompt templates stored in DB.
    Version is embedded in the Redis cache key — bumping version auto-invalidates cache.
    """
    name = models.CharField(max_length=100, unique=True)
    version = models.PositiveIntegerField(default=1)
    system_prompt = models.TextField()
    user_prompt_template = models.TextField(
        help_text="Use {description}, {guide_type}, {candidates} as placeholders."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', '-version']

    def __str__(self):
        return f'{self.name} v{self.version}'


class AIUsageLog(models.Model):
    """
    Append-only log of every Claude call. Used for cost tracking and analytics.
    Also logs zero-result events (model='', tokens=0) for prompt quality diagnosis.
    """
    EVENT_CHOICES = [
        ('llm_call', 'LLM Call'),
        ('zero_result', 'Zero Result (retrieval returned 0 candidates)'),
        ('validation_dropout', 'Validation Dropout (all suggestions invalid)'),
        ('degraded', 'Degraded (AI unavailable)'),
        ('cache_hit', 'Cache Hit'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prompt_template = models.ForeignKey(
        AIPromptTemplate, null=True, blank=True, on_delete=models.SET_NULL
    )
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES, default='llm_call')
    tokens_in = models.PositiveIntegerField(default=0)
    tokens_out = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    model = models.CharField(max_length=100, default='claude-haiku-4-5-20251001')
    input_text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.event_type} @ {self.created_at:%Y-%m-%d %H:%M}'


class TUSSAISuggestion(models.Model):
    """
    Tracks every TUSS AI suggestion shown to a faturista.
    Accepted/rejected signal is the sprint's primary proprietary data output.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    usage_log = models.ForeignKey(
        AIUsageLog, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='suggestions'
    )
    tuss_code = models.CharField(max_length=20, db_index=True)
    description = models.CharField(max_length=500)
    rank = models.PositiveSmallIntegerField(help_text="1 = most relevant")
    input_text = models.CharField(max_length=500)
    guide_type = models.CharField(max_length=50, blank=True)
    accepted = models.BooleanField(null=True, blank=True, help_text="None = no feedback yet")
    feedback_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['tuss_code', 'created_at']),
            models.Index(fields=['accepted', 'created_at']),
        ]

    def __str__(self):
        status = 'accepted' if self.accepted else ('rejected' if self.accepted is False else 'pending')
        return f'TUSS {self.tuss_code} rank={self.rank} [{status}]'
