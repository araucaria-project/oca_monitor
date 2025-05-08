import logging
import datetime
import time
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QLabel,QSizePolicy
from PyQt6.QtCore import QTimer
from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap
import os

from qasync import asyncSlot

#from PyQt6 import Qt
#from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
#from matplotlib.figure import Figure
#from qasync import asyncSlot
#from serverish.base import dt_ensure_datetime
#from serverish.base.task_manager import create_task_sync, create_task
#from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

class SatelliteAnimationWidget(QWidget):
    def __init__(self, main_window, allsky_dir='/data/misc/GOES_satellite/', vertical_screen = False, **kwargs):
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
        if self.vertical:
            self.label.resize(self.width(),self.width())
        else:
            self.label.resize(self.height(),self.height())
        self.layout.addWidget(self.label,1)
        self.w = self.width()
        self.h = self.height()
        self.label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Ignored)
        # QTimer.singleShot(0, self.async_init)
        self.update_v2()
        
    def update(self):


        try:
            lista = os.popen('ls -tr '+self.dir+'*600x600.jpg').read().split('\n')[:-1]
            if len(lista) > 4:
                lista = lista[-4:]

            if len(lista)> 0:
                figure = QPixmap(lista[self.counter])

                if self.vertical:
                    self.label.setPixmap(figure.scaled(self.height(),self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))
                else:
                    self.label.setPixmap(figure.scaled(self.height(), self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))

                self.counter = self.counter + 1
                if self.counter == len(lista):
                    self.counter = 0
        except:
            self.counter = 0

        QTimer.singleShot(self.freq, self.update)
        self._change_update_time()


    def update_v2(self):

        try:
            files_list = os.listdir(self.dir)
        except OSError:
            logger.error(f'Can not access {self.dir}.')
            files_list = []

        if len(files_list) == 0:
            logger.warning(f'No files.')

        else:
            lista = [os.path.join(self.dir, f) for f in files_list]
            if len(lista) > 4:
                lista = lista[-4:]

            if len(lista) > 0:
                figure = QPixmap(lista[self.counter])

                if self.vertical:
                    self.label.setPixmap(figure.scaled(self.height(),self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))
                else:
                    self.label.setPixmap(figure.scaled(self.height(), self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))

                self.counter = self.counter + 1
                if self.counter == len(lista):
                    self.counter = 0

        QTimer.singleShot(self.freq, self.update_v2)
        self._change_update_time()

    @asyncSlot()
    async def async_init(self):

        logger.info('Starting satelite')

    def _change_update_time(self):
        self.freq = 1000

widget_class = SatelliteAnimationWidget