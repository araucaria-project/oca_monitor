import asyncio
import logging
from typing import Any

from nats.errors import TimeoutError as NatsTimeoutError
from PyQt6.QtWidgets import QDialog,QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox
from PyQt6 import QtCore, QtGui
from PyQt6.QtGui import QPixmap
import json, requests
import aiohttp
import oca_monitor.config as config
from qasync import asyncSlot
from PyQt6.QtCore import QTimer
from serverish.base.task_manager import create_task_sync, create_task
import ephem
import time
from oca_monitor.image_display import ImageDisplay


# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

def ephemeris():
    arm=ephem.Observer()
    arm.pressure=730
    arm.lon='-70.201266'
    arm.lat='-24.598616'
    arm.elev=2800
    arm.pressure=730
    #lt = time.strftime('%H:%M:%S %Y/%m/%d',time.localtime() )
    lt = time.strftime('%H:%M:%S',time.localtime() )
    sun = ephem.Sun()
    sun.compute(arm)
    #return str(lt).replace(' ','\n\n',1),str(sun.alt).split(':')[0]
    return str(lt),str(sun.alt).split(':')[0]


class WaterPump:
    def __init__(self, ip: str, name: str = 'hot_water'):
        self.name = name
        self.timeout: float = 2
        self.ip = ip
        self.button = QCheckBox()
        self.button.setStyleSheet("QCheckBox::indicator{width: 170px; height:170px;} QCheckBox::indicator:checked {image: url(./Icons/hot_water_on.png)} QCheckBox::indicator:unchecked {image: url(./Icons/hot_water_off.png)}")
        self.button.setChecked(False)

    @property
    def url(self) -> str:
        return f'http://{self.ip}/state'

    @asyncSlot()
    async def connect(self):
        self.button.stateChanged.connect(self.button_pressed)

    @asyncSlot()
    async def button_pressed(self) -> int:
        # Water pump signal need to be pressed for 2 seconds to get effect
        await self.change_state()
        self.button.setChecked(True)
        await asyncio.sleep(2)
        await self.change_state()
        return 0

    @asyncSlot()
    async def change_state(self):

        if self.button.isChecked():
            value = 1
        else:
            value = 0
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.timeout)) as session:
                await session.post(
                    self.url,
                    json={"relays": [{"relay": 0, "state": value}]}
                )
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.error(f'Hot water pump can not be connected')


class TouchButtonsWBedroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 allsky_dir='/data/misc/allsky/',
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 temp_subject='telemetry.conditions.bedroom-west-tsensor',
                 room = '',
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.main_window = main_window
        self.weather_subject = subject
        self.temp_subject = temp_subject
        self.room = room
        self.freq = 2000
        self.counter = 0
        self.dir = allsky_dir
        self.water_pump = None
        self.wind: str | int | float = '0.0'
        self.temp: str | int | float = '0.0'
        self.hum: str | int | float = '0.0'
        self.pres: str | int | float = '0.0'
        self.lock: asyncio.Lock = asyncio.Lock()
        self.initUI(example_parameter,subject)

    def initUI(self, text,subject):
        
        self.layout = QHBoxLayout(self)
        self.vbox_left = QVBoxLayout()
        self.vbox_center = QVBoxLayout()
        self.vbox_right = QVBoxLayout()
        
        self.label_ephem = QLabel("ephem")
        self.label_ephem.setStyleSheet("background-color : #2b2b2b; color: white; font-weight: bold")
        self.label_ephem.setFont(QtGui.QFont('Arial', 52))

        self.vbox_left.addWidget(self.label_ephem)


        self.label_allsky = QLabel()
        self.label_allsky.resize(300,300)
        self.vbox_center.addWidget(self.label_allsky)

        self.label_temp = QLabel("temp")
        self.label_temp.setStyleSheet("background-color : #2b2b2b; color: white; font-weight: bold")
        self.label_temp.setFont(QtGui.QFont('Arial', 52))

        self.vbox_left.addWidget(self.label_temp)

        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 270px; height:270px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.clicked.connect(self.send_alarm)
        self.b_alarm.setChecked(False)

        self.vbox_right.addWidget(self.b_alarm)

        self.label_weather = QLabel("weather")
        self.label_weather.setStyleSheet("background-color : silver; color: black")
        self.label_weather.setFont(QtGui.QFont('Arial', 34))

        self.vbox_right.addWidget(self.label_weather)

        self.water_pump = WaterPump(ip=config.bbox_bedroom_west['hot_water'])
        self.vbox_center.addWidget(self.water_pump.button)

        self.layout.addLayout(self.vbox_left)
        self.layout.addLayout(self.vbox_center)
        self.layout.addLayout(self.vbox_right)
        
        self._update_weather()
        self._update_ephem()
        self._update_temp()
        # self._update_allsky()
        QTimer.singleShot(0, self.async_init)
        logger.info("UI setup done")

    @staticmethod
    async def image_instance(image_path: str) -> Any:
        image_instance = QPixmap(image_path)
        if image_instance.isNull():
            return None
        else:
            return QPixmap(image_path)

    async def image_display(self, object_to_display: QPixmap):
        self.label_allsky.setPixmap(object_to_display.scaled(300, 300, QtCore.Qt.AspectRatioMode.KeepAspectRatio))

    @asyncSlot()
    async def async_init(self):
        await self.water_pump.connect()
        logger.info('Starting allsky display.')
        display = ImageDisplay(
            name='allsky', images_dir=self.dir, image_display_clb=self.image_display,
            image_instance_clb=self.image_instance, images_prefix='lastimage',
            image_cascade_sec=0.75, image_pause_sec=1.25, refresh_list_sec=10, mode='update_files',
            sort_reverse=True
        )
        await display.display_init()

    # @asyncSlot()
    # async def water_button_pressed(self,wylacz=False):
    #     if wylacz:
    #         self.water_pump.button.setChecked(False)
    #     await self.changeWaterState()
    #     if self.water_pump.button.isChecked():
    #         #przycisk musi byc wlaczony przez okolo 2 sekundy zeby pompa sie uruchomila
    #
    #         QtCore.QTimer.singleShot(2000, lambda: self.water_button_pressed(wylacz=True))
    #
    # async def changeWaterState(self):
    #     self.water_pump.changeState()

    def send_alarm(self):
        print(self.b_alarm.isChecked())
        if self.b_alarm.isChecked():
            self.d = QDialog()
            layout = QVBoxLayout()
            l1 = QHBoxLayout()
            self.d.setWindowTitle("ALARM")
            self.d.button_silent_test = QPushButton()
            self.d.button_silent_test.setText('TEST')
            self.d.button_silent_test.clicked.connect(lambda: self.raise_alarm('OCM: TEST,',wyj=0))
            self.d.button_silent_test.setStyleSheet('QPushButton {background-color: white; border:  grey; font: bold;font-size: 32px; color: black;height: 160px;width: 220px}')

            self.d.button_siren = QPushButton()
            self.d.button_siren.setText('SIREN')
            self.d.button_siren.clicked.connect(lambda: self.raise_alarm('',wyj=1))
            self.d.button_siren.setStyleSheet('QPushButton {background-color: yellow; border:  grey; font: bold;font-size: 34px;color: black;height: 160px;width: 220px}')

            self.d.button_sirenstop = QPushButton()
            self.d.button_sirenstop.setText('SIREN STOP')
            self.d.button_sirenstop.clicked.connect(lambda: self.raise_alarm('',wyj=0))
            self.d.button_sirenstop.setStyleSheet('QPushButton {background-color: orange; border:  grey; font: bold;font-size: 34px;color: black;height: 160px;width: 220px}')
            
            self.d.button_alarm = QPushButton()
            self.d.button_alarm.setText('REAL ALARM')
            self.d.button_alarm.clicked.connect(lambda: self.raise_alarm('OCM: HELP US,',wyj=1))
            self.d.button_alarm.setStyleSheet('QPushButton {background-color: red; border:  grey; font: bold;font-size: 34px;color: black;height: 160px;width: 220px}')

            self.d.button_close = QPushButton()
            self.d.button_close.setText('EXIT')
            self.d.button_close.clicked.connect(self.d_close_clicked)
            self.d.button_close.setStyleSheet('QPushButton {background-color: grey; border:  grey; font: bold;font-size: 34px;color: black;height: 100px;width: 400px}')


            l1.addWidget(self.d.button_silent_test)
            l1.addWidget(self.d.button_siren)
            l1.addWidget(self.d.button_sirenstop)
            l1.addWidget(self.d.button_alarm)

            layout.addLayout(l1)
            layout.addWidget(self.d.button_close)


            self.d.setLayout(layout)
            self.d.exec()
            
            #self.d.setGeometry(500,300,1400,500)

        return 1

    def d_close_clicked(self):
        self.d.close()
        self.b_alarm.setChecked(False)
        print('status',self.b_alarm.isChecked())
        self.send_alarm()

    @asyncSlot()
    async def raise_alarm(self,mess,wyj=0):
        if len(mess) > 0:
            for name,po_data in config.pushover.items():
            
                user = po_data[0]
                token = po_data[1]
                await self.push(name,user,token,mess)
        
            self.c = QDialog()
            label = QLabel()
            label.setText('ALARM SENT')
            label.setStyleSheet("QLabel{font-size: 40pt;background-color: white; color:red}")
            button = QPushButton('OK')
            button.clicked.connect(self.c_close_clicked)
            layout = QVBoxLayout()
            layout.addWidget(label)
            layout.addWidget(button)
            self.c.setLayout(layout)
            self.c.exec()

        await self.siren(wyj)
        self.d_close_clicked()

    async def push(self, name,user,token,mess):
        pars = {'token':token,'user':user,'message':mess+name+'!'}
        try:
            requests.post('https://api.pushover.net/1/messages.json',data=pars)
        except:
            pass

    def c_close_clicked(self):
        self.c.close()

    async def siren(self,wyj):
        for siren,ip in config.bbox_sirens.items():
            requests.post('http://'+ip+'/state',json={"relays":[{"relay":0,"state":wyj}]})

    def _update_ephem(self):
        lt, sunalt = ephemeris()
        sunalt = str(sunalt)
        text = str(lt)+'\n\nSUN: ' + sunalt
        self.label_ephem.setText(text)
        QtCore.QTimer.singleShot(1000, self._update_ephem)

    @asyncSlot()
    async def _update_weather(self):
        await create_task(self.reader_loop_2(), "nats_weather_reader")

    async def reader_loop_2_clb(self, data, meta):
        try:
            measurement = data['measurements']
            wind = "{:.1f}".format(measurement['wind_10min_ms'])
            temp = "{:.1f}".format(measurement['temperature_C'])
            hum = int(measurement['humidity'])
            pres = int(measurement['pressure_Pa'])
            warning = 'Wind:\t' + str(wind) + ' m/s\n' + 'Temp:\t' + str(
                temp) + ' C\n' + 'Hum:\t' + str(hum) + ' %\n' + 'Press:\t' + str(pres) + ' hPa'
            if (11. <= float(wind) < 14.) or float(hum) > 70:
                self.label_weather.setStyleSheet("background-color : yellow; color: black")
            elif float(wind) >= 14. or float(hum) > 75. or float(temp) < 0.:
                self.label_weather.setStyleSheet("background-color : coral; color: black")
            else:
                self.label_weather.setStyleSheet("background-color : lightgreen; color: black")
            self.label_weather.setText(warning)
        except (ValueError, TypeError, LookupError):
            pass
        return True

    async def reader_loop_2(self):

        await self.main_window.run_reader(
            clb=self.reader_loop_2_clb,
            subject=self.weather_subject,
            deliver_policy='last'
        )

    @asyncSlot()
    async def _update_temp(self):

        await create_task(self.reader_loop_3(), "nats_temp_reader")

    async def reader_loop_3_clb(self, data, meta):
        try:
            mes = data["measurements"]
            temp = "{:.1f}".format(mes['temperature'])
            self.label_temp.setText(str(temp) + ' C')
        except (ValueError, TypeError, LookupError):
            pass
        return True

    async def reader_loop_3(self):

        await self.main_window.run_reader(
            clb=self.reader_loop_3_clb,
            subject=self.temp_subject,
            deliver_policy='last'
        )


widget_class = TouchButtonsWBedroom
