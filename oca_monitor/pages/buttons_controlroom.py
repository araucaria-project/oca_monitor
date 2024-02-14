import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox
from PyQt6 import QtCore, QtGui
import json,requests
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
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
        



class ButtonsWidgetControlroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 **kwargs  # other parameters
                 ):
        super().__init__()
        
        self.initUI(example_parameter,subject)

    def initUI(self, text,subject):
        self.weather_subject=subject
        self.layout = QVBoxLayout(self)
        self.label = QLabel("STATUS -not working yet")
        self.label.setStyleSheet("background-color : lightgreen; color: black")
        self.label.setFont(QtGui.QFont('Arial', 20))
        self.layout.addWidget(self.label)

        self.b_abort = QPushButton(self)#abort button
        self.b_abort.setStyleSheet("background-color : red; color: black")
        self.b_abort.setText("ABORT\n OBSERVATIONS\n- not working")
        self.b_abort.setFixedSize(150, 150)
        self.enable_abort = QCheckBox('Enable abort button')
        self.enable_abort.setStyleSheet("QCheckBox::indicator{width: 60px; height:40px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.enable_warnings = QCheckBox('Enable warnings')
        self.enable_warnings.setStyleSheet("QCheckBox::indicator{width: 60px; height:40px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.enable_sounds = QCheckBox('Enable sounds')
        self.enable_sounds.setStyleSheet("QCheckBox::indicator{width: 60px; height:40px;} QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)} QCheckBox::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.vbox_buttons = QVBoxLayout()
        self.vbox_buttons.addWidget(self.enable_warnings)
        self.vbox_buttons.addWidget(self.enable_sounds)
        self.vbox_buttons.addWidget(self.enable_abort)

        self.hbox_abortButton = QHBoxLayout(self)
        self.hbox_abortButton.addLayout(self.vbox_buttons)
        self.hbox_abortButton.addWidget(self.b_abort)
        self.layout.addLayout(self.hbox_abortButton)

        self.label_lights = QLabel(f"LIGHTS", self)
        self.label_lights.setStyleSheet("background-color: grey; color: black")
        self.vbox_light_buttons_left = QVBoxLayout()
        self.vbox_light_buttons_right = QVBoxLayout()
        self.hbox_light_buttons = QHBoxLayout()
        self.vbox_light_buttons_left.addWidget(self.label_lights)


        self.lightSlides = []
        for i,light in enumerate(config.bbox_led_control_tel):
            self.lightSlides.append(lightSlide(light,config.bbox_led_control_tel[light],QCheckBox()))
            self.lightSlides[-1].slide.setStyleSheet("QCheckBox::indicator{width: 80px; height:70px;} QCheckBox::indicator:checked {image: url(./Icons/"+light+"_lighton.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light+"_lightoff.png)}")
            self.lightSlides[-1].slide.setChecked(False)
            self.lightSlides[-1].slide.stateChanged.connect(self.lightSlides[-1].changeLight)

            if i%2==1:
                self.vbox_light_buttons_right.addWidget(self.lightSlides[-1].slide)
            else:
                self.vbox_light_buttons_left.addWidget(self.lightSlides[-1].slide)

        self.hbox_light_buttons.addLayout(self.vbox_light_buttons_left)
        self.hbox_light_buttons.addLayout(self.vbox_light_buttons_right)
        self.layout.addLayout(self.hbox_light_buttons)

        # Some async operation
        self._update_lights_status()
        QtCore.QTimer.singleShot(0, self._update_warningWindow)
        logger.info("UI setup done")

    @asyncSlot()
    async def _update_warningWindow(self):
        self.wind = '0.0'
        self.temp = '0.0'
        self.hum = '0.0'
        self.pres = '0.0'
        await create_task(self.reader_loop(), "weather reader")
        warning = 'Wind: '+str(self.wind)+' m/n\n'+'Temperature: '+str(self.temp)+' C\n'+'Humidity: '+str(self.hum)+' %\n'
        self.label.setText(warning)

    

    def _update_lights_status(self):
        for light in self.lightSlides:
            light.is_avilable()
            if light.is_active:
                light.slide.setStyleSheet("QCheckBox::indicator{width: 80px; height:70px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_lighton.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_lightoff.png)}")
            else:
                light.slide.setStyleSheet("QCheckBox::indicator{width: 80px; height:70px;} QCheckBox::indicator:checked {image: url(./Icons/"+light.name+"_lightna.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+light.name+"_lightna.png)}")

        QtCore.QTimer.singleShot(30000, self._update_lights_status)

    
    

    async def reader_loop(self):
        msg = Messenger()

        # We want the data from the midnight of yesterday
        

        rdr = msg.get_reader(
            self.weather_subject,
            deliver_policy='last',
        )
        logger.info(f"Subscribed to {self.weather_subject}")

        sample_measurement = {
                "temperature_C": 10,
                "humidity": 50,
                "wind_dir_deg": 180,
                "wind_ms": 5,
                "wind_10min_ms": 5,
                "pressure_Pa": 101325,
                "bar_trend": 0,
                "rain_mm": 0,
                "rain_day_mm": 0,
                "indoor_temperature_C": 20,
                "indoor_humidity": 50,
        }
        async for data, meta in rdr:
            ts = dt_ensure_datetime(data['ts']).astimezone()
            hour = ts.hour + ts.minute / 60 + ts.second / 3600
            measurement = data['measurements']
            self.wind_speed10 = measurement['wind_10min_ms']
            self.temp = measurement['temperature_C']
            self.hum = measurement['humidity']
            self.pres = measurement['pressure_Pa']

            warning = 'Wind: '+str(self.wind)+' m/n\n'+'Temperature: '+str(self.temp)+' C\n'+'Humidity: '+str(self.hum)+' %\n'
            self.label.setText(warning)


widget_class = ButtonsWidgetControlroom
