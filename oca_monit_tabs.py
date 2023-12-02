#!/usr/bin/env python
import os
#import numpy as np
#import time
#import datetime
from PyQt5 import QtCore
from PyQt5 import QtWidgets
from PyQt5.QtGui import QPixmap, QPixmapCache
#QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)
#from PyQt5 import QtWebEngine
#from PyQt5.QtWebKitWidgets import QWebView





#################################################################
#                                                               #
#           TABS CLASSES TO BE DISPLAYED IN OCA_MONITOR         #
#                   Cerro Armazones Observatory                 #
#                      Araucaria Group, 2023                    #
#               contact person pwielgor@camk.edu.pl             #
#                                                               #
#################################################################

#Status of clusters, power production from solar panels
class EnergyGui(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.name = "Energy"
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
        print("TODO")

    def wakeUp(self):
        self._downloadEnergy()
        self.timer.start()

    def sleep(self):
        self.timer.stop()

        

#Weather conditions
class WeatherGui(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.name = "Weather" 
        self.mkUI()

    def mkUI(self):
        self.freq = 30000
        grid = QtWidgets.QGridLayout()
        self.timer=QtCore.QTimer()
        self.timer.timeout.connect(self._readWeather)
        self.timer.setInterval(self.freq)
        self.setLayout(grid)

    def _readWeather(self):
        print("TODO")
    
    def wakeUp(self):
        self._readWeather()
        self.timer.start()

    def sleep(self):
        #self.label.setPixmap()
        self.timer.stop()
        

        

        
        

#Weather forecast and satellite image
#from memory_profiler import profile

class ForecastGui(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.name = "Forecast"  
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
    def __init__(self):
        super().__init__()
        self.name = "Water"
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
    def __init__(self):
        super().__init__()
        self.name = "Allsky"
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
        try:    
            self.images = os.popen('ls ./copy_scripts/GOES_satellite/*600x600.jpg').read().split('\n')[:-1]
            
            self.currImage += 1
            if self.currImage == len(self.images):
                self.currImage = 0

            self.im.load(self.images[self.currImage])
            self.label.setPixmap(self.im.scaled(800,800))

        except:
            pass

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
        

class SatelliteGui(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.name = "Satellite"
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
        self.timer.timeout.connect(self._plot_satellite)
        self.timer.setInterval(self.freq)
        grid.addWidget(self.label, w, 0)
        self.setLayout(grid)

    def _plot_satellite(self):
        
        QPixmapCache.clear()
        try:     
            self.images = os.popen('ls ./copy_scripts/GOES_satellite/*600x600.jpg').read().split('\n')[:-1]
            
            self.currImage += 1
            if self.currImage == len(self.images):
                self.currImage = 0

            self.im.load(self.images[self.currImage])
            self.label.setPixmap(self.im.scaled(800,800))
            
        except:
            pass

    def wakeUp(self):
        self.currImage=0
        self._plot_satellite()
        self.timer.start()

    def sleep(self):
        self.timer.stop()
        self.im = QPixmap()
        self.label.setPixmap(self.im.scaled(800,800))
        QPixmapCache.clear()
        #self.im = self.blank
        #self.freq = 2147483647
   

############################################################################
#----------Add any new tab to the list below before running oca_monit.py!  #
############################################################################

tabsList = [AllskyGui(),SatelliteGui(),WeatherGui(),ForecastGui(),WaterGui(),EnergyGui()]

#maybe some initial configuration should be here- which tabs should be displayed in batch mode
