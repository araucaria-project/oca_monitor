import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox
from PyQt6 import QtCore, QtGui
import json,requests
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
import ephem
import time
from astropy.time import Time as czas_astro
# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

def raise_alarm(mess):
    pars = {'token':'adcte9qacd6jhmhch8dyw4e4ykuod2','user':'uacjyhka7d75k5i3gmfhdg9pc2vqyf','message':mess}
    requests.post('https://api.pushover.net/1/messages.json',data=pars)

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
        text = 'UT:\t'+ut+'\nLT:\t'+lt+'\nSIDT:\t'+str(lst)+'\nJD:\t\t'+str("{:.2f}".format(float(jd)))+'\nSUNRISE(UT):\t'+sunrise[-8:]+'\nSUN ALT:\t'+str(sun.alt)
    else:
        text = 'UT:\t'+ut+'\nLT:\t'+lt+'\nSIDT:\t'+str(lst)+'\nJD:\t\t'+str("{:.2f}".format(float(jd)))+'\nSUNSET(UT):\t'+sunset[-8:]+'\nSUN ALT:\t'+str(sun.alt)
    return text,sun.alt
        



class WidgetTvsControlroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.main_window = main_window
        self.initUI(example_parameter,subject)

    def initUI(self, text,subject):
        self.alarm_weather_kontrolka = 0
        self.weather_subject=subject
        self.layout = QVBoxLayout(self)
        self.ephem = QLabel("init")
        self.ephem.setStyleSheet("background-color : silver; color: black")
        self.ephem.setFont(QtGui.QFont('Arial', 26))

        self.zb08= QLabel("ZB08:init")
        self.zb08.setStyleSheet("background-color : silver; color: black")
        self.zb08.setFont(QtGui.QFont('Arial', 26))

        self.wk06 = QLabel("WK06:init")
        self.wk06.setStyleSheet("background-color : silver; color: black")
        self.wk06.setFont(QtGui.QFont('Arial', 26))

        self.jk15 = QLabel("JK15init")
        self.jk15.setStyleSheet("background-color : silver; color: black")
        self.jk15.setFont(QtGui.QFont('Arial', 26))

        self.energy = QLabel("Energy:init")
        self.energy.setStyleSheet("background-color : silver; color: black")
        self.energy.setFont(QtGui.QFont('Arial', 26))

        

        self.layout.addWidget(self.ephem)
        self.layout.addWidget(self.zb08)
        self.layout.addWidget(self.wk06)
        self.layout.addWidget(self.jk15)
        self.layout.addWidget(self.energy)

        # Some async operation
        self._update_ephem()
        logger.info("UI setup done")

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

        QtCore.QTimer.singleShot(1000, self._update_ephem)


    


widget_class = WidgetTvsControlroom
