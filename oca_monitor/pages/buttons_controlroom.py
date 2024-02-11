import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel,QSlider,QDial,QScrollBar
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

    def changeLight(self,value):
        try:
            #if True:
            self.slide.setValue(value)
            val = str(hex(int(value*255/100))).replace('0x','',1)
            if len(val) == 1:
                val = '0'+val
            
            self.req(val)
        except:
            pass

    def req(self,val):
        requests.post('http://'+self.ip+'/api/rgbw/set',json={"rgbw":{"desiredColor":val}}),"setLight"
        



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
        self.label = QLabel(f"Secret message: {text}", self)
        self.layout.addWidget(self.label)
        self.lightSlides = []
        for i,light in enumerate(config.bbox_led_control_tel):
            self.lightSlides.append(lightSlide(light,config.bbox_led_control_tel[light],QSlider(QtCore.Qt.Orientation.Horizontal)))
            self.lightSlides[-1].slide.setStyleSheet('''
                QSlider::handle:horizontal{{
                    image: url({});
                    width:"64px";
                    height:"64px";
                }}
                '''.format("./Icons/zb08.png"))
            #self.lightSlides.append(lightSlide(light,config.bbox_led_control_tel[light],QDial(self)))
            #self.lightSlides[-1].slide.groove()
            self.lightSlides[-1].slide.setRange(0,100)
            self.lightSlides[-1].slide.setPageStep(10)
            self.lightSlides[-1].slide.valueChanged.connect(self.lightSlides[-1].changeLight)
            self.layout.addWidget(self.lightSlides[-1].slide)

        # Some async operation
        logger.info("UI setup done")

    

widget_class = ButtonsWidgetControlroom
