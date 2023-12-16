#!/usr/bin/env python

#################################################################
#                                                               #
#                       OCA_MONITOR  GUI                        #
#                   Cerro Armazones Observatory                 #
#                      Araucaria Group, 2023                    #
#               contact person pwielgor@camk.edu.pl             #
#                                                               #
#################################################################

import inspect
import sys, ephem, os
import time
import datetime
from astropy.time import Time as czas_astro
from PyQt5 import QtGui,QtCore
from PyQt5 import QtWidgets

import asyncio
import functools
import qasync

from serverish.messenger import Messenger, get_reader

from cale_to_zlo import CaleToZlo, MetaCaleToZlo

import oca_monit_telescopes as telescopes
import oca_monit_tabs as tabs




#QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts, True)
#from PyQt5.QtWebEngineWidgets import QWebEngineView
#from PyQt5.QtWebKitWidgets import QWebView
#import math


try:
    import pygame
    pygame_kontrolka = 0
except:
    #print("install pygame")
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


    

        

# class MonitGUI(QtWidgets.QWidget):
#
#
#
#     def __init__(self, parent=None):
#         super(MonitGUI,self).__init__(parent)
#
#         self.initUI()
#
#     def initUI(self):
#
#
#         #import oca_monit_tabs as tabs
#         import oca_monit_telescopes as telescopes
#
#
#         self.freq = 1000
#         #--------------------EPMHEMERIS-------------------------------------
#
#         self.ephemeris= ephemeris()
#         self.czas=QtWidgets.QLabel(str(self.ephemeris),self)
#         self.czas.setStyleSheet('background-color: white')
#         self.czas.resize(150,300)
#         self.timer = QtCore.QTimer()
#         self.timer.timeout.connect(self.updateEphemeris)
#         self.timer.setInterval(self.freq)
#         self.timer.start()
#
#
#         #-------------------TELESCOPES---------------------------------------
#
#
#
#         #self.warningIrisEdit=QtWidgets.QLabel(str(''),self)
#         #self.warningIrisEdit.setAlignment(QtCore.Qt.AlignCenter)
#         #if 'CHECK' in warningIris:
#         #    self.warningIrisEdit.setStyleSheet('background-color: red')
#
#
#         #--------------GUI SETTINGS----------------------------------------
#
#
#         self.b_play = QtWidgets.QPushButton(self)
#         self.b_play.setText("PLAY")
#         self.b_play.resize(50,32)
#         self.b_play.clicked.connect(self.b_play_clicked)
#
#         self.b_stop = QtWidgets.QPushButton(self)
#         self.b_stop.setText("STOP")
#         self.b_stop.resize(50,32)
#         self.b_stop.clicked.connect(self.b_stop_clicked)
#
#         self.b_faster = QtWidgets.QPushButton(self)
#         self.b_faster.setText("+")
#         self.b_faster.resize(30,32)
#         self.b_faster.clicked.connect(self.b_faster_clicked)
#
#         self.freq_tabs_field=QtWidgets.QLabel('10',self)
#         self.freq_tabs_field.setStyleSheet('background-color: white')
#         #self.freq_tabs_field.setText('10')
#         self.freq_tabs_field.resize(1,1)
#
#         self.b_slower = QtWidgets.QPushButton(self)
#         self.b_slower.setText("-")
#         self.b_slower.resize(30,32)
#         self.b_slower.clicked.connect(self.b_slower_clicked)
#
#         self.b_enable = QtWidgets.QCheckBox('ENABLE ABORT BUTTONS')
#         self.b_enable.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
#
#         self.b_sound = QtWidgets.QCheckBox('ENABLE SOUND WARNING')
#         self.b_sound.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
#
#         self.b_enable_warnings = QtWidgets.QCheckBox('ENABLE WARNINGS')
#         self.b_enable_warnings.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
#
#         self.b_abort = QtWidgets.QPushButton(self)#abort button
#         self.b_abort.setStyleSheet("background-color : red")
#         self.b_abort.setText("ABORT OBSERVATIONS")
#         self.b_abort.setFixedSize(300, 100)
#
#         self.b_abort_telescopes = []
#         for telescope in telescopes.telescopesList:
#             self.b_abort_telescopes.append(QtWidgets.QPushButton(self))#abort button
#             self.b_abort_telescopes[-1].setStyleSheet("background-color : orange")
#             self.b_abort_telescopes[-1].setText('ABORT '+telescope.name)
#             self.b_abort_telescopes[-1].setFixedSize(300, 50)
#
#
#
#         self.b_exit = QtWidgets.QPushButton(self)#abort button
#         self.b_exit.setText("EXIT")
#         self.b_exit.resize(100,32)
#         self.b_exit.clicked.connect(self.b_exit_clicked)
#
#         self.tabs = []
#         self.tabWidget=QtWidgets.QTabWidget()
#         for tab in tabs.tabsList:
#             self.tabs.append(tab)
#         self.tabs_buttons = []
#         for tab in self.tabs:
#             self.tabWidget.addTab(tab,tab.name)
#             self.tabs_buttons.append(QtWidgets.QCheckBox(tab.name))
#             self.tabs_buttons[-1].setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
#             self.tabs_buttons[-1].setChecked(True)
#
#         self.tabs[0].wakeUp()
#         self.tabWidget.tabBarClicked.connect(self.tab_change)
#
#         self.hbox_main=QtWidgets.QHBoxLayout()#main
#
#         self.hbox_main.addWidget(self.tabWidget)
#         self.vbox_right= QtWidgets.QVBoxLayout()
#         self.hbox_tab_buttons = QtWidgets.QHBoxLayout()
#         self.vbox_tab_buttons_left = QtWidgets.QVBoxLayout()
#         self.vbox_tab_buttons_right = QtWidgets.QVBoxLayout()
#
#
#         for i,button in enumerate(self.tabs_buttons):
#             if i < int(len(self.tabs_buttons)/2):
#                 self.vbox_tab_buttons_left.addWidget(button)
#             else:
#                 self.vbox_tab_buttons_right.addWidget(button)
#
#         self.hbox_tab_buttons.addLayout(self.vbox_tab_buttons_left)
#         self.hbox_tab_buttons.addLayout(self.vbox_tab_buttons_right)
#         self.vbox_right.addLayout(self.hbox_tab_buttons)
#         self.hbox_buttons_play = QtWidgets.QHBoxLayout()
#         self.hbox_buttons_play.addWidget(self.b_play)
#         self.hbox_buttons_play.addWidget(self.b_stop)
#         self.vbox_right.addLayout(self.hbox_buttons_play)
#
#         self.hbox_buttons_freq = QtWidgets.QHBoxLayout()
#         self.hbox_buttons_freq.addWidget(self.b_slower)
#         self.hbox_buttons_freq.addWidget(self.freq_tabs_field)
#         self.hbox_buttons_freq.addWidget(self.b_faster)
#         self.vbox_right.addLayout(self.hbox_buttons_freq)
#         self.vbox_right.addWidget(self.czas)
#
#         self.vbox_right.addWidget(self.b_enable_warnings)
#         self.vbox_right.addWidget(self.b_sound)
#         self.vbox_right.addWidget(self.b_enable)
#         self.vbox_right.addWidget(self.b_abort)
#         for telescope_button in self.b_abort_telescopes:
#             self.vbox_right.addWidget(telescope_button)
#
#
#         self.vbox_right.addWidget(self.b_exit)
#
#
#         self.hbox_main.addLayout(self.vbox_right)
#
#
#
#
#         #----gui settings-------
#         self.setLayout(self.hbox_main)
#         #self.setWindowState(QtCore.Qt.WindowMaximized)
#         #self.showFullScreen()
#         self.setGeometry(500,300,1000,800)
#         self.setWindowTitle("OCA MONITOR")
#         self.show()
#
#     def tab_change(self,index):
#         print('bleble')
#         for i, tab in enumerate(self.tabs):
#
#             if i == index:
#                 tab.wakeUp()
#             else:
#                 tab.sleep()
#
#
#
#     def moveTab(self):
#
#         curr_index = self.tabWidget.currentIndex()
#         if curr_index < len(self.tabs)-1:
#             i = curr_index+1
#         else:
#             i = 0
#         isSomethingChecked = 0
#         for j in range(len(self.tabs)):
#             if self.tabs_buttons[j].isChecked():
#                 isSomethingChecked = 1
#
#         if isSomethingChecked:
#             while not self.tabs_buttons[i].isChecked():
#                 i = i+1
#                 if i == len(self.tabs):
#                     i = 0
#         else:
#                 i = 0
#
#         self.tabWidget.setCurrentIndex(i)
#         self.tab_change(index=i)
#
#     def b_play_clicked(self):
#         self.moveTab()
#         self.timer = QtCore.QTimer()
#         self.timer.timeout.connect(self.moveTab)
#         self.timer.start(int(self.freq_tabs_field.text())*1000)
#
#
#     def b_stop_clicked(self):
#         self.timer.stop()
#
#
#     def b_faster_clicked(self):
#         curr_index = self.tabWidget.currentIndex()
#         if curr_index < len(self.tabs) - 1:
#             i = curr_index + 1
#         else:
#             i = 0
#         # not self.tabs_buttons[i].isChecked() and
#         while i != curr_index:
#             i = i + 1
#             if i == len(self.tabs):
#                 i = 0
#
#         self.tabWidget.setCurrentIndex(i)
#         QtCore.QTimer.singleShot(10000, lambda: self.b_play_clicked())
#
#     def b_slower_clicked(self):
#         curr_index = self.tabWidget.currentIndex()
#         if curr_index < len(self.tabs) - 1:
#             i = curr_index + 1
#         else:
#             i = 0
#         # not self.tabs_buttons[i].isChecked() and
#         while  i != curr_index:
#             i = i + 1
#             if i == len(self.tabs):
#                 i = 0
#
#         self.tabWidget.setCurrentIndex(i)
#         QtCore.QTimer.singleShot(10000, lambda: self.b_play_clicked())
#
#
#     def b_exit_clicked(self):
#         sys.exit()
#
#     '''#-------------BUTTONS--------------
#     #telescopes
#     def b1_clicked(self):#iris warning on/off
#         if MonitGUI.run_warnings_iris == 1:
#             MonitGUI.run_warnings_iris = 0
#             self.b1.setText("IRIS AUDIT OFF")
#         else:
#             MonitGUI.run_warnings_iris = 1
#             self.b1.setText("IRIS AUDIT ON")'''
#
#
#     def b21_clicked(self):
#         self.dialog.show()
#
#     def b22_clicked(self):
#         global sounds
#
#         if sounds == 'OFF':
#             sounds = 'ON'
#             self.b22.setText("SOUND IS ON")
#
#         else:
#             sounds = 'OFF'
#             self.b22.setText("SOUND IS OFF")
#
#     #-----------ephemeris text---------
#     def updateEphemeris(self):
#         # change the following line to retrieve the new voltage from the device
#         self.ephemeris = ephemeris()
#         self.czas.setText(str(self.ephemeris))
#

class MonitGUI2(QtWidgets.QWidget,CaleToZlo, metaclass=MetaCaleToZlo):
    def __init__(self, loop: qasync.QEventLoop = None, parent=None):
        super().__init__(loop=loop)
        self.loop = loop

        self.sound = True

        self.tab_window_size=[600,700]
        self.resize(self.tab_window_size[0]+74,self.tab_window_size[1]+32)
        self.setWindowTitle("OCA MONITOR")
        self.mkUI()

    def mkUI(self):

        self.b_enable = QtWidgets.QCheckBox('ENABLE ABORT BUTTONS')
        self.b_enable.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.b_sound = QtWidgets.QCheckBox('ENABLE SOUND WARNING')
        self.b_sound.setChecked(True)
        self.b_sound.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")
        self.b_sound.clicked.connect(self.enable_sound)

        self.b_enable_warnings = QtWidgets.QCheckBox('ENABLE WARNINGS')
        self.b_enable_warnings.setStyleSheet("QCheckBox::indicator:checked {image: url(./Icons/SwitchOn.png)}::indicator:unchecked {image: url(./Icons/SwitchOff.png)}")

        self.b_abort = QtWidgets.QPushButton("ABORT \nOBSERVATIONS")  # abort button
        self.b_abort.setStyleSheet("background-color : red")
        self.b_abort.setFixedSize(150, 150)

        self.b_abort_telescopes = []
        for telescope in telescopes.telescopesList:
            self.b_abort_telescopes.append(QtWidgets.QPushButton(self))  # abort button
            self.b_abort_telescopes[-1].setStyleSheet("background-color : orange")
            self.b_abort_telescopes[-1].setText('ABORT ' + telescope.name)
            self.b_abort_telescopes[-1].setFixedSize(150, 45)

        self.close_p = QtWidgets.QPushButton("Close")#abort button
        self.close_p.setFixedSize(450,50)
        self.close_p.clicked.connect(self.close)

        self.tab_grid = QtWidgets.QGridLayout()
        self.tab_grid.addWidget(TabBox(parent=self),0,0)

        self.buttons_grid = QtWidgets.QGridLayout()

        self.buttons_grid.addWidget(self.b_enable, 0, 0)
        self.buttons_grid.addWidget(self.b_sound, 1, 0)
        self.buttons_grid.addWidget(self.b_enable_warnings, 2, 0)

        self.buttons_grid.addWidget(self.b_abort,0,1,3,1)

        c = 2
        w = 0
        for i,telescope_button in enumerate(self.b_abort_telescopes):
            self.buttons_grid.addWidget(telescope_button,w,c)
            w = w + 1
            if w == 3: w,c = 0,c+1


        self.buttons_grid.addWidget(self.close_p,4,1,1,4)


        self.layout = QtWidgets.QVBoxLayout()
        self.layout.addLayout(self.tab_grid)
        self.layout.addLayout(self.buttons_grid)

        self.setLayout(self.layout)
        self.resizeEvent = self.on_resize
        self.show()

    def updateUI(self):
        self.resizeEvent = self.block_resizeEvent
        self.width = self.size().width()
        self.height = self.size().height()
        width_box_count = ((self.size().width() - 74 ) // self.tab_window_size[0] )
        height_box_count = ((self.size().height() - 31 )  // self.tab_window_size[1] )
        while self.tab_grid.count():
            w = self.tab_grid.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()

        for w in range(width_box_count):
            for h in range(height_box_count):
                if w<4 and h<4:
                    self.tab_grid.addWidget(TabBox(parent=self),h,w)

        self.resizeEvent = self.on_resize

    def block_resizeEvent(self,tmp):
        pass

    def on_resize(self,tmp):
        self.updateUI()

    async def on_start_app(self):
        await self.run_background_tasks()

    def enable_sound(self):
        if self.b_sound.checkState():
            self.sound = True
        else:
            self.sound = False


class TabBox(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.parent = parent
        self.setFixedSize(self.parent.tab_window_size[0], self.parent.tab_window_size[1])
        self.tabsList = []
        for tab,obj in inspect.getmembers(sys.modules[tabs.__name__]):
            if inspect.isclass(obj):
                try:
                    instance = obj(parent=self.parent)
                    if hasattr(instance, 'display') and hasattr(instance, 'active'):
                        if instance.display:
                            self.tabsList.append(instance)
                except TypeError:
                    pass
        self.initUI()


    def tab_change(self, index):
        for i, tab in enumerate(self.tabs):
            if i == index:
                if tab.active:
                    tab.wakeUp()
                else:
                    self.moveTab()
            else:
                tab.sleep()

    def moveTab(self):
        curr_index = self.tabWidget.currentIndex()
        i = curr_index + 1
        if curr_index < len(self.tabs) - 1:
            i = curr_index + 1
        else:
            i = 0
        self.tabWidget.setCurrentIndex(i)
        self.tab_change(index=i)


    def b_play_clicked(self):
        self.moveTab()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.moveTab)
        self.timer.start(int(self.freq_tabs_field.text()) * 1000)

    def b_stop_clicked(self):
        self.timer.stop()

    def b_faster_clicked(self):
        try:
            t = int(self.freq_tabs_field.text())
            t = t - 1
            if t == 0:
                t = 1
            self.freq_tabs_field.setText(str(t))
            self.timer.setInterval(t*1000)
        except Exception as e:
            print(f"Exception b_faster_clicked: {e}")

    def b_slower_clicked(self):
        try:
            t = int(self.freq_tabs_field.text())
            t = t + 1
            self.freq_tabs_field.setText(str(t))
            self.timer.setInterval(t*1000)
        except Exception as e:
            print(f"Exception b_faster_clicked: {e}")

    def initUI(self):
        QtWidgets.QVBoxLayout()

        self.b_play = QtWidgets.QPushButton(self)
        self.b_play.setText("\u25B6 PLAY")
        self.b_play.resize(50,32)
        self.b_play.clicked.connect(self.b_play_clicked)

        self.b_stop = QtWidgets.QPushButton(self)
        self.b_stop.setText("\u23F8 PAUSE ")
        self.b_stop.resize(50,32)
        self.b_stop.clicked.connect(self.b_stop_clicked)

        self.b_faster = QtWidgets.QPushButton(self)
        self.b_faster.setText("-")
        self.b_faster.resize(30,32)
        self.b_faster.clicked.connect(self.b_faster_clicked)

        self.freq_tabs_field=QtWidgets.QLineEdit('10',self)
        self.freq_tabs_field.setStyleSheet('background-color: white')
        self.freq_tabs_field.resize(1,1)

        self.b_slower = QtWidgets.QPushButton(self)
        self.b_slower.setText("+")
        self.b_slower.resize(30,32)
        self.b_slower.clicked.connect(self.b_slower_clicked)

        self.tabs = []
        for tab in self.tabsList:
            self.tabs.append(tab)

        self.tabWidget = QtWidgets.QTabWidget()
        for tab in self.tabs:
            self.tabWidget.addTab(tab,tab.name)

        self.tabs[0].wakeUp()
        self.tabWidget.tabBarClicked.connect(self.tab_change)


        self.layout = QtWidgets.QVBoxLayout()

        self.h1 =  QtWidgets.QHBoxLayout()
        self.h1.addWidget(self.b_play)
        self.h1.addWidget(self.b_stop)

        self.h2 =  QtWidgets.QHBoxLayout()
        self.h2.addWidget(self.b_faster)
        self.h2.addWidget(self.freq_tabs_field)
        self.h2.addWidget(self.b_slower)

        self.layout.addWidget(self.tabWidget)
        self.layout.addLayout(self.h1)
        self.layout.addLayout(self.h2)

        self.setLayout(self.layout)

        self.show()

#------------------------------------------------------------
#--------------------------MAIN------------------------------
#------------------------------------------------------------



async def run_qt_app():

    msg = Messenger()
    await msg.open('nats.oca.lan',4222, wait=3)

    def close_future(future_, loop_):
        loop_.call_later(10, future_.cancel)
        future_.cancel()

    loop = asyncio.get_event_loop()
    future = asyncio.Future()
    app = qasync.QApplication.instance()
    if hasattr(app, "aboutToQuit"):
        getattr(app, "aboutToQuit").connect(functools.partial(close_future, future, loop))

    ex = MonitGUI2(loop=loop)

    await ex.on_start_app()
    await future
    await msg.close()
    return True


# def main():
#     app = QtWidgets.QApplication(sys.argv)
#     ex = MonitGUI2()
#     sys.exit(app.exec_())


def main():
    try:
        qasync.run(run_qt_app())
    except asyncio.exceptions.CancelledError:
        sys.exit(0)


if __name__ == '__main__':
    main()
          
          
          
          
          
          
          
