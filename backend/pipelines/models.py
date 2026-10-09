from django.db import models
from django.utils.crypto import get_random_string


class PipelineManager(models.Manager):
    def get_by_natural_key(self, slug):
        return self.get(slug=slug)


class Pipeline(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=255)
    config_schema = models.JSONField(blank=True)
    description = models.TextField()

    created = models.DateTimeField(auto_now_add=True)
    edited = models.DateTimeField(auto_now=True)
    active = models.BooleanField(default=True)

    objects = PipelineManager()

    def __repr__(self):
        return f"{self.name} ({self.slug})"

    def __str__(self):
        return self.__repr__()

    def natural_key(self):
        return (self.slug,)


def _generate_api_key():
    return "ioos_br_" + get_random_string(22)


class PipelineApiKey(models.Model):
    """API keys for programmatic access to pipelines"""

    id = models.AutoField(primary_key=True)
    user = models.ForeignKey("buoy_retriever_account.User", on_delete=models.PROTECT)
    name = models.CharField(max_length=255)
    key_value = models.CharField(max_length=255, unique=True, default=_generate_api_key)

    created = models.DateTimeField(auto_now_add=True)
    edited = models.DateTimeField(auto_now=True)

    is_active = models.BooleanField(default=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.is_active and not self.deactivated_at:
            from django.utils import timezone

            self.deactivated_at = timezone.now()
        super().save(*args, **kwargs)
