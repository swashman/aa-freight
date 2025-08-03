from django.apps import AppConfig

from . import __version__


class FreightConfig(AppConfig):
    name = "freight"
    label = "freight"
    verbose_name = f"Freight v{__version__}"
