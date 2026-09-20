"""Start the API locally.

Exists because `uv run uvicorn ...` fails on this machine: Windows Application
Control blocks the `uvicorn.exe` shim with

    error: Failed to spawn: `uvicorn`
    Caused by: An Application Control policy has blocked this file. (os error 4551)

Importing uvicorn and calling it from Python spawns no blocked executable, so
this works where the console script does not.

    uv run python -m scripts.serve

Reads the same .env as the app. With no GEMINI_API_KEY the service still starts
and only /v1/search refuses.
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Furniture AI API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--reload", action="store_true", help="Reload on source changes."
    )
    arguments = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=arguments.host,
        port=arguments.port,
        reload=arguments.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
