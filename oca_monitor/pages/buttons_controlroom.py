import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox
from PyQt6 import QtCore
import json,requests
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base.task_manager import create_task_sync, create_task
# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

class lightSlide():
    def __init__(self,name,ip,slide):
        self.name = name
        self.ip = ip
        self.slide = slide

    def is_avilable(self):
        try:
            req = requests.post('http://'+self.ip+'/info',timeout=1.0)
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
        



class ButtonsWidgetControlroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.initUI(example_parameter)

    def initUI(self, text):
        self.layout = QVBoxLayout(self)
        self.label = QLabel(f"Telescopes", self)
        self.layout.addWidget(self.label)

        self.b_abort = QPushButton(self)#abort button
        self.b_abort.setStyleSheet("background-color : red")
        self.b_abort.setText("ABORT OBSERVATIONS")
        self.b_abort.setFixedSize(300, 100)
        self.layout.addWidget(self.b_abort)

        self.lightSlides = []
        for i,light in enumerate(config.bbox_led_control_tel):
            self.lightSlides.append(lightSlide(light,config.bbox_led_control_tel[light],QCheckBox()))
            self.lightSlides[-1].slide.setStyleSheet("QCheckBox::indicator{width: 80px; height:70px;} QCheckBox::indicator:checked {image: url(./Icons/"+light+"_lighton.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light+"_lightoff.png)}")
            self.lightSlides[-1].slide.setChecked(False)
            self.lightSlides[-1].slide.stateChanged.connect(self.lightSlides[-1].changeLight)
            self.layout.addWidget(self.lightSlides[-1].slide)

        # Some async operation
        self._update_lights_status()
        logger.info("UI setup done")

    def _update_lights_status(self):
        for light in self.lightSlides:
            light.is_avilable()
            if light.is_active:
                light.slide.setStyleSheet("QCheckBox::indicator{width: 80px; height:70px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_lighton.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_lightoff.png)}")
            else:
                light.slide.setStyleSheet("QCheckBox::indicator{width: 80px; height:70px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_lightna.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_lightna.png)}")

        QtCore.QTimer.singleShot(30000, self._update_lights_status)
    

widget_class = ButtonsWidgetControlroom
