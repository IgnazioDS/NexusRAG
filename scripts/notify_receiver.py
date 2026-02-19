from __future__ import annotations

import uvicorn

from nexusrag.apps.notify_receiver import create_app, load_receiver_settings


def main() -> None:
    # Run the reference receiver with env-driven settings for compose and local contract validation.
    settings = load_receiver_settings()
    app = create_app(settings=settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()

