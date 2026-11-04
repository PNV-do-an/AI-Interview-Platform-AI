"""Khởi động AI service: .venv/Scripts/python run_ai_server.py"""
from __future__ import annotations

import logging

import uvicorn
from dotenv import load_dotenv

from app.config import Settings
from app.main import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> None:
    load_dotenv()
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.listen_host, port=settings.listen_port)


if __name__ == "__main__":
    main()
