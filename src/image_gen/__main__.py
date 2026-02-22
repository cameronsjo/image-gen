"""Uvicorn entrypoint — run with `python -m image_gen`."""

import uvicorn

from image_gen.app import create_app
from image_gen.config import Settings


def main() -> None:
    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
