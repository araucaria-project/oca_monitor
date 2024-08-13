import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QPushButton,QCheckBox
from PyQt6 import QtCore,QtGui
import json,requests
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base.task_manager import create_task_sync, create_task
# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

class light_point_old():
    def __init__(self,name,ip,button_brighter,button_fainter,label):
        self.name = name
        self.ip = ip
        self.label = label
        self.b_bright = button_brighter
        self.b_faint = button_fainter
        self.b_bright.setStyleSheet("background-color : silver; color: black")
        self.b_faint.setStyleSheet("background-color : silver; color: black")
        self.b_bright.clicked.connect(self.brightLight)
        self.b_faint.clicked.connect(self.dimLight)
        self.label.setStyleSheet("background-color : silver; color: black")

    def brightLight(self):
        try:
        #if True:
            self.status()
            #if True:
            if self.is_active:
                new_value = self.curr_value + 25
                if new_value > 255:
                    new_value = 255

                val = str(hex(int(new_value))).replace('0x','',1)
                if len(val) == 1:
                    val = '0'+val
                
                self.req(val)
        except:
            pass

    def dimLight(self):
        try:
            self.status()
            #if True:
            if self.is_active:
                new_value = self.curr_value - 25
                if new_value < 0:
                    new_value = 0

                val = str(hex(int(new_value))).replace('0x','',1)
                if len(val) == 1:
                    val = '0'+val
                
                self.req(val)
        except:
            pass

    def req(self,val):
        requests.post('http://'+self.ip+'/api/rgbw/set',json={"rgbw":{"desiredColor":val}})

    def status(self):
        #try:
        if True:
            req = requests.get('http://'+self.ip+'/api/rgbw/state',timeout=0.5)
            
            if int(req.status_code) != 200:
                self.is_active = False
            else:
                self.is_active = True 
                self.curr_value = int(req.json()["rgbw"]["desiredColor"],16)
        #except:
        #    self.is_active = False

class light_point():
    def __init__(self,name,ip,slider):
        self.name = name
        self.ip = ip
        
        self.slider= slider
        
        self.slider.valueChanged.connect(self.changeLight)

    def changeLight(self):
        try:
        #if True:
            self.status()
            #if True:
            if self.is_active:
                new_value = int(self.slider.value()*255/100)

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
        #try:
        if True:
            req = requests.get('http://'+self.ip+'/api/rgbw/state',timeout=0.5)
            
            if int(req.status_code) != 200:
                self.is_active = False
            else:
                self.is_active = True 
                self.curr_value = int(req.json()["rgbw"]["desiredColor"],16)
                self.slider.setValue(int(self.curr_value*100/255))
        #except:
        #    self.is_active = False
        



class ButtonsWidgetTVroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 **kwargs  # other parameters.setStyleSheet("background-color : silver
                 ):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.layout = QHBoxLayout(self)
        self.lights = []
        
        for i,light in enumerate(config.bbox_led_control_tvroom):
            #self.lights.append(light_point(light,config.bbox_led_control[light],QPushButton('+'),QPushButton('-'),QLabel('LIGHT '+light)))
            self.lights.append(light_point(light,config.bbox_led_control[light],QDial()))
            #vbox = QVBoxLayout()
        
            #hbox.addWidget(self.lights[-1].b_faint)
            #hbox.addWidget(self.lights[-1].b_bright)
            #vbox.addWidget(self.lights[-1].label)
            #vbox.addLayout(hbox)

        self.layout.addWidget(self.lights[-1].slider)
        #self.label = QLabel("TEL STATUS -not working yet")
        #self.label.setStyleSheet("background-color : lightgreen; color: black")
        #self.label.setFont(QtGui.QFont('Arial', 20))
        
        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.stateChanged.connect(self.send_alarm)
        self.layout.addWidget(self.b_alarm)
        # Some async operation
        logger.info("UI setup done")

    @asyncSlot()
    async def send_alarm(self):
        if self.b_alarm.isChecked:
            await self.raise_alarm('OCM: HELP!')

        self.b_alarm.setChecked(False)

    async def raise_alarm(self,mess):
        pars = {'token':'adcte9qacd6jhmhch8dyw4e4ykuod2','user':'uacjyhka7d75k5i3gmfhdg9pc2vqyf','message':mess}
        requests.post('https://api.pushover.net/1/messages.json',data=pars)



        
        


widget_class = ButtonsWidgetTVroom
