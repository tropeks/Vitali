"""
Core signals — e.g., auto-create FeatureFlags when a Subscription is created.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="core.Subscription")
def create_feature_flags_on_subscription(sender, instance, created, **kwargs):
    """Automatically enable FeatureFlags for the modules in a new subscription."""
    if not created:
        return

    from apps.core.models import FeatureFlag

    for module_key in instance.active_modules:
        FeatureFlag.objects.get_or_create(
            tenant=instance.tenant,
            module_key=module_key,
            defaults={"is_enabled": True},
        )
