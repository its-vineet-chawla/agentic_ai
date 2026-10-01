from agentic_ai.config import Settings
from agentic_ai.logging_config import configure_logging


def main() -> None:
    settings = Settings()
    configure_logging(settings)
    print("Hello, world!")