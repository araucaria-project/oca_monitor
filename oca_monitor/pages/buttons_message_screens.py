import logging
import os
import subprocess
import time
import json,requests
import oca_monitor.config as config
from PyQt6.QtWidgets import  QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox, QTextEdit
from PyQt6.QtCore import QTimer
from PyQt6 import QtCore, QtGui
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import get_reader


logger = logging.getLogger(__name__.rsplit('.')[-1])


class light_point():
    def __init__(self,name,ip,slider):
        self.name = name
        self.ip = ip
        
        self.slider= slider
        self.slider.setGeometry(100, 100, 100, 100)
        self.slider.setNotchesVisible(True)
        self.slider.valueChanged.connect(self.changeLight)

    def changeLight(self):
        try:
            if self.is_active:
                new_value = int(self.slider.value()*255/100)
                print(new_value)
                if new_value > 255:
                    new_value = 255

                val = str(hex(int(new_value))).replace('0x','',1)
                if len(val) == 1:
                    val = '0'+val
                
                self.req(val)
        except:
            pass

    

    def req(self,val):
        try:
            requests.post('http://'+self.ip+'/api/rgbw/set',json={"rgbw":{"desiredColor":val}})
        except:
            pass

    def status(self):
        try:
        #if True:
            req = requests.get('http://'+self.ip+'/api/rgbw/state',timeout=0.5)
            
            if int(req.status_code) != 200:
                self.is_active = False
            else:
                self.is_active = True 
                self.curr_value = int(req.json()["rgbw"]["desiredColor"],16)
                self.slider.setValue(int(self.curr_value*100/255))
        except:
            self.is_active = False

class ButtonsMessageKitchenWidget(QWidget):
    def __init__(self, main_window, subject='telemetry.weather.davis', vertical_screen = False, light='', **kwargs):
        super().__init__()
        self.parent = main_window
        self.subject = subject
        self.vertical = bool(vertical_screen)
        self.light = light
        self.initUI()
        self.parent.sound_page = self
        self.one_sun_sound = True
        self.one_weather_warning = True
        self.one_weather_stop = True
        QTimer.singleShot(0, self.async_init)
        #self.script_location = os.path.dirname(os.path.abspath(__file__))

    @asyncSlot()
    async def async_init(self):

        for tel in self.parent.telescope_names:
            await create_task(self.toi_message_reader(tel), "message_reader")


    def initUI(self,):
        self.layout = QHBoxLayout(self)
        self.info_e = QTextEdit()
        self.swiatlo = light_point(self.light,config.bbox_led_control_main[self.light],QDial())
            

        self.layout.addWidget(self.swiatlo.slider,1)
        
        self.layout.addWidget(self.info_e,2)
        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.stateChanged.connect(self.send_alarm)
        self.layout.addWidget(self.b_alarm,1)
        self._update_lights_status()
        # Some async operation
        logger.info("UI setup done")
        

    def _update_lights_status(self):
        self.swiatlo.status()

        QtCore.QTimer.singleShot(30000, self._update_lights_status)

    def send_alarm(self):
        if self.b_alarm.isChecked:
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


    @asyncSlot()
    async def raise_alarm(self,mess,wyj=0):
        if len(mess) > 0:
            for name,po_data in config.pushover.items():
            
                user = po_data[0]
                token = po_data[1]
                await self.push(name,user,token,mess)
        

        await self.siren(wyj)
        if self.b_alarm.isChecked():
            QtCore.QTimer.singleShot(2000, self.siren(mes='',wyj=0))
        self.d_close_clicked()
           

    async def push(self, name,user,token,mess):
        pars = {'token':token,'user':user,'message':mess+name+'!'}
        try:
            requests.post('https://api.pushover.net/1/messages.json',data=pars)
            self.c = QDialog()
            label = QLabel()
            label.setText('Alarm sent')
            button = QPushButton('OK')
            button.clicked.connect(self.c_close_clicked)
            layout = QHBoxLayout()
            layout.addWidget(label)
            layout.addWidget(button)
            self.c.exec()
        except:
            pass

    def c_close_clicked(self):
        self.c.close()

    async def siren(self,wyj):
        for siren,ip in config.bbox_sirens.items():
            requests.post('http://'+ip+'/state',json={"relays":[{"relay":0,"state":wyj}]})

    async def toi_message_reader(self,tel):
        try:
            r = get_reader(f'tic.status.{tel}.toi.message', deliver_policy='new')
            async for data, meta in r:
                txt = f"{time.strftime('%H:%M:%S', time.gmtime())}"
                if "info" in data.keys() and "tel" in data.keys():
                    if "BELL" in data['info']:
                        txt = f"(UT {txt}) {data['info']} by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/romulan_alarm.wav"])
                    elif "STOP" in data['info']:
                        txt = f"(UT {txt}) {data['info']} reached by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/alert06.wav"])
                    elif "PING" in data['info']:
                        txt = f"(UT {txt}) {data['info']} reached by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/tos_alien_sound_4.wav"])
                    else:
                        txt = f"(UT {txt}) {data['info']} by {data['tel']}"
                        self.info_e.append(txt)
                        subprocess.run(["aplay",f"{os.getcwd()}/sounds/computerbeep_12.wav"])


        except Exception as e:
            logger.warning(f'{e}')


widget_class = ButtonsMessageKitchenWidget