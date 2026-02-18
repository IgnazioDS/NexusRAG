from __future__ import annotations

import asyncio

from nexusrag.core.logging import configure_logging
from nexusrag.services.operability.worker import run_background_evaluator_loop


async def _main() -> None:
    # Boot a dedicated evaluator loop process so alerts/incidents continue without request traffic.
    configure_logging()
    await run_background_evaluator_loop()


if __name__ == "__main__":
    asyncio.run(_main())
