import logging

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox, QTextEdit, QLineEdit
from PyQt6 import QtCore, QtGui
import json,requests
import asyncio
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger, single_read, get_reader

import datetime
import time
from astropy.time import Time as czas_astro

from oca_monitor.utils.ephem_ocm import (
    moon_state, next_sun_alt_event, sidereal_time_str, sun_alt_deg,
)

# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])


def ephemeris():
    now = datetime.datetime.now(datetime.timezone.utc)
    ut = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime())
    lt = time.strftime('%Y/%m/%d %H:%M:%S', time.localtime())
    jd = czas_astro(now).jd
    sun_alt = sun_alt_deg(now)
    ms = moon_state(now)
    moon_pct = int(ms['phase'] * 100)
    moon_alt_int = int(round(ms['alt_deg']))
    sidt = sidereal_time_str(now)
    if sun_alt < 0:
        rise = next_sun_alt_event(now, 0.0, 'rising')
        rise_s = rise.strftime('%H:%M:%S') if rise else '—'
        text = (f'UT:\t{ut}\nSIDT:\t\t{sidt}\nJD:\t\t{jd:.2f}'
                f'\nSUNRISE(UT):\t{rise_s}\nMOON PHASE[%]:\t{moon_pct}'
                f'\nMOON ALT:\t\t{moon_alt_int}')
    else:
        sset = next_sun_alt_event(now, 0.0, 'setting')
        set_s = sset.strftime('%H:%M:%S') if sset else '—'
        text = (f'UT:\t{ut}\nLT:\t\t{lt}\nSIDT:\t{sidt}\nJD:\t\t{jd:.2f}'
                f'\nSUNSET(UT):\t{set_s}\nMOON PHASE[%]:\t{moon_pct}'
                f'\nMOON ALT:\t\t{moon_alt_int}')
    return text, sun_alt
        



class WidgetEphem(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.main_window = main_window

        self.initUI()
        logger.info(f"WidgetEphem init setup done")



    def initUI(self):
        
        self.layout = QVBoxLayout(self)
        self.ephem = QLabel("init")
        self.ephem.setStyleSheet("background-color : silver; color: black")
        self.ephem.setFont(QtGui.QFont('Arial', 22))

        self.layout.addWidget(self.ephem)

        QTimer.singleShot(0, self.async_init)
        # self._update_ephem()

    async def a_update_ephem(self):
        while True:
            text, sunalt = ephemeris()
            sunalt = str(sunalt)
            self.ephem.setText(text)
            if float(sunalt.split(':')[0]) < 0. and float(sunalt.split(':')[0]) > -17.:
                self.ephem.setStyleSheet("background-color : yellow; color: black")
            elif float(sunalt.split(':')[0]) <= -17.:
                self.ephem.setStyleSheet("background-color : lightgreen; color: black")
            else:
                self.ephem.setStyleSheet("background-color : coral; color: black")
            await asyncio.sleep(1)

    # def _update_ephem(self):
    #     text,sunalt = ephemeris()
    #     sunalt = str(sunalt)
    #     self.ephem.setText(text)
    #     if float(sunalt.split(':')[0]) <0. and float(sunalt.split(':')[0])  > -17.:
    #         self.ephem.setStyleSheet("background-color : yellow; color: black")
    #     elif float(sunalt.split(':')[0])  <= -17.:
    #         self.ephem.setStyleSheet("background-color : lightgreen; color: black")
    #     else:
    #         self.ephem.setStyleSheet("background-color : coral; color: black")
    #
    #
    #
    #     QtCore.QTimer.singleShot(1000, self._update_ephem)

    @asyncSlot()
    async def async_init(self):
        await create_task(self.a_update_ephem(), f'ephemeris_update')


widget_class = WidgetEphem
