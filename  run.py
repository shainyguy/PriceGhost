import asyncio
import logging
import sys

from config import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger(__name__)


def main():
    if config.webhook.url:
        logger.info("🌐 Starting in WEBHOOK mode (Railway)")
        from bot.main import start_webhook
        start_webhook()
    else:
        logger.info("🔄 Starting in POLLING mode (local)")
        from bot.main import start_polling
        asyncio.run(start_polling())


if __name__ == "__main__":
    main()