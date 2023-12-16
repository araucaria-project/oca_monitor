#!/usr/bin/env python
import os
import asyncio
import subprocess

import requests
#import numpy as np
#import time
#import datetime

from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5.QtGui import QPixmap, QPixmapCache
#QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)
#from PyQt5 import QtWebEngine
#from PyQt5.QtWebKitWidgets import QWebView

from serverish.messenger import Messenger, single_read, get_reader, get_journalreader

import datetime
import time
from matplotlib.pyplot import Circle






#################################################################
#                                                               #
#           TABS CLASSES TO BE DISPLAYED IN OCA_MONITOR         #
#                   Cerro Armazones Observatory                 #
#                      Araucaria Group, 2023                    #
#               contact person pwielgor@camk.edu.pl             #
#                                                               #
#################################################################

###################################################################################################
#----------Tabs will appear only if they have attribute self.display = True, and self.active = True / False
####################################################################################################




#maybe some initial configuration should be here- which tabs should be displayed in batch mode


# ################## TEMPLATE ########################
class Template(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.name = "Template"
        self.display = False    # If to display as a TAB it should be True
        self.active = True
        self.mkUI()

        self.freq = 500
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._do_sthg)
        self.timer.setInterval(self.freq)

        self.counter = 0

    def mkUI(self):

        # Active toggle
        self.b_active = QtWidgets.QCheckBox('ACTIVE ')
        self.b_active.setChecked(True)
        self.b_active.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
        self.b_active.clicked.connect(self._active_clicked)

        # pretty picture
        self.label = QtWidgets.QLabel("Henlol")

        # add buttons and pictures to layout, active toggle buttons is obligatory
        grid = QtWidgets.QGridLayout()
        grid.addWidget(self.b_active, 0, 0)
        grid.addWidget(self.label, 1, 0)
        self.setLayout(grid)

    def _do_sthg(self):
        self.counter = self.counter + 1
        txt = f"Henlol {self.counter}"
        self.label.setText(txt)

    def wakeUp(self):
        self.currImage = 0
        self._do_sthg()
        self.timer.start()

    def sleep(self):
        pass
        #self.timer.stop()

    def _active_clicked(self):
        try:
            self.active = self.b_active.checkState()
        except Exception as e:
            pass

# Weather conditions
class TelescopesGui(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(TelescopesGui, self).__init__(parent)
        self.parent = parent
        self.name = "Telescopes"
        self.active = True
        self.display = True
        self.mkUI()
        self.m = None

        self.parent.add_background_task(self.nats_toi_signal())

    async def nats_toi_signal(self):
        reader = get_journalreader(f'tic.journal.zb08.toi.signal', deliver_policy='last')
        async for data, meta in reader:
            d = data
            r = d.message
            subprocess.run(["aplay", "./sounds/romulan_alarm.wav"])
            print("NATS BELL: ", r)



    def mkUI(self):
        self.freq = 30000
        grid = QtWidgets.QGridLayout()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._readWeather)
        self.timer.setInterval(self.freq)
        self.setLayout(grid)

        self.b_active = QtWidgets.QCheckBox('ACTIVE ')
        self.b_active.setChecked(True)
        self.b_active.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
        self.b_active.clicked.connect(self._active_clicked)

        self.wind_l = QtWidgets.QLabel("Wind:")
        self.wind_e = QtWidgets.QLineEdit()
        self.wind_e.setReadOnly(True)
        self.wind_e.setStyleSheet("background-color: rgb(235,235,235);")


        w = 0

        grid.addWidget(self.wind_l, w, 1)
        grid.addWidget(self.wind_e, w, 2)
        w = w + 1


    def _readWeather(self):
        pass

    def wakeUp(self):
        #self._readWeather()
        self.timer.start()

    def sleep(self):
        pass
        # self.label.setPixmap()
        #self.timer.stop()

    def _active_clicked(self):
        try:
            self.active = self.b_active.checkState()
        except Exception as e:
            pass


# Weather conditions
class WeatherGui(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(WeatherGui, self).__init__(parent)
        self.parent = parent
        self.name = "Weather"
        self.active = True
        self.display = True
        self.mkUI()
        self.m = None

        self.parent.add_background_task(self.nats_weather_loop())

    async def nats_weather_loop(self):

            reader = get_reader('telemetry.weather.davis', deliver_policy='last')
            async for data, meta in reader:
                weather = data['measurements']

                self.wind_e.setText(f"{weather['wind_10min_ms']:.1f} [m/s]")
                self.windDir_e.setText(f"{weather['wind_dir_deg']} [deg]")
                self.temp_e.setText(f"{weather['temperature_C']:.1f} [C]")
                self.hummidity_e.setText(f"{weather['humidity']:.1f} [%]")
                self.pressure_e.setText(f"{weather['pressure_Pa']:.0f} [Pa]")



    def mkUI(self):
        self.freq = 30000
        grid = QtWidgets.QGridLayout()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._readWeather)
        self.timer.setInterval(self.freq)
        self.setLayout(grid)

        self.b_active = QtWidgets.QCheckBox('ACTIVE ')
        self.b_active.setChecked(True)
        self.b_active.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
        self.b_active.clicked.connect(self._active_clicked)

        self.wind_l = QtWidgets.QLabel("Wind:")
        self.wind_e = QtWidgets.QLineEdit()
        self.wind_e.setReadOnly(True)
        self.wind_e.setStyleSheet("background-color: rgb(235,235,235);")
        self.windDir_l = QtWidgets.QLabel("Direction:")
        self.windDir_e = QtWidgets.QLineEdit()
        self.windDir_e.setReadOnly(True)
        self.windDir_e.setStyleSheet("background-color: rgb(235,235,235);")
        self.temp_l = QtWidgets.QLabel("Temp:")
        self.temp_e = QtWidgets.QLineEdit()
        self.temp_e.setReadOnly(True)
        self.temp_e.setStyleSheet("background-color: rgb(235,235,235);")
        self.hummidity_l = QtWidgets.QLabel("Humidity:")
        self.hummidity_e = QtWidgets.QLineEdit()
        self.hummidity_e.setReadOnly(True)
        self.hummidity_e.setStyleSheet("background-color: rgb(235,235,235);")
        self.pressure_l = QtWidgets.QLabel("Pressure:")
        self.pressure_e = QtWidgets.QLineEdit()
        self.pressure_e.setReadOnly(True)
        self.pressure_e.setStyleSheet("background-color: rgb(235,235,235);")

        w = 0
        grid.addWidget(self.b_active, w, 1)
        w = w + 1
        grid.addWidget(self.temp_l, w, 1)
        grid.addWidget(self.temp_e, w, 2)
        w = w + 1
        grid.addWidget(self.hummidity_l, w, 1)
        grid.addWidget(self.hummidity_e, w, 2)
        w = w + 1
        grid.addWidget(self.wind_l, w, 1)
        grid.addWidget(self.wind_e, w, 2)
        w = w + 1
        grid.addWidget(self.windDir_l, w, 1)
        grid.addWidget(self.windDir_e, w, 2)
        w = w + 1
        grid.addWidget(self.pressure_l, w, 1)
        grid.addWidget(self.pressure_e, w, 2)

    def _readWeather(self):
        pass

    def wakeUp(self):
        self._readWeather()
        self.timer.start()

    def sleep(self):
        # self.label.setPixmap()
        self.timer.stop()

    def _active_clicked(self):
        try:
            self.active = self.b_active.checkState()
        except Exception as e:
            pass

#Status of clusters, power production from solar panels
class EnergyGui(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super().__init__()
        self.parent = parent
        self.name = "Energy"
        self.active = True
        self.display = False
        self.mkUI()

    def mkUI(self):
        self.freq = 10000
        grid = QtWidgets.QGridLayout()
        self.timer=QtCore.QTimer()
        self.timer.timeout.connect(self._downloadEnergy)
        self.timer.setInterval(self.freq)
        self.setLayout(grid)
        #self.webview = QWebView()
        #grid.addWidget(self.webview)
        
    #def _readEnergy(self)

    
    def _downloadEnergy(self):
        pass

    def wakeUp(self):
        self._downloadEnergy()
        self.timer.start()

    def sleep(self):
        self.timer.stop()

        


        

        
        

#Weather forecast and satellite image
#from memory_profiler import profile

class ForecastGui(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super().__init__()
        self.parent = parent
        self.name = "Forecast"
        self.active = True
        self.display = False
        self.mkUI()
    #@profile
    def mkUI(self):
        self.freq = 3600000
        self.grid = QtWidgets.QGridLayout()
        #self.webview = QWebView()
        #self.grid.addWidget(self.webview)
        self.timer=QtCore.QTimer()
        self.timer.timeout.connect(self._downloadForecast)
        self.timer.setInterval(self.freq)
        self.setLayout(self.grid)
    #@profile
    
        
        
    def _downloadForecast(self):
        #displaying windy is nice but consume a lot of RAM and I do not know how to lower it...
        #self.webview.load(QtCore.QUrl("https://embed.windy.com/embed2.html?lat=-24.704&lon=-69.883&detailLat=-24.592&detailLon=-70.193&width=1300&height=900&zoom=10&level=surface&overlay=wind&product=ecmwf&menu=&message=&marker=&calendar=now&pressure=&type=map&location=coordinates&detail=true&metricWind=m%2Fs&metricTemp=%C2%B0C&radarRange=-1"))
        #self.webview.show()
        print("TODO")

    #@profile
    def wakeUp(self):
        
        self._downloadForecast()
        self.timer.start()

    #@profile
    def sleep(self):
        self.timer.stop()
        #self.webview.setHtml("")
        #self.webview.stop()
        #self.webview.close()
        #self.webview.history().clear()
               


#Water and maybe some other social stuff like temperature, humidity in the building....
class WaterGui(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super().__init__()
        self.parent = parent
        self.name = "Water"
        self.active = True
        self.display = False
        self.mkUI()

    def mkUI(self):
        self.freq = 500
        grid = QtWidgets.QGridLayout()
        self.timer=QtCore.QTimer()
        self.timer.timeout.connect(self._plot_water)
        self.timer.setInterval(self.freq)
        self.setLayout(grid)
        w=0
        self.label = QtWidgets.QLabel()
        self.blank = QPixmap()
        self.im = QPixmap()
        self.label.setPixmap(self.blank)  
        grid.addWidget(self.label, w, 0)
        self.setLayout(grid)

    
    def _plot_water(self):
        
        try: 
            QPixmapCache.clear()      
           
            self.im.load('/home/piotr/Pobrane/water.png')
            self.label.setPixmap(self.im)
             
        except:
            pass

    def wakeUp(self):
        self._plot_water()
        self.timer.start()

    def sleep(self):
        self.timer.stop()
        self.label.setPixmap(self.blank)
        QPixmapCache.clear()
        #self.im = self.blank


             

#allsky image with positions of telescopes, wind arrow
class AllskyGui(QtWidgets.QWidget):
    def __init__(self,parent=None):
        super().__init__()
        self.parent = parent
        self.name = "Allsky"
        self.active = True
        self.display = False
        self.mkUI()

    def mkUI(self):
        self.currImage = -1
        self.freq = 500
        self.label = QtWidgets.QLabel()
        self.im = QPixmap()
        self.label.setPixmap(self.im.scaled(800,800))
        grid = QtWidgets.QGridLayout()
        w=0
        self.timer=QtCore.QTimer()
        self.timer.timeout.connect(self._plot_allskycam)
        self.timer.setInterval(self.freq)
        grid.addWidget(self.label, w, 0)
        self.setLayout(grid)

    #------ALLSKYCAM MOVIE AND DIFFERENTIAL IMAGE---------
    def _plot_allskycam(self):
        ''''#circle radius = zenith distance in degrees*3.13
                circle60deg = Circle((almukantary_srodek[0], almukantary_srodek[1]), 94, color='r',fill=False)
                circle40deg = Circle((almukantary_srodek[0], almukantary_srodek[1]), 156.5, color='r', linestyle=':', fill=False)
                circle20deg = Circle((almukantary_srodek[0], almukantary_srodek[1]), 210., color='r',fill=False)
                ax3 = self.figure.add_axes([-0.5,0,2,1])
                ax3.add_artist(circle60deg)
                ax3.add_artist(circle40deg)
                ax3.add_artist(circle20deg)
                
                x_arrow,y_arrow,dx_arrow,dy_arrow = self.calc_wind_arrow(almukantary_srodek[0],almukantary_srodek[1],210.,170.)
                wind_arrow = Arrow(x_arrow,y_arrow,dx_arrow,dy_arrow,width=20.,color="pink")
                ax3.add_artist(wind_arrow)

                x_v16,y_v16 = self.calc_tel_pos(almukantary_srodek[0],almukantary_srodek[1],self.v16_az,self.v16_h)

                ax3.plot(x_v16,y_v16,'o',color='g')

                ax3.plot(316-101,210,'+',color='r')
                ax3.text(316-101,408,'N',bbox=dict(facecolor='red', alpha=0.5))
                ax3.text(410,210,'E',bbox=dict(facecolor='red', alpha=0.5))
                ax3.text(12,5,kiedy[0],color='white',fontsize=15)
                ax3.text(310,5,'UT'+kiedy[1],color='white',fontsize=15)

                self.figure.gca().invert_yaxis()
                ax.axes.get_yaxis().set_ticklabels([])
                ax2.axes.get_yaxis().set_ticklabels([])
                ax3.axes.get_yaxis().set_ticklabels([])
                ax.axes.get_xaxis().set_ticklabels([])
                ax2.axes.get_xaxis().set_ticklabels([])
                ax3.axes.get_xaxis().set_ticklabels([])
                ax.axes.get_yaxis().set_ticks([])
                ax2.axes.get_yaxis().set_ticks([])
                ax3.axes.get_yaxis().set_ticks([])
                ax.axes.get_xaxis().set_ticks([])
                ax2.axes.get_xaxis().set_ticks([])
                ax3.axes.get_xaxis().set_ticks([])'''
        
        QPixmapCache.clear()
        # try:
        #     self.images = os.popen('ls ./copy_scripts/GOES_satellite/*600x600.jpg').read().split('\n')[:-1]
        #
        #     self.currImage += 1
        #     if self.currImage == len(self.images):
        #         self.currImage = 0
        #
        #     self.im.load(self.images[self.currImage])
        #     self.label.setPixmap(self.im.scaled(800,800))
        #
        # except:
        #     pass

    def wakeUp(self):
        self.currImage=0
        self._plot_allskycam()
        self.timer.start()


    def sleep(self):
        self.im = QPixmap()
        self.timer.stop()
        self.label.setPixmap(self.im.scaled(800,800))
        QPixmapCache.clear()
        #self.im = self.blank



# class SatelliteGui(QtWidgets.QWidget):
#     def __init__(self, parent=None):
#         super().__init__()
#         self.parent = parent
#         self.name = "Satellite"
#         self.active = True
#         self.display = True
#         self.mkUI()
#
#         self.currImage = -1
#         self.freq = 500
#         self.timer = QtCore.QTimer()
#         self.timer.timeout.connect(self._plot_satellite)
#         self.timer.setInterval(self.freq)
#
#     def mkUI(self):
#
#         # Active toggle
#         self.b_active = QtWidgets.QCheckBox('ACTIVE ')
#         self.b_active.setStyleSheet(
#             "QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
#         self.b_active.clicked.connect(self._active_clicked)
#
#         # pretty picture
#         self.label = QtWidgets.QLabel()
#         self.im = QPixmap()
#         self.label.setPixmap(self.im.scaled(800, 800))
#
#         # add buttons and pictures to layout
#         grid = QtWidgets.QGridLayout()
#         grid.addWidget(self.b_active, 0, 0)
#         grid.addWidget(self.label, 1, 0)
#         self.setLayout(grid)
#
#     def _plot_satellite(self):
#
#         QPixmapCache.clear()
#         try:
#             self.images = os.popen('ls ./copy_scripts/GOES_satellite/*600x600.jpg').read().split('\n')[:-1]
#
#             self.currImage += 1
#             if self.currImage == len(self.images):
#                 self.currImage = 0
#
#             self.im.load(self.images[self.currImage])
#             self.label.setPixmap(self.im.scaled(700, 600))
#
#         except:
#             pass
#
#     def wakeUp(self):
#         self.currImage = 0
#         self._plot_satellite()
#         self.timer.start()
#
#     def sleep(self):
#         self.timer.stop()
#         self.im = QPixmap()
#         self.label.setPixmap(self.im.scaled(800, 800))
#         QPixmapCache.clear()
#         # self.im = self.blank
#         # self.freq = 2147483647
#
#     def _active_clicked(self):
#         try:
#             self.active = self.b_active.checkState()
#         except Exception as e:
#             pass


class SatelliteGui(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.name = "Satellite"
        self.active = True
        self.display = True
        self.mkUI()

        self.freq = 1000*60
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._plot_satellite)
        self.timer.setInterval(self.freq)

        self._plot_satellite()
        self.timer.start()

    def mkUI(self):

        # Active toggle
        self.b_active = QtWidgets.QCheckBox('ACTIVE ')
        self.b_active.setChecked(True)
        self.b_active.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
        self.b_active.clicked.connect(self._active_clicked)

        # pretty picture
        self.label = QtWidgets.QLabel()
        self.im = QPixmap()
        self.label.setPixmap(self.im.scaled(700, 600))

        # add buttons and pictures to layout
        grid = QtWidgets.QGridLayout()
        grid.addWidget(self.b_active, 0, 0)
        grid.addWidget(self.label, 1, 0)
        self.setLayout(grid)

    def _plot_satellite(self):
        QPixmapCache.clear()
        image = self.get_photo()
        if image != None:
            self.im.loadFromData(image)
            self.label.setPixmap(self.im.scaled(700, 600))

    def wakeUp(self):
        pass

    def sleep(self):
        pass
        # self.timer.stop()
        # self.im = QPixmap()
        # self.label.setPixmap(self.im.scaled(700, 600))
        # QPixmapCache.clear()

    def _active_clicked(self):
        try:
            self.active = self.b_active.checkState()
        except Exception as e:
            pass

    def get_photo(self):
        image = None
        url = 'https://cdn.star.nesdis.noaa.gov/GOES16/ABI/SECTOR/ssa/GEOCOLOR/latest.jpg'
        r = requests.get(url)
        if r.status_code == 200:
            image = r.content
        return image

    def edit_images(images, dates):
        sites_dic = {"OCA": [270, 270, "*", "red"], "Antofagasta": [250, 180, "s", "magenta"],
                     "Tal-Tal": [240, 330, "s", "yellow"], "Llullaillaco": [430, 270, "^", "green"],
                     "Copiapo": [250, 530, "s", "cyan"]}

        # with imageio.get_writer('satellite.gif', mode='I',duration=500) as writer:
        # try:
        if True:
            for j, image in enumerate(images):
                mpl.pyplot.figure(figsize=(10, 10))
                im = mpl.pyplot.imread(image)
                mpl.pyplot.clf()

                mpl.pyplot.imshow(im[1000:1600, 2100:2700])
                for i, site in enumerate(sites_dic):
                    (x, y, marker, color) = sites_dic[site]
                    mpl.pyplot.plot(x, y, marker, color=color, markersize=10)

                    mpl.pyplot.text(x - 70, y, site, c=color)
                mpl.pyplot.text(20, 580, 'UT: ' + dates[j], c='red', fontsize='x-large')
                mpl.pyplot.text(500, 580, 'GOES-16 satellite', c='yellow')

                frame = mpl.pyplot.gca()
                frame.axes.xaxis.set_ticklabels([])
                frame.axes.yaxis.set_ticklabels([])
                frame.axes.get_xaxis().set_ticks([])
                frame.axes.get_yaxis().set_ticks([])

                mpl.pyplot.tight_layout()
                mpl.pyplot.savefig(image.replace('7200x4320.jpg', '600x600.jpg', 1))

