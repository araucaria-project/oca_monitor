"""
OCA Monitor

See settings.toml for configuration options.
"""
import logging
import asyncio
import os
import sys
import argparse
from importlib import import_module

from qasync import QEventLoop, QApplication
from serverish.messenger import Messenger

from oca_monitor.config import settings
from oca_monitor.main_window import MainWindow

logger = logging.getLogger('main')


async def asyncmain(loop):
    host, port = settings.nats_host, settings.nats_port

    msg = Messenger()
    _opener = await msg.open(host, port, wait=3)
    if _opener is None:
        logger.info(f'NATS Messenger connected on {host}:{port}')
    else:
        logger.warning(f'NATS Messenger not connected, will still trying to connect to nats://{host}:{port}')

    window = MainWindow()
    window.show()

    loop.run_forever()

def main():
    # Parse command line arguments
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument('--env',
                           help='Settings environment name, overrides OCAMONITOR_ENV environment variable. '
                                'If none of them is set, default value "dev" is used')
    argparser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                           help='Logging level, overrides OCAMONITOR_LOG_LEVEL environment variable and settings.toml.')
    args = argparser.parse_args()

    # Settings environment configuration
    # Environment name is taken from command line arguments, or default value 'oca' is used
    if args.env:
        os.environ["OCAMONITOR_ENV"] = args.env  # hard override
    else:
        os.environ.setdefault("OCAMONITOR_ENV", "dev")  # effective only if env variable is not set


    # Logging configuration
    # Logging level is taken from command line arguments, or environment variable, or settings.toml
    if args.log_level:
        loglevel = args.log_level  # hard override
    else:
        loglevel = settings.log_level
    logging.basicConfig(level=loglevel,
                        format='%(asctime)s [%(levelname)s] [%(name)s] %(message)s')
    logger.info(f'OCA Monitor logging level: {loglevel}')
    logger.info(f'OCA Monitor configuration environment: {settings.env_for_dynaconf}')

    # Standard Qt Application
    app = QApplication(sys.argv)

    # Style sheet
    try:
        style_module = import_module(f'oca_monitor.styles.{settings.style}')
        app.setStyleSheet(style_module.style_sheet)
    except ImportError:
        logger.warning(f'Cannot import style sheet from {settings.style_sheet}')
    except (AttributeError, LookupError):
        pass

    # Event loop from qasync (make Qt + asyncio work together)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    asyncio.run(asyncmain(loop))
