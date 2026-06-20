#!/usr/bin/env python3
"""Launch the Aegis web app.

Examples
--------
    python run.py                 # auto-detect hardware, fall back to mock
    AEGIS_MOCK=1 python run.py     # force full mock mode (no hardware needed)
    AEGIS_PORT=9000 python run.py  # serve on a different port
"""

import uvicorn

from aegis.config import load_config


def main() -> None:
    config = load_config()
    uvicorn.run("aegis.app:app", host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
