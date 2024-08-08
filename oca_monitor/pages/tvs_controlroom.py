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
        self.ephem.setFont(QtGui.QFont('Arial', 20))

        

        

        self.label_lights = QLabel(f"LIGHTS", self)
        self.label_lights.setStyleSheet("background-color: grey; color: black")

        # Some async operation
        self._update_ephem()
        self._update_lights_status()
        QtCore.QTimer.singleShot(0, self._update_warningWindow)
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
            self.ephem.setStyleSheet("background-color : pink; color: black")

        QtCore.QTimer.singleShot(1000, self._update_ephem)


    @asyncSlot()
    async def _update_warningWindow(self):
        self.wind = '0.0'
        self.temp = '0.0'
        self.hum = '0.0'
        self.pres = '0.0'
        await create_task(self.reader_loop(), "weather reader")
        #warning = 'Wind: '+str(self.wind)+' m/s\n'+'Temperature: '+str(self.temp)+' C\n'+'Humidity: '+str(self.hum)+' %\n'+'Wind dir: '+str(self.main_window.winddir)+'\n'
        #self.label.setText(warning)
    

    async def reader_loop(self):
        msg = Messenger()

        # We want the data from the midnight of yesterday
        

        rdr = msg.get_reader(
            self.weather_subject,
            deliver_policy='last',
        )
        logger.info(f"Subscribed to {self.weather_subject}")

        sample_measurement = {
                "temperature_C": 10,
                "humidity": 50,
                "wind_dir_deg": 180,
                "wind_ms": 5,
                "wind_10min_ms": 5,
                "pressure_Pa": 101325,
                "bar_trend": 0,
                "rain_mm": 0,
                "rain_day_mm": 0,
                "indoor_temperature_C": 20,
                "indoor_humidity": 50,
        }
        async for data, meta in rdr:
            ts = dt_ensure_datetime(data['ts']).astimezone()
            hour = ts.hour + ts.minute / 60 + ts.second / 3600
            measurement = data['measurements']
            self.wind = "{:.1f}".format(measurement['wind_10min_ms'])
            self.temp = "{:.1f}".format(measurement['temperature_C'])
            self.hum = int(measurement['humidity'])
            self.pres = int(measurement['pressure_Pa'])
            self.winddir = int(measurement['wind_dir_deg'])

            self.main_window.wind = self.wind
            self.main_window.temp = self.temp
            self.main_window.hum = self.hum
            self.main_window.winddir = self.winddir
            self.main_window.skytemp = '0'

            warning = 'Wind: '+str(self.wind)+' m/s\n'+'Temperature: '+str(self.temp)+' C\n'+'Humidity: '+str(self.hum)+' %\n'+'Wind dir: '+str(self.main_window.winddir)+'\n'
            if (float(self.wind) >= 11. and float(self.wind) < 14.) or float(self.hum) > 70.:
                self.label.setStyleSheet("background-color : yellow; color: black")
                self.alarm_weather_kontrolka = 0
            elif float(self.wind) >= 14. or float(self.hum) > 75.:
                if self.alarm_weather_kontrolka == 0:
                    raise_alarm('weather alarm')
                    self.alarm_weather_kontrolka = 1
                self.label.setStyleSheet("background-color : red; color: black")
            else:
                self.label.setStyleSheet("background-color : lightgreen; color: black")
                self.alarm_weather_kontrolka = 0

            self.label.setText(warning)


widget_class = WidgetTvsControlroom
