import logging
from PyQt6.QtWidgets import QDialog,QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox
from PyQt6 import QtCore, QtGui
from PyQt6.QtGui import QPixmap
import json,requests
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
import ephem
import time
from astropy.time import Time as czas_astro
import os
# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

def ephemeris():
    arm=ephem.Observer()
    arm.pressure=730
    arm.lon='-70.201266'
    arm.lat='-24.598616'
    arm.elev=2800
    arm.pressure=730
    #lt = time.strftime('%H:%M:%S %Y/%m/%d',time.localtime() )
    lt = time.strftime('%H:%M:%S',time.localtime() )
    sun = ephem.Sun()
    sun.compute(arm)
    #return str(lt).replace(' ','\n\n',1),str(sun.alt).split(':')[0]
    return str(lt),str(sun.alt).split(':')[0]

class bboxItem():
    def __init__(self,name,ip,button):
        self.name = name
        self.ip = ip
        self.button = button
        self.is_available()

    def is_available(self):
        try:
        #if True:
            req = requests.get('http://'+self.ip+'/info',timeout=0.5)
            if int(req.status_code) != 200:
                self.is_active = False
            else:
                self.is_active = True 
        except:
            self.is_active = False
        return self.is_active

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

        return True

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
                 allsky_dir='/data/misc/allsky/',
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 temp_subject='telemetry.conditions.bedroom-west-tsensor',
                 room = '',
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.main_window = main_window
        self.weather_subject = subject
        self.temp_subject = temp_subject
        self.room = room
        self.freq = 2000
        self.counter = 0
        self.dir = allsky_dir
        self.initUI(example_parameter,subject)

    def initUI(self, text,subject):
        
        self.layout = QHBoxLayout(self)
        self.vbox_left = QVBoxLayout()
        self.vbox_center = QVBoxLayout()
        self.vbox_right = QVBoxLayout()
        
        self.label_ephem = QLabel("ephem")
        self.label_ephem.setStyleSheet("background-color : #2b2b2b; color: white; font-weight: bold")
        self.label_ephem.setFont(QtGui.QFont('Arial', 52))

        self.vbox_left.addWidget(self.label_ephem)


        self.label_weather = QLabel("weather")
        self.label_weather.setStyleSheet("background-color : silver; color: black")
        self.label_weather.setFont(QtGui.QFont('Arial', 34))

        self.vbox_center.addWidget(self.label_weather)

        self.label_temp = QLabel("temp")
        self.label_temp.setStyleSheet("background-color : #2b2b2b; color: white; font-weight: bold")
        self.label_temp.setFont(QtGui.QFont('Arial', 52))

        self.vbox_left.addWidget(self.label_temp)

        self.b_alarm = QCheckBox()#abort button
        self.b_alarm.setStyleSheet("QCheckBox::indicator{width: 300px; height:300px;} QCheckBox::indicator:checked {image: url(./Icons/alarmon.png)} QCheckBox::indicator:unchecked {image: url(./Icons/alarmoff.png)}")
        self.b_alarm.clicked.connect(self.send_alarm)
        self.b_alarm.setChecked(False)

        self.vbox_right.addWidget(self.b_alarm)

        self.label_allsky = QLabel()
        self.label_allsky.resize(100,100)
        self.vbox_right.addWidget(self.label_allsky,1)
        
                
        self.water_pump=bboxItem('hot_water',config.bbox_bedroom_west['hot_water'],QCheckBox())
        self.water_pump.button.setStyleSheet("QCheckBox::indicator{width: 200px; height:200px;} QCheckBox::indicator:checked {image: url(./Icons/hot_water_on.png)} QCheckBox::indicator:unchecked {image: url(./Icons/hot_water_off.png)}")
        self.water_pump.button.setChecked(False)
        self.water_pump.button.stateChanged.connect(self.water_button_pressed)
        self.vbox_center.addWidget(self.water_pump.button)

    
        self.layout.addLayout(self.vbox_left)
        self.layout.addLayout(self.vbox_center)
        self.layout.addLayout(self.vbox_right)

        # Some async operation
        
        self._update_weather()
        self._update_ephem()
        self._update_temp()
        self._update_allsky()
        
        logger.info("UI setup done")

   

    def _update_allsky(self):
        lista = os.popen('ls -tr '+self.dir+'lastimage*.jpg').read().split('\n')[:-1]
        if len(lista) > 0:
            try:
                figure = QPixmap(lista[self.counter])
                self.label_allsky.setPixmap(figure.scaled(100,100, QtCore.Qt.AspectRatioMode.KeepAspectRatio))

                self.counter = self.counter + 1
                if self.counter == len(lista):
                    self.counter = 0
            except:
                pass

        QtCore.QTimer.singleShot(self.freq, self._update_allsky)
        

    


    @asyncSlot()
    async def water_button_pressed(self,wylacz=False):
        if wylacz:
            self.water_pump.button.setChecked(False)
        await self.changeWaterState()
        if self.water_pump.button.isChecked():
            #przycisk musi byc wlaczony przez okolo 2 sekundy zeby pompa sie uruchomila
            
            QtCore.QTimer.singleShot(2000, lambda: self.water_button_pressed(wylacz=True))

    async def changeWaterState(self):
        self.water_pump.changeState()



    def send_alarm(self):
        print(self.b_alarm.isChecked())
        if self.b_alarm.isChecked():
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
            self.d.button_close.setText('EXIT')
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
            label.setText('ALARM SENT')
            label.setStyleSheet("QLabel{font-size: 40pt;background-color: white; color:red}")
            button = QPushButton('OK')
            button.clicked.connect(self.c_close_clicked)
            layout = QVBoxLayout()
            layout.addWidget(label)
            layout.addWidget(button)
            self.c.setLayout(layout)
            self.c.exec()

        await self.siren(wyj)
        #if self.b_alarm.isChecked():
        #    QtCore.QTimer.singleShot(2000, self.raise_alarm(mes='',wyj=0))

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

        

            

    def _update_ephem(self):
        lt,sunalt = ephemeris()
        sunalt = str(sunalt)
        text = str(lt)+'\n\nSUN: '+sunalt
        self.label_ephem.setText(text)
        
        QtCore.QTimer.singleShot(1000, self._update_ephem)

    @asyncSlot()
    async def _update_weather(self):
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

            warning = 'Wind:\t'+str(self.wind)+' m/s\n'+'Temp:\t'+str(self.temp)+' C\n'+'Hum:\t'+str(self.hum)+' %\n'+'Press:\t'+str(self.pres)+' hPa\n'
            

            if (float(self.wind) >= 11. and float(self.wind) < 14.) or float(self.hum) > 70:
                self.label_weather.setStyleSheet("background-color : yellow; color: black")
                
            elif float(self.wind) >= 14. or float(self.hum) > 75. or float(self.temp) < 0.:
                self.label_weather.setStyleSheet("background-color : coral; color: black")
                
            else:
               
                self.label_weather.setStyleSheet("background-color : lightgreen; color: black")

            self.label_weather.setText(warning)

    @asyncSlot()
    async def _update_temp(self):
        
        self.roomtemp = '0.0'
        await create_task(self.reader_loop_3(), "temp reader")
        #warning = 'Wind: '+str(self.wind)+' m/s\n'+'Temperature: '+str(self.temp)+' C\n'+'Humidity: '+str(self.hum)+' %\n'+'Wind dir: '+str(self.main_window.winddir)+'\n'
        #self.label.setText(warning)
    

    async def reader_loop_3(self):
        
        msg = Messenger()

        # We want the data from the midnight of yesterday
        

        rdr = msg.get_reader(
            self.temp_subject,
            deliver_policy='last',
        )
        logger.info(f"Subscribed to {self.temp_subject}")

        sample_measurement = {
                "temperature": 10
        }
        try:
            async for data, meta in rdr:
                ts = dt_ensure_datetime(data['ts']).astimezone()
                mes = data["measurements"]
                self.temp = "{:.1f}".format(mes['temperature'])
                self.label_temp.setText(str(self.temp)+ ' C')
        except:
            pass

widget_class = TouchButtonsWBedroom
