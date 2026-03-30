from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("SYNC115PAN_HOST", "127.0.0.1")
    port = int(os.getenv("SYNC115PAN_PORT", "8000"))
    uvicorn.run("sync115pan.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
