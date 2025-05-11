import logging
import datetime
import time
from typing import Any

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QLabel,QSizePolicy
from PyQt6.QtCore import QTimer
from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Arrow
import matplotlib.pyplot as plt
import os
import math

from qasync import asyncSlot

from image_display import ImageDisplay

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
        #self.label = QLabel()
        self.figure = Figure()

        self.canvas = FigureCanvas(self.figure)
        #if self.vertical:
        #    self.label.resize(self.width(),self.width())
        #else:
        #    self.label.resize(self.height(),self.height())
        # self.label.addWidget(self.canvas)
        self.layout.addWidget(self.canvas,1)
        QTimer.singleShot(0, self.async_init)
        # self.update()

    def calc_tel_xy(self,x_0,y_0,alt,az):
        pi = 3.14159
        az = (270.-az) * pi / 180.
        alt = (90-alt) * 520/90.

        x = x_0 - alt * math.cos(az)
        y = y_0 + alt * math.sin(az)
        return x,y

    def calc_wind_arrow(self,x_0,y_0,r,r_prim):
        pi = 3.14159
        try:
            winddir = self.main_window.winddir
            x = x_0-r*math.cos((270.-winddir)*pi/180.)
            y = y_0+r*math.sin((270.-winddir)*pi/180.)
            x_prim = x_0-r_prim*math.cos((270.-winddir)*pi/180.)
            y_prim = y_0+r_prim*math.sin((270.-winddir)*pi/180.)

        except:
            winddir = 180.
            x = x_0-r*math.cos((270.-winddir)*pi/180.)
            y = y_0+r*math.sin((270.-winddir)*pi/180.)
            x_prim = x_0-r_prim*math.cos((270.-winddir)*pi/180.)
            y_prim = y_0+r_prim*math.sin((270.-winddir)*pi/180.)

        return x,y,x_prim-x,y_prim-y

    def update(self):
        lista = os.popen('ls -tr '+self.dir+'lastimage*.jpg').read().split('\n')[:-1]
        if len(lista) > 0:
            try:
            #if True:
                self.figure.clf()
                ax = self.figure.add_subplot(111)
                image = plt.imread(lista[self.counter])
                ax.imshow(image)

                try:
                    for t in self.main_window.telescope_names:
                        if self.main_window.telescopes_alt and self.main_window.telescopes_az:
                            if t in self.main_window.telescopes_alt.keys() and t in self.main_window.telescopes_az.keys():
                                x,y = self.calc_tel_xy(625,625,float(self.main_window.telescopes_alt[t]),float(self.main_window.telescopes_az[t]))
                                if t == "wk06":
                                    ax.plot(x,y,"o", color='#14AD4E')
                                    ax.text(10,30,"wk06", color='#14AD4E', fontsize = 12)
                                if t == "zb08":
                                    ax.plot(x, y, "o", color='#0082E8')
                                    ax.text(10, 70, "zb08", color='#0082E8', fontsize=12)
                                if t == "jk15":
                                    ax.plot(x, y, "o", color='#67F4F5')
                                    ax.text(10, 110, "jk15", color='#67F4F5', fontsize=12)
                except Exception as e:
                    print(f"EXCEPTION 32: {e}")


                x_arrow,y_arrow,dx_arrow,dy_arrow = self.calc_wind_arrow(600,600,550.,500.)
                wind_arrow = Arrow(x_arrow,y_arrow,dx_arrow,dy_arrow,width=20.,color="magenta")
                ax.add_artist(wind_arrow)
                ax.axis('off')

                self.canvas.draw()

                self.counter = self.counter + 1
                if self.counter == len(lista):
                    self.counter = 0
            except:
                pass

        

        QTimer.singleShot(self.freq, self.update)
        self._change_update_time()

    def _change_update_time(self):
        self.freq = 2000
    #
    # async def fimage_instance(self, image_path: str) -> Any:
    #     figure = Figure()
    #     ax = figure.add_subplot(111)
    #     image = plt.imread(image_path)
    #     ax.imshow(image)
    #     return figure


    async def image_instance(self, image_path: str) -> Any:

        figure = Figure()
        figure.clf()
        ax = figure.add_subplot(111)
        image = plt.imread(image_path)
        ax.imshow(image)

        try:
            for t in self.main_window.telescope_names:
                if self.main_window.telescopes_alt and self.main_window.telescopes_az:
                    if t in self.main_window.telescopes_alt.keys() and t in self.main_window.telescopes_az.keys():
                        x, y = self.calc_tel_xy(625, 625, float(self.main_window.telescopes_alt[t]),
                                                float(self.main_window.telescopes_az[t]))
                        if t == "wk06":
                            ax.plot(x, y, "o", color='#14AD4E')
                            ax.text(10, 30, "wk06", color='#14AD4E', fontsize=12)
                        if t == "zb08":
                            ax.plot(x, y, "o", color='#0082E8')
                            ax.text(10, 70, "zb08", color='#0082E8', fontsize=12)
                        if t == "jk15":
                            ax.plot(x, y, "o", color='#67F4F5')
                            ax.text(10, 110, "jk15", color='#67F4F5', fontsize=12)
        except Exception as e:
            print(f"EXCEPTION 32: {e}")

        x_arrow, y_arrow, dx_arrow, dy_arrow = self.calc_wind_arrow(600, 600, 550., 500.)
        wind_arrow = Arrow(x_arrow, y_arrow, dx_arrow, dy_arrow, width=20., color="magenta")
        ax.add_artist(wind_arrow)
        ax.axis('off')

        figure.tight_layout()
        canvas = FigureCanvas(figure)

        return canvas

    async def image_display(self, image_to_display: Any):

        self.layout.removeWidget(self.canvas)
        self.canvas.setParent(None)

        self.canvas = image_to_display
        # if self.vertical:
        #    self.label.resize(self.width(),self.width())
        # else:
        #    self.label.resize(self.height(),self.height())
        # self.label.addWidget(self.canvas)

        # self.figure = image_to_display
        # self.figure.tight_layout()
        # self.layout.addWidget(self.canvas, 1)self.canvas = FigureCanvas(self.figure)
        self.layout.insertWidget(0, image_to_display)


        # self.canvas = FigureCanvas(self.figure)
        # self.layout.insertWidget(self.canvas,1)
        self.canvas.draw()

    @asyncSlot()
    async def async_init(self):
        logger.info('Starting allsky display.')
        display = ImageDisplay(
            name='allsky', images_dir=self.dir, image_display_clb=self.image_display,
            image_instance_clb=self.image_instance, images_prefix='lastimage',
            image_cascade_sec=0.75, image_pause_sec=1.25, refresh_list_sec=10, mode='update_files'
        )
        await display.display_init()

widget_class = AllskyAnimationMplWidget




