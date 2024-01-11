#!/usr/bin/env python3

"""This is the old-fashion startup script for OCA monitor

This script should not be needed, because `poetry` generates a startup scripts, but
is here for those who prefer this way of starting the application.

Note, that poetry scripts take care of the virtual environment, so it's better to use them.

Anyway, do not add any code here, all initialization, configuration etc. should be done in `oca_monitor/main.py`.
"""

from oca_monitor.main import main

if __name__ == '__main__':
    main()