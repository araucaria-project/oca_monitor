"""
OCA Monitor

See settings.toml for configuration options.
"""
import logging
import asyncio
import os
import sys
import argparse
import time
from importlib import import_module
from logging.handlers import RotatingFileHandler

from PyQt6.QtWidgets import QMainWindow
from qasync import QEventLoop, QApplication
from serverish.messenger import Messenger

from oca_monitor.config import settings
from oca_monitor.main_window import MainWindow

logger = logging.getLogger('main')

async def dummytask():
    logger.info('Dummy task started')
    return
    while True:
        await asyncio.sleep(1)
        logger.info('Dummy task')

async def asyncmain(app):
    host, port = settings.nats_host, settings.nats_port

    msg = Messenger()
    _opener = await msg.open(host, port, wait=3)
    if _opener is None:
        logger.info(f'NATS Messenger connected on {host}:{port}')
    else:
        logger.warning(f'NATS Messenger not connected, will still trying to connect to nats://{host}:{port}')

    window = MainWindow()
    window.show()

    app_close_event = asyncio.Event()
    app.aboutToQuit.connect(app_close_event.set)
    await app_close_event.wait()

def main():
    # Parse command line arguments
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument('--env',
                           help='Settings environment name, overrides OCAMONITOR_ENV environment variable. '
                                'If none of them is set, default values are used')
    argparser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                           help='Logging level, overrides OCAMONITOR_LOG_LEVEL environment variable and settings.toml.')
    args = argparser.parse_args()

    # Settings environment configuration
    # Environment name is taken from command line arguments, or default value 'oca' is used
    if args.env:
        os.environ["OCAMONITOR_ENV"] = args.env  # hard override
    else:
        os.environ.setdefault("OCAMONITOR_ENV", "default")  # effective only if env variable is not set


    # Logging configuration
    # Logging level is taken from command line arguments, or environment variable, or settings.toml
    if args.log_level:
        loglevel = args.log_level  # hard override
    else:
        loglevel = settings.log_level
    log_file_name = f'ocam.log'
    log_path = '~/.oca'
    log_file = os.path.expanduser(os.path.join(log_path, log_file_name))
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(filename=log_file, maxBytes=1000000, backupCount=5)
        file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
        logging.Formatter.converter = time.gmtime
        logging.getLogger().addHandler(file_handler)
        logger.info(f'Log file added at {log_file}')
    except OSError:
        logger.warning(f'Can not create loging folder.')

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

    loop.run_until_complete(asyncmain(app))
