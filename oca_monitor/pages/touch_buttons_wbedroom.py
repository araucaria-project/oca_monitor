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

class bboxItem():
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

    def changeState(self):
        if self.is_active:
            #try:
            if True:
                if self.slide.isChecked():
                    value = 1
                else:
                    value = 0
                
                self.req(value)
            #except:
            #    pass

    def req(self,val):
        requests.post('http://'+self.ip+'/state',json={"relays":[{"relay":0,"state":val}]})


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


class TouchButtonsWBedroom(QWidget):
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
        
        
        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.stateChanged.connect(self.send_alarm)
        
        

        self.vbox_emergency_buttons = QVBoxLayout()
        self.vbox_emergency_buttons.addWidget(self.b_alarm)
                
        self.vbox_light_buttons_left = QVBoxLayout()
        self.vbox_light_buttons_right = QVBoxLayout()
        self.hbox_light_buttons = QHBoxLayout()
        #self.vbox_light_buttons_left.addWidget(self.label_lights)

        self.lights = []
        
        for i,light in enumerate(config.bbox_led_control_controlroom):
            #self.lights.append(light_point(light,config.bbox_led_control[light],QPushButton('+'),QPushButton('-'),QLabel('LIGHT '+light)))
            self.lights.append(light_point(light,config.bbox_led_control_controlroom[light],QDial()))
            self.vbox_enable_buttons.addWidget(self.lights[-1].slider,1)

        self.bedroomStaff = []
        for i,item in enumerate(config.bbox_bedroom_west):
            self.bedroomStaff.append(bboxItem(item,config.bbox_bedroom_west[item],QCheckBox()))
            self.bedroomStaff[-1].slide.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/"+item+"_on.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+item+"_off.png)}")
            self.bedroomStaff[-1].slide.setChecked(False)
            self.bedroomStaff[-1].slide.stateChanged.connect(self.bedroomStaff[-1].changeState)

            if i%2==1:
                self.vbox_light_buttons_right.addWidget(self.bedroomStaff[-1].slide)
            else:
                self.vbox_light_buttons_left.addWidget(self.bedroomStaff[-1].slide)

        self.hbox_light_buttons.addLayout(self.vbox_light_buttons_left)
        self.hbox_light_buttons.addLayout(self.vbox_light_buttons_right)

        self.hbox_main = QHBoxLayout()
        self.hbox_main.addLayout(self.hbox_light_buttons)
        self.hbox_main.addLayout(self.vbox_emergency_buttons)
        self.layout.addLayout(self.hbox_main)

        # Some async operation
        
        self._update_lights_status()
        
        logger.info("UI setup done")

    
    def _update_lights_status(self):
        for light in self.bedroomStaff:
            light.is_avilable()
            if light.is_active:
                light.slide.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_on.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_off.png)}")
            #else:
            #    light.slide.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_na.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_na.png)}")

        for light in self.lights:
            light.status()
            

        QtCore.QTimer.singleShot(15000, self._update_lights_status)


    @asyncSlot()
    async def send_alarm(self):
        if self.b_alarm.isChecked:
            await self.raise_alarm('OCM: HELP!')

        self.b_alarm.setChecked(False)

    @asyncSlot()
    async def abort_observations(self):
        if self.b_abort.isChecked:
            await self.raise_alarm('EMERGENCY STOP OBS!')
            
        self.b_abort.setChecked(False)

    async def raise_alarm(self,mess):
        pars = {'token':'adcte9qacd6jhmhch8dyw4e4ykuod2','user':'uacjyhka7d75k5i3gmfhdg9pc2vqyf','message':mess}
        requests.post('https://api.pushover.net/1/messages.json',data=pars)

        # mgorski tez tu nizej
        pars = {'token':"adcte9qacd6jhmhch8dyw4e4ykuod2",'user':"ugcgrfrrfn4eefnpiekgwqnxfwtrz5",'message':mess}
        requests.post('https://api.pushover.net/1/messages.json',data=pars)


widget_class = TouchButtonsWBedroom
