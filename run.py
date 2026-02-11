import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)


def main():
    logging.info("Starting in POLLING mode")
    from bot.main import start_polling
    asyncio.run(start_polling())


if __name__ == "__main__":
    main()
