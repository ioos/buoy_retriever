from django.apps import AppConfig


class BuoyRetrieverConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "buoy_retriever"
    label = "buoy_retriever"

    def ready(self):
        # Initialize signals
        import buoy_retriever.signals # noqa
