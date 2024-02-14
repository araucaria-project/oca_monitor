import logging
import datetime
import time
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QLabel,QSizePolicy
from PyQt6.QtCore import QTimer
from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Arrow
import matplotlib.pyplot as plt
import os
import math
#from PyQt6 import Qt
#from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
#from matplotlib.figure import Figure
#from qasync import asyncSlot
#from serverish.base import dt_ensure_datetime
#from serverish.base.task_manager import create_task_sync, create_task
#from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

class AllskyAnimationMplWidget(QWidget):
    def __init__(self, main_window, allsky_dir='/data/misc/allsky/', vertical_screen = False, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.dir = allsky_dir
        self.freq = 500
        self.vertical = bool(vertical_screen)
        self.counter = 0
        self.initUI()
        
    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.label = QLabel()
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        if self.vertical:
            self.label.resize(self.width(),self.width())
        else:
            self.label.resize(self.height(),self.height())
        self.label.addWidget(self.canvas)
        self.layout.addWidget(self.label,1)
        self.update()
    
    def calc_wind_arrow(self,x_0,y_0,r,r_prim):
        pi = 3.14159
        try:
            winddir = self.main_window.wind_dir_deg
            x = x_0+r*math.cos((270.-winddir)*pi/180.)
            y = y_0+r*math.sin((270.-winddir)*pi/180.)
            x_prim = x_0+r_prim*math.cos((270.-winddir)*pi/180.)
            y_prim = y_0+r_prim*math.sin((270.-winddir)*pi/180.)

        except:
            self.wind_dir = 180.
            x = x_0+r*math.cos((270.-winddir)*pi/180.)
            y = y_0+r*math.sin((270.-winddir)*pi/180.)
            x_prim = x_0+r_prim*math.cos((270.-winddir)*pi/180.)
            y_prim = y_0+r_prim*math.sin((270.-winddir)*pi/180.)

        return x,y,x_prim-x,y_prim-y

    def update(self):
        lista = os.popen('ls -tr '+self.dir+'lastimage*.jpg').read().split('\n')[:-1]
        if len(lista) > 0:
            try:
                self.figure.clf()
                ax = self.figure.add_subplot(111)
                image = plt.imread(lista[self.counter])
                plt.imshow(image)

                x_arrow,y_arrow,dx_arrow,dy_arrow = self.calc_wind_arrow(1000,1000,420.,370.)
                wind_arrow = Arrow(x_arrow,y_arrow,dx_arrow,dy_arrow,width=20.,color="pink")
                ax.add_artist(wind_arrow)


                self.counter = self.counter + 1
                if self.counter == len(lista):
                    self.counter = 0
            except:
                pass

        

        QTimer.singleShot(self.freq, self.update)
        self._change_update_time()

    def _change_update_time(self):
        self.freq = 2000

widget_class = AllskyAnimationMplWidget




