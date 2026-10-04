"""Worker entrypoint: `uv run --package sg_worker python -m sg_worker.main`."""

from sg_core.logging import configure_logging
from sg_core.settings import Environment, get_settings
from sg_worker.client import get_hatchet
from sg_worker.tasks import ALL_WORKFLOWS


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json=settings.environment is not Environment.LOCAL)
    worker = get_hatchet().worker("skill-garden-worker", workflows=ALL_WORKFLOWS)
    worker.start()


if __name__ == "__main__":
    main()
