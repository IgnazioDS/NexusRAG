from __future__ import annotations

import asyncio

from nexusrag.core.logging import configure_logging
from nexusrag.services.operability.worker import run_notification_delivery_loop


async def _main() -> None:
    # Boot a dedicated delivery loop so notification retries and dedupe run independently from API handlers.
    configure_logging()
    await run_notification_delivery_loop()


if __name__ == "__main__":
    asyncio.run(_main())
