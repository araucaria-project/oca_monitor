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
        



class TouchButtonsControlroom(QWidget):
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
        
        self.layout = QHBoxLayout(self)
        self.b_abort = QCheckBox()#abort button
        self.b_abort.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/closedomeson.png)} QCheckBox::indicator:unchecked {image: url(./Icons/closedomesoff.png)}")
        self.b_abort.stateChanged.connect(self.abort_observations)
        
        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.stateChanged.connect(self.send_alarm)

        self.enable_abort = QCheckBox('Enable abort button')
        self.enable_abort.setStyleSheet("QCheckBox::indicator{width: 120px; height:80px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.enable_warnings = QCheckBox('Enable warnings')
        self.enable_warnings.setStyleSheet("QCheckBox::indicator{width: 120px; height:80px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.enable_sounds = QCheckBox('Enable sounds')
        self.enable_sounds.setStyleSheet("QCheckBox::indicator{width: 120px; height:80px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.vbox_enable_buttons = QVBoxLayout()
        self.vbox_enable_buttons.addWidget(self.enable_warnings)
        self.vbox_enable_buttons.addWidget(self.enable_sounds)
        self.vbox_enable_buttons.addWidget(self.enable_abort)

        self.vbox_emergency_buttons = QVBoxLayout()
        self.vbox_emergency_buttons.addWidget(self.b_alarm)
        self.vbox_emergency_buttons.addWidget(self.b_abort)
        
                
        self.vbox_light_buttons_left = QVBoxLayout()
        self.vbox_light_buttons_right = QVBoxLayout()
        self.hbox_light_buttons = QHBoxLayout()
        #self.vbox_light_buttons_left.addWidget(self.label_lights)


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

        QtCore.QTimer.singleShot(15000, self._update_lights_status)

    @asyncSlot()
    async def send_alarm(self):
        if self.b_alarm.isChecked:
            await self.raise_alarm('OCM: HELP!')
            time.sleep(3)
            self.b_alarm.setChecked(False)

    @asyncSlot()
    async def abort_observations(self):
        if self.b_abort.isChecked:
            await self.raise_alarm('EMERGENCY STOP OBS!')
            time.sleep(3)
            self.b_abort.setChecked(False)

    async def raise_alarm(self,mess):
        pars = {'token':'adcte9qacd6jhmhch8dyw4e4ykuod2','user':'uacjyhka7d75k5i3gmfhdg9pc2vqyf','message':mess}
        requests.post('https://api.pushover.net/1/messages.json',data=pars)


widget_class = TouchButtonsControlroom
