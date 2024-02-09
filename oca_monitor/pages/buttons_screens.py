import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel,QSlider,QDial,QScrollBar
from PyQt6 import QtCore
import json,requests
import oca_monitor.config as config

# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

class lightSlide():
    def __init__(self,name,ip,slide):
        self.name = name
        self.ip = ip
        self.slide = slide

    def changeLight(self,value):
        try:
            self.slide.setValue(value)
            val = str(hex(int(value*255/100))).replace('0x','',1)
            if len(val) == 1:
                val = '0'+val
            
            self.req(self.ip,val)
        except:
            pass

    def req(self,ip,val):
        requests.post('http://'+ip+'/api/rgbw/set',json={"rgbw":{"desiredColor":val}})



class ButtonsWidget(QWidget):
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
        for i,light in enumerate(config.bbox_led_control):
            self.lightSlides.append(lightSlide(light,config.bbox_led_control[light],QSlider(self)))
            #self.lightSlides[-1].slide.groove(background="#C9CDD0",height='50px')
            self.lightSlides[-1].slide.setRange(0,100)
            self.lightSlides[-1].slide.setPageStep(10)
            self.lightSlides[-1].slide.valueChanged.connect(self.lightSlides[-1].changeLight)
            self.layout.addWidget(self.lightSlides[-1].slide)

        # Some async operation
        logger.info("UI setup done")

    

widget_class = ButtonsWidget
