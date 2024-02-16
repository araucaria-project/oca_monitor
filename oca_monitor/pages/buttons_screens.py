import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox
from PyQt6 import QtCore,QtGui
import json,requests
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base.task_manager import create_task_sync, create_task
# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

class light_point():
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
        #try:
        if True:
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
        #except:
        #    pass

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
        



class ButtonsWidget(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 **kwargs  # other parameters.setStyleSheet("background-color : silver
                 ):
        super().__init__()
        self.initUI(example_parameter)

    def initUI(self, text):
        self.layout = QVBoxLayout(self)
        self.label = QLabel(f"Secret message: {text}", self)
        self.layout.addWidget(self.label)
        self.lights = []
        hlayout = QHBoxLayout()
        for i,light in enumerate(config.bbox_led_control):
            self.lights.append(light_point(light,config.bbox_led_control[light],QPushButton('+'),QPushButton('-'),QLabel('LIGHT '+light)))
            vbox = QVBoxLayout()
            hbox = QHBoxLayout()
            hbox.addWidget(self.lights[-1].b_faint)
            hbox.addWidget(self.lights[-1].b_bright)
            vbox.addWidget(self.lights[-1].label)
            vbox.addLayout(hbox)
            self.layout.addLayout(vbox)

        self.label = QLabel("TEL STATUS -not working yet")
        self.label.setStyleSheet("background-color : lightgreen; color: black")
        self.label.setFont(QtGui.QFont('Arial', 20))
        
        hlayout.addLayout(vbox,1)
        hlayout.addWidget(self.label,3)
        

        self.b_abort = QPushButton(self)#abort button
        self.b_abort.setStyleSheet("background-color : red; color: black")
        self.b_abort.setText("ABORT\n OBSERVATIONS\n- not working")
        self.b_abort.setFixedSize(140, 80)
        self.enable_abort = QCheckBox('Enable abort button')
        self.enable_abort.setStyleSheet("QCheckBox::indicator{width: 60px; height:40px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
        hlayout.addWidget(self.b_abort)
        hlayout.addWidget(self.enable_abort)
        self.layout.addLayout(hlayout)
        # Some async operation
        logger.info("UI setup done")

    

widget_class = ButtonsWidget
