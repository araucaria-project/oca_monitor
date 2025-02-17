import logging
from PyQt6.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox
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




class lightSlide():
    def __init__(self,name,ip,slide):
        self.name = name
        self.ip = ip
        self.slide = slide

    def is_avilable(self):
        try:
        #if True:
            req = requests.get('http://'+self.ip+'/info',timeout=0.5)
            if int(req.status_code) != 200:
                self.is_active = False
            else:
                self.is_active = True 
        except:
            self.is_active = False

    def changeLight(self):
        if self.is_active:
            try:
                #if True:
                if self.slide.isChecked():
                    value = 70
                else:
                    value = 0
            
                val = str(hex(int(value*255/100))).replace('0x','',1)
                if len(val) == 1:
                    val = '0'+val
                
                self.req(val)
            except:
                pass

    def req(self,val):
        requests.post('http://'+self.ip+'/api/rgbw/set',json={"rgbw":{"desiredColor":val}})
        
class light_point():
    def __init__(self,name,ip,slider):
        self.name = name
        self.ip = ip
        
        self.slider= slider
        self.slider.setGeometry(50, 50, 50, 50)
        self.slider.setNotchesVisible(True)
        self.slider.valueChanged.connect(self.changeLight)

    def changeLight(self):
        try:
        #if True:
            #self.status()
            #if True:
            if self.is_active:
                new_value = int(self.slider.value()*255/100)
                #print(new_value)
                if new_value > 255:
                    new_value = 255

                val = str(hex(int(new_value))).replace('0x','',1)
                if len(val) == 1:
                    val = '0'+val
                
                self.req(val)
        except:
            pass

    

    def req(self,val):
        requests.post('http://'+self.ip+'/api/rgbw/set',json={"rgbw":{"desiredColor":val}})

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


class TouchButtonsControlroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 light='',
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.main_window = main_window
        self.light = light
        self.initUI(example_parameter,subject)

    def initUI(self, text,subject):
        
        self.layout = QHBoxLayout(self)
        self.b_abort = QCheckBox()#abort button
        self.b_abort.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/closedomeson.png)} QCheckBox::indicator:unchecked {image: url(./Icons/closedomesoff.png)}")
        self.b_abort.stateChanged.connect(self.abort_observations)
        
        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.stateChanged.connect(self.send_alarm)


        self.enable_sounds = QCheckBox('Enable sounds')
        self.enable_sounds.setStyleSheet("QCheckBox::indicator{width: 120px; height:80px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.vbox_enable_buttons = QVBoxLayout()
        self.vbox_enable_buttons.addWidget(self.enable_sounds,1)
        

        self.vbox_emergency_buttons = QVBoxLayout()
        self.vbox_emergency_buttons.addWidget(self.b_abort)
        self.vbox_emergency_buttons.addWidget(self.b_alarm)
                
        self.vbox_light_buttons_left = QVBoxLayout()
        self.vbox_light_buttons_right = QVBoxLayout()
        self.hbox_light_buttons = QHBoxLayout()
        #self.vbox_light_buttons_left.addWidget(self.label_lights)

        self.swiatlo=light_point(self.light,config.bbox_led_control_main[self.light],QDial())
        self.vbox_enable_buttons.addWidget(self.swiatlo.slider,1)

        self.lightSlides = []
        for i,light in enumerate(config.bbox_led_control_tel):
            self.lightSlides.append(lightSlide(light,config.bbox_led_control_tel[light],QCheckBox()))
            self.lightSlides[-1].slide.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/"+light+"_lighton.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light+"_lightoff.png)}")
            self.lightSlides[-1].slide.setChecked(False)
            self.lightSlides[-1].slide.stateChanged.connect(self.lightSlides[-1].changeLight)

            if i%2==1:
                self.vbox_light_buttons_right.addWidget(self.lightSlides[-1].slide)
            else:
                self.vbox_light_buttons_left.addWidget(self.lightSlides[-1].slide)

        self.hbox_light_buttons.addLayout(self.vbox_light_buttons_left)
        self.hbox_light_buttons.addLayout(self.vbox_light_buttons_right)

        self.hbox_main = QHBoxLayout()
        self.hbox_main.addLayout(self.hbox_light_buttons)
        self.hbox_main.addLayout(self.vbox_enable_buttons)
        self.hbox_main.addLayout(self.vbox_emergency_buttons)
        self.layout.addLayout(self.hbox_main)

        # Some async operation
        
        self._update_lights_status()
        
        logger.info("UI setup done")

    
    def _update_lights_status(self):
        for light in self.lightSlides:
            light.is_avilable()
            if light.is_active:
                light.slide.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_lighton.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_lightoff.png)}")
            else:
                light.slide.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_lightna.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_lightna.png)}")

        self.swiatlo.status()
            

        QtCore.QTimer.singleShot(15000, self._update_lights_status)


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
            self.d.button_close.setText('CLOSE')
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
            label.setText('Alarm sent')
            button = QPushButton('OK')
            button.clicked.connect(self.c_close_clicked)
            layout = QHBoxLayout()
            layout.addWidget(label)
            layout.addWidget(button)
            self.c.exec()
        

        await self.siren(wyj)
        if self.b_alarm.isChecked():
            QtCore.QTimer.singleShot(2000, self.siren(mes='',wyj=0))
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


    @asyncSlot()
    async def abort_observations(self):
        if self.b_abort.isChecked:
            await self.raise_alarm('EMERGENCY STOP OBS!')
            
        self.b_abort.setChecked(False)


widget_class = TouchButtonsControlroom
