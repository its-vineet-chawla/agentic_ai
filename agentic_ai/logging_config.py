import logging

from agentic_ai.config import Settings


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.app_log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )