#!/usr/bin/env python

#################################################################
#                                                               #
#                       OCA_MONITOR  GUI                        #
#                   Cerro Armazones Observatory                 #
#                      Araucaria Group, 2023                    #
#               contact person pwielgor@camk.edu.pl             #
#                                                               #
#################################################################


#import json

import sys, ephem, os
#import numpy as np
import time
import datetime
from astropy.time import Time as czas_astro
from PyQt5 import QtGui,QtCore
from PyQt5 import QtWidgets
#QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)
#from PyQt5.QtWebEngineWidgets import QWebEngineView
#from PyQt5.QtWebKitWidgets import QWebView
#import math


#import oca_monit_telescopes

try:
    import pygame
    pygame_kontrolka = 0
except:
    print("install pygame")
    pygame_kontrolka = 1

global source_path
source_path = '/home/observer/Dropbox/OCA_WARNING_SYSTEM/'
if not os.access(source_path,os.R_OK):
    source_path = './'
global images_store_path


global sounds
sounds = 'ON'

global notify
notify = ''

global date


#my smartphone pushover app push notification command:     curl -s --form-string 'token=adcte9qacd6jhmhch8dyw4e4ykuod2' --form-string 'user=uacjyhka7d75k5i3gmfhdg9pc2vqyf' --form-string 'message=OWS' https://api.pushover.net/1/messages.json
            

#-------------------------------
#-----VOICE NOTIFICATION--------
#-------------------------------

def send_notification(message):
        global notify
        if len(notify) == 0:
                command = "curl -s --form-string 'token=adcte9qacd6jhmhch8dyw4e4ykuod2' --form-string 'user=uacjyhka7d75k5i3gmfhdg9pc2vqyf' --form-string 'message=OWS:blebleble' https://api.pushover.net/1/messages.json"

        else:
                command = notify

        os.system(command.replace('blebleble',message,1))
        return 1

#++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++EPHEMERIS TO DISPLAY+++++++++++++++++
#++++++++++++++++++++++++++++++++++++++++++++++++++++

def sun():
    arm=ephem.Observer()
    arm.lon=str(-70.183515)
    arm.lat=str(-24.58917)
    arm.elev=2800
    ut = time.strftime('%Y/%m/%d %H:%M:%S',time.gmtime() )
    arm.date = ut
    sun = ephem.Sun()
    sun.compute(arm)
    return int(str(sun.alt).split(':')[0])

#def moon(date):

def ephemeris():
    arm=ephem.Observer()
    arm.lon=str(-70.183515)
    arm.lat=str(-24.58917)
    arm.elev=2800
    global date
    date = time.strftime('%Y%m%d',time.gmtime() )
    ut = time.strftime('%Y/%m/%d %H:%M:%S',time.gmtime() )
    t = czas_astro([ut.replace('/','-',2).replace(' ','T',1)])
    jd = str(t.jd[0])[:12]
    lt = time.strftime('%Y/%m/%d %H:%M:%S',time.localtime() )
    arm.date = ut
    sunset=str(arm.next_setting(ephem.Sun()))
    sunrise=str(arm.next_rising(ephem.Sun()))
    sun = ephem.Sun()
    moon = ephem.Moon()
    sun.compute(arm)
    moon.compute(arm)
    lst = arm.sidereal_time()
    text = 'UT:\t\t\t'+ut+'\nLOCAL TIME:\t\t'+lt+'\nLOCAL SIDEREAL TIME:\t'+str(lst)+'\nJD:\t\t\t'+jd+'\nNEXT SUNSET(UT):\t'+sunset+'\nNEXT SUNRISE(UT):\t'+sunrise+'\nSUN ALTITUDE:\t\t'+str(sun.alt)
    return text

def dec2deg(angle):
    d=int(angle)
    diff_angle_d = angle-float(d)
    m=int(diff_angle_d*60.)
    s=int(((diff_angle_d*60.)-float(m))*60.)
    return str(d)+':'+str(m)+':'+str(s)

def dec2h(angle):
    angle = angle*12./180.
    d=int(angle)
    diff_angle_d = angle-float(d)
    m=int(diff_angle_d*60.)
    s=int(((diff_angle_d*60.)-float(m))*60.)
    return str(d)+':'+str(m)+':'+str(s)

def deg2dec(angle):
    if angle[0] == '-':
        return (float(str(angle).split(':')[0])-float(str(angle).split(':')[1])/60.-float(str(angle).split(':')[2])/3600.)
    else:
        return (float(str(angle).split(':')[0])+float(str(angle).split(':')[1])/60.+float(str(angle).split(':')[2])/3600.)
        
        

def calc_star_coo(ra,dec):
    if ra != -99 and dec != -99:
        arm=ephem.Observer()
        arm.lon=str(-70.183515)
        arm.lat=str(-24.58917)
        arm.elev=2800
        arm.date = time.strftime('%Y/%m/%d %H:%M:%S',time.gmtime() )
        star = ephem.FixedBody()
        star._ra=ephem.degrees(str(ra))
        star._dec=ephem.degrees(str(dec))
        star._epoch = ephem.J2000
        star.compute(arm)
        return deg2dec(str(star.az)), deg2dec(str(star.alt))
    else:
        return ra,dec
    

'''def running_mean_convolution(wind, kernel_size):
    """smart but unstable on ends (Mikolaj)"""
    if len(wind) > kernel_size:
        kernel = np.full(shape=(kernel_size,), fill_value=1.0/kernel_size)
        return np.convolve(wind, kernel, mode='same')
    else:  # data shorter than kernel - use constant mean
        return np.full_like(wind, np.mean(wind))

def running_mean_cumsum(wind, kernel_size):
    """Fast and preserve ends (Mikolaj)"""
    cumsum = np.cumsum(np.insert(wind, 0, np.full(kernel_size, wind[0] if len(wind)>0 else 0)))
    return (cumsum[kernel_size:] - cumsum[:-kernel_size]) / float(kernel_size)


running_mean = running_mean_cumsum
#running_mean = running_mean_convolution'''

#++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++GUI++++++++++++++++++++++
#++++++++++++++++++++++++++++++++++++++++++++++++++


    

        

class MonitGUI(QtWidgets.QWidget):
    


    def __init__(self, parent=None):
        super(MonitGUI,self).__init__(parent)

        self.initUI()

    def initUI(self):
        

        import oca_monit_tabs as tabs
        import oca_monit_telescopes as telescopes

        
        self.freq = 1000
        #--------------------EPMHEMERIS-------------------------------------

        self.ephemeris= ephemeris()
        self.czas=QtWidgets.QLabel(str(self.ephemeris),self)
        self.czas.setStyleSheet('background-color: white')
        self.czas.resize(150,300)
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.updateEphemeris)
        self.timer.setInterval(self.freq)
        self.timer.start()


        #-------------------TELESCOPES---------------------------------------


         
        #self.warningIrisEdit=QtWidgets.QLabel(str(''),self)
        #self.warningIrisEdit.setAlignment(QtCore.Qt.AlignCenter)
        #if 'CHECK' in warningIris:
        #    self.warningIrisEdit.setStyleSheet('background-color: red')


        #--------------GUI SETTINGS----------------------------------------

        
        self.b_play = QtWidgets.QPushButton(self)
        self.b_play.setText("PLAY")
        self.b_play.resize(50,32)
        self.b_play.clicked.connect(self.b_play_clicked)

        self.b_stop = QtWidgets.QPushButton(self)
        self.b_stop.setText("STOP")
        self.b_stop.resize(50,32)
        self.b_stop.clicked.connect(self.b_stop_clicked)

        self.b_faster = QtWidgets.QPushButton(self)
        self.b_faster.setText("+")
        self.b_faster.resize(30,32)
        self.b_faster.clicked.connect(self.b_faster_clicked)

        self.freq_tabs_field=QtWidgets.QLabel('10',self)
        self.freq_tabs_field.setStyleSheet('background-color: white')
        #self.freq_tabs_field.setText('10')
        self.freq_tabs_field.resize(1,1)

        self.b_slower = QtWidgets.QPushButton(self)
        self.b_slower.setText("-")
        self.b_slower.resize(30,32)
        self.b_slower.clicked.connect(self.b_slower_clicked)

        self.b_enable = QtWidgets.QCheckBox('ENABLE ABORT BUTTONS')
        self.b_enable.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.b_sound = QtWidgets.QCheckBox('ENABLE SOUND WARNING')
        self.b_sound.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.b_enable_warnings = QtWidgets.QCheckBox('ENABLE WARNINGS')
        self.b_enable_warnings.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.b_abort = QtWidgets.QPushButton(self)#abort button
        self.b_abort.setStyleSheet("background-color : red")
        self.b_abort.setText("ABORT OBSERVATIONS")
        self.b_abort.setFixedSize(300, 100)

        self.b_abort_telescopes = []
        for telescope in telescopes.telescopesList:
            self.b_abort_telescopes.append(QtWidgets.QPushButton(self))#abort button
            self.b_abort_telescopes[-1].setStyleSheet("background-color : orange")
            self.b_abort_telescopes[-1].setText('ABORT '+telescope.name)
            self.b_abort_telescopes[-1].setFixedSize(300, 50)


        
        self.b_exit = QtWidgets.QPushButton(self)#abort button
        self.b_exit.setText("EXIT")
        self.b_exit.resize(100,32)
        self.b_exit.clicked.connect(self.b_exit_clicked)

        self.tabs = []
        self.tabWidget=QtWidgets.QTabWidget()
        for tab in tabs.tabsList:
            self.tabs.append(tab)
        self.tabs_buttons = []
        for tab in self.tabs:
            self.tabWidget.addTab(tab,tab.name)
            self.tabs_buttons.append(QtWidgets.QCheckBox(tab.name))
            self.tabs_buttons[-1].setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
            self.tabs_buttons[-1].setChecked(True)
        
        self.tabs[0].wakeUp()
        self.tabWidget.tabBarClicked.connect(self.tab_change)
        
        self.hbox_main=QtWidgets.QHBoxLayout()#main
        
        self.hbox_main.addWidget(self.tabWidget)
        self.vbox_right= QtWidgets.QVBoxLayout()
        self.hbox_tab_buttons = QtWidgets.QHBoxLayout()
        self.vbox_tab_buttons_left = QtWidgets.QVBoxLayout()
        self.vbox_tab_buttons_right = QtWidgets.QVBoxLayout()

        
        for i,button in enumerate(self.tabs_buttons): 
            if i < int(len(self.tabs_buttons)/2):
                self.vbox_tab_buttons_left.addWidget(button)
            else:
                self.vbox_tab_buttons_right.addWidget(button)

        self.hbox_tab_buttons.addLayout(self.vbox_tab_buttons_left)
        self.hbox_tab_buttons.addLayout(self.vbox_tab_buttons_right)
        self.vbox_right.addLayout(self.hbox_tab_buttons)
        self.hbox_buttons_play = QtWidgets.QHBoxLayout()
        self.hbox_buttons_play.addWidget(self.b_play)
        self.hbox_buttons_play.addWidget(self.b_stop)
        self.vbox_right.addLayout(self.hbox_buttons_play)
        
        self.hbox_buttons_freq = QtWidgets.QHBoxLayout()
        self.hbox_buttons_freq.addWidget(self.b_slower)
        self.hbox_buttons_freq.addWidget(self.freq_tabs_field)
        self.hbox_buttons_freq.addWidget(self.b_faster)
        self.vbox_right.addLayout(self.hbox_buttons_freq)
        self.vbox_right.addWidget(self.czas)

        self.vbox_right.addWidget(self.b_enable_warnings)
        self.vbox_right.addWidget(self.b_sound)
        self.vbox_right.addWidget(self.b_enable)
        self.vbox_right.addWidget(self.b_abort)
        for telescope_button in self.b_abort_telescopes:
            self.vbox_right.addWidget(telescope_button)

        
        self.vbox_right.addWidget(self.b_exit)
        
    
        self.hbox_main.addLayout(self.vbox_right)
        
      
        
        
        #----gui settings-------
        self.setLayout(self.hbox_main)
        #self.setWindowState(QtCore.Qt.WindowMaximized)
        #self.showFullScreen()
        self.setGeometry(500,300,1000,800)
        self.setWindowTitle("OCA MONITOR")
        self.show()

    def tab_change(self,index):
        print('bleble')
        for i, tab in enumerate(self.tabs):
            
            if i == index:
                tab.wakeUp()
            else:
                tab.sleep()

        

    def moveTab(self):
        
        curr_index = self.tabWidget.currentIndex()
        if curr_index < len(self.tabs)-1:
            i = curr_index+1
        else:
            i = 0
        isSomethingChecked = 0
        for j in range(len(self.tabs)):
            if self.tabs_buttons[j].isChecked():
                isSomethingChecked = 1

        if isSomethingChecked:
            while not self.tabs_buttons[i].isChecked():
                i = i+1
                if i == len(self.tabs):
                    i = 0
        else:
                i = 0  
                    
        self.tabWidget.setCurrentIndex(i)
        self.tab_change(index=i)

    def b_play_clicked(self):
        self.moveTab()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.moveTab)
        self.timer.start(int(self.freq_tabs_field.text())*1000)
        

    def b_stop_clicked(self):
        self.timer.stop()

    def b_faster_clicked(self):
        curr_index = self.tabWidget.currentIndex()
        if curr_index < len(self.tabs)-1:
            i = curr_index+1
        else:
            i = 0
        while not self.tabs_buttons[i].isChecked() and i != curr_index:
            i = i+1
            if i == len(self.tabs):
                i = 0
           
                
        self.tabWidget.setCurrentIndex(i)
        QtCore.QTimer.singleShot(10000, lambda: self.b_play_clicked())

    def b_slower_clicked(self):
        curr_index = self.tabWidget.currentIndex()
        if curr_index < len(self.tabs)-1:
            i = curr_index+1
        else:
            i = 0
        while not self.tabs_buttons[i].isChecked() and i != curr_index:
            i = i+1
            if i == len(self.tabs):
                i = 0
           
                
        self.tabWidget.setCurrentIndex(i)
        QtCore.QTimer.singleShot(10000, lambda: self.b_play_clicked())

    def b_exit_clicked(self):
        sys.exit()

    '''#-------------BUTTONS--------------
    #telescopes
    def b1_clicked(self):#iris warning on/off
        if MonitGUI.run_warnings_iris == 1:
            MonitGUI.run_warnings_iris = 0
            self.b1.setText("IRIS AUDIT OFF")
        else:
            MonitGUI.run_warnings_iris = 1
            self.b1.setText("IRIS AUDIT ON")'''

    

    
            


    def b21_clicked(self):
        self.dialog.show()

    def b22_clicked(self):
        global sounds
        
        if sounds == 'OFF':
            sounds = 'ON'
            self.b22.setText("SOUND IS ON")

        else:
            sounds = 'OFF'
            self.b22.setText("SOUND IS OFF")
        
    #-----------ephemeris text---------
    def updateEphemeris(self):
        # change the following line to retrieve the new voltage from the device
        self.ephemeris = ephemeris()
        self.czas.setText(str(self.ephemeris))
   


#------------------------------------------------------------
#--------------------------MAIN------------------------------
#------------------------------------------------------------



def main():
    app=QtWidgets.QApplication(sys.argv)

    ex=MonitGUI()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
          
          
          
          
          
          
          
