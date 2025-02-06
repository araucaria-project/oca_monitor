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

def ephemeris():
    arm=ephem.Observer()
    arm.pressure=730
    arm.lon='-70.201266'
    arm.lat='-24.598616'
    arm.elev=2800
    arm.pressure=730
    lt = time.strftime('%Y/%m/%d %H:%M:%S',time.localtime() )
    sun = ephem.Sun()
    sun.compute(arm)
    return lt,sun.alt

class bboxItem():
    def __init__(self,name,ip,slide):
        self.name = name
        self.ip = ip
        self.button = button

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
                if self.button.isChecked():
                    value = 1
                else:
                    value = 0
                
                self.req(value)
            #except:
            #    pass

    def req(self,val):
        requests.post('http://'+self.ip+'/state',json={"relays":[{"relay":0,"state":val}]})


'''class lightSlide():
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
            self.is_active = False'''


class TouchButtonsWBedroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 temp_subject='telemetry.conditions.bedroom-west-tsensor',
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.main_window = main_window
        self.weather_subject = subject
        self.temp_subject = temp_subject
        self.initUI(example_parameter,subject)

    def initUI(self, text,subject):
        
        self.layout = QHBoxLayout(self)
        self.vbox_left = QVBoxLayout()
        self.vbox_center = QVBoxLayout()
        self.vbox_right = QVBoxLayout()
        
        self.label_ephem = QLabel("ephem")
        self.label_ephem.setStyleSheet("background-color : gray; color: white")
        self.label_ephem.setFont(QtGui.QFont('Arial', 26))

        self.vbox_left.addWidget(self.label_ephem)

        self.label_weather = QLabel("weather")
        self.label_weather.setStyleSheet("background-color : silver; color: black")
        self.label_weather.setFont(QtGui.QFont('Arial', 26))

        self.vbox_center.addWidget(self.label_weather)

        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.stateChanged.connect(self.send_alarm)

        self.vbox_right.addWidget(self.b_alarm)
                
        self.water_pump=bboxItem('hot_water',config.bbox_bedroom_west['hot_water'],QCheckBox())
        self.water_pump.button.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/"+item+"_on.png)} QCheckBox::indicator:unchecked {image: url(./Icons/"+item+"_off.png)}")
        self.water_pump.button.setChecked(False)
        self.water_pump.button.stateChanged.connect(self.bedroomStaff[-1].changeState)
        self.vbox_left.addWidget(self.water_pump.button)

    
        self.layout.addLayout(self.vbox_left)
        self.layout.addLayout(self.vbox_center)
        self.layout.addLayout(self.vbox_right)

        # Some async operation
        
        QtCore.QTimer.singleShot(1000, self._update_weather)
        QtCore.QTimer.singleShot(1000, self._update_ephem)
        
        logger.info("UI setup done")

    
    @asyncSlot()
    async def button_pressed(self):
        if self.b_abort.isChecked:
            await self.raise_alarm('EMERGENCY STOP OBS!')
            
        self.b_abort.setChecked(False)

    @asyncSlot()
    async def send_alarm(self):
        if self.b_alarm.isChecked:
            await self.raise_alarm('OCM: HELP US, ')

        self.b_alarm.setChecked(False)


    async def raise_alarm(self,mess):
        for name,po_data in config.pushover.items():
            user = po_data[0]
            token = po_data[1]
            pars = {'token':token,'user':user,'message':mess+name+'!'}
            requests.post('https://api.pushover.net/1/messages.json',data=pars)

    def _update_ephem(self):
        lt,sunalt = ephemeris()
        sunalt = str(sunalt)
        text = str(lt)+'\nSUN ALT: '+sunalt
        self.label_ephem.setText(text)
        
        QtCore.QTimer.singleShot(1000, self._update_ephem)

    @asyncSlot()
    async def _update_warningWindow(self):
        self.wind = '0.0'
        self.temp = '0.0'
        self.hum = '0.0'
        self.pres = '0.0'
        await create_task(self.reader_loop_2(), "weather reader")
        #warning = 'Wind: '+str(self.wind)+' m/s\n'+'Temperature: '+str(self.temp)+' C\n'+'Humidity: '+str(self.hum)+' %\n'+'Wind dir: '+str(self.main_window.winddir)+'\n'
        #self.label.setText(warning)
    

    async def reader_loop_2(self):
        
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
            self.wind = "{:.1f}".format(measurement['wind_10min_ms'])
            self.temp = "{:.1f}".format(measurement['temperature_C'])
            self.hum = int(measurement['humidity'])
            self.pres = int(measurement['pressure_Pa'])
            self.winddir = int(measurement['wind_dir_deg'])

            self.main_window.wind = self.wind
            self.main_window.temp = self.temp
            self.main_window.hum = self.hum
            self.main_window.winddir = self.winddir
            self.main_window.skytemp = '0'
            if self.vertical:
                warning = 'Wind:\t'+str(self.wind)+' m/s\n'+'Temp:\t'+str(self.temp)+' C\n'+'Hum:\t'+str(self.hum)+' %\n'+'Wdir:\t'+str(self.main_window.winddir)+' deg'
            else:
                warning = '   Wind:\t\t'+str(self.wind)+' m/s\n'+'   Temperature:\t'+str(self.temp)+' C\n'+'   Humidity:\t'+str(self.hum)+' %\n'+'   Wind dir:\t'+str(self.main_window.winddir)+' deg'
            if (float(self.wind) >= 11. and float(self.wind) < 14.) or float(self.hum) > 70.:
                self.label.setStyleSheet("background-color : yellow; color: black")
                if self.main_window.sound_page:
                    self.main_window.sound_page.play_weather_warning(True)
            elif float(self.wind) >= 14. or float(self.hum) > 75. or float(self.temp) < 0.:
                self.label.setStyleSheet("background-color : red; color: black")
                if self.main_window.sound_page:
                    self.main_window.sound_page.play_weather_warning(False)
                    self.main_window.sound_page.play_weather_stop(True)
            else:
                if self.main_window.sound_page:
                    self.main_window.sound_page.play_weather_warning(False)
                    self.main_window.sound_page.play_weather_stop(False)
                self.label.setStyleSheet("background-color : lightgreen; color: black")

            self.label.setText(warning)

widget_class = TouchButtonsWBedroom
