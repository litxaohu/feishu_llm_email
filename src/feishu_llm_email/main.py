import asyncio
import logging

from .bot import FeishuLLMBot
from .config import load_settings


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


async def _run() -> None:
    settings = load_settings()
    bot = FeishuLLMBot(settings)
    await bot.run()


def main() -> None:
    setup_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
