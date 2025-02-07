import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox, QTextEdit, QLineEdit
from PyQt6 import QtCore, QtGui
import json,requests
import asyncio
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger, single_read, get_reader

import ephem
import time
from astropy.time import Time as czas_astro
# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])


def ephemeris():
    arm=ephem.Observer()
    arm.pressure=730
    #arm.horizon = '-0.5'
    arm.lon='-70.201266'
    arm.lat='-24.598616'
    arm.elev=2800
    arm.pressure=730
    date = time.strftime('%Y%m%d',time.gmtime() )
    ut = time.strftime('%Y/%m/%d %H:%M:%S',time.gmtime() )
    t = czas_astro([ut.replace('/','-',2).replace(' ','T',1)])
    jd = str(t.jd[0])[:12]
    lt = time.strftime('%Y/%m/%d %H:%M:%S',time.localtime() )
    arm.date = ut
    sunset=str(arm.next_setting(ephem.Sun()))
    sunrise=str(arm.next_rising(ephem.Sun()))
    sun = ephem.Sun()
    moon = ephem.Moon()
    sun.compute(arm)
    moon.compute(arm)
    arm.horizon = '-18'
    
    lst = arm.sidereal_time()
    if str(sun.alt)[0] == '-':
        text = 'UT:\t'+ut+'\nSIDT:\t'+str(lst)+'\nJD:\t\t'+str("{:.2f}".format(float(jd)))+'\nSUNRISE(UT):\t'+sunrise[-8:]
    else:
        text = 'UT:\t'+ut+'\nLT:\t'+lt+'\nSIDT:\t'+str(lst)+'\nJD:\t\t'+str("{:.2f}".format(float(jd)))+'\nSUNSET(UT):\t'+sunset[-8:]
    return text,sun.alt
        



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



    def initUI(self):
        
        self.layout = QVBoxLayout(self)
        self.ephem = QLabel("init")
        self.ephem.setStyleSheet("background-color : silver; color: black")
        self.ephem.setFont(QtGui.QFont('Arial', 22))

        self.layout.addWidget(self.ephem)
        

        self._update_ephem()

    def _update_ephem(self):
        text,sunalt = ephemeris()
        sunalt = str(sunalt)
        self.ephem.setText(text)
        if float(sunalt.split(':')[0]) <0. and float(sunalt.split(':')[0])  > -17.:
            self.ephem.setStyleSheet("background-color : yellow; color: black")
        elif float(sunalt.split(':')[0])  <= -17.:
            self.ephem.setStyleSheet("background-color : lightgreen; color: black")
        else:
            self.ephem.setStyleSheet("background-color : coral; color: black")

        # obsluiga buczkow
        if self.prev_sun_alt:
            if int(sunalt.split(':')[0]) == 5 and ephem.degrees(self.prev_sun_alt) > ephem.degrees(sunalt):
                self.main_window.sound_page.play_sun_alt(True)
            elif int(sunalt.split(':')[0]) == -18 and ephem.degrees(self.prev_sun_alt) < ephem.degrees(sunalt):
                self.main_window.sound_page.play_sun_alt(True)
            elif int(sunalt.split(':')[0]) == 0:
                self.main_window.sound_page.play_sun_alt(True)
            else:
                self.main_window.sound_page.play_sun_alt(False)
        self.prev_sun_alt = sunalt

        QtCore.QTimer.singleShot(1000, self._update_ephem)


widget_class = WidgetEphem
