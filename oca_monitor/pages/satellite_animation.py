import asyncio
import copy
import logging
import datetime
import time

import numpy as np
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
from serverish.base.task_manager import create_task
#from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

class SatelliteAnimationWidget(QWidget):

    IMAGE_PREFIX = '600x600'
    REFRESH_IMAGE_TIME_SEC = 10
    IMAGE_CHANGE_SEC = 0.5
    MAX_IMAGES_NO = 12

    def __init__(self, main_window, allsky_dir='/data/misc/GOES_satellite/', vertical_screen = False, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.dir = allsky_dir
        self.freq = 500
        self.vertical = bool(vertical_screen)
        self.counter = 0
        self.lock = asyncio.Lock()
        self.image_queue = asyncio.Queue()
        self.files_list = []
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
        QTimer.singleShot(0, self.async_init)
        # self.update_v2()
        
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
        files_list = []
        try:
            files_found = os.listdir(self.dir)
        except OSError:
            logger.error(f'Can not access {self.dir}.')
            files_found = []

        for file in files_found:
            if self.IMAGE_PREFIX in file:
                files_list.append(file)

        if len(files_list) == 0:
            logger.warning(f'No files.')

        else:
            files_list.sort()
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

    async def a_image_list_refresh(self):
        while True:
            current_files_list = []
            try:
                files_found = os.listdir(self.dir)
            except OSError:
                logger.error(f'Can not access {self.dir}.')
                files_found = []

            for file in files_found:
                if self.IMAGE_PREFIX in file:
                    current_files_list.append(file)
            current_files_list.sort()
            current_files_list_path = [os.path.join(self.dir, f) for f in current_files_list[:self.MAX_IMAGES_NO]]
            logger.info(f'{len(current_files_list_path)} {len(self.files_list)}')
            if current_files_list_path != self.files_list:
                logger.info(f'Satellite files list updating...')
                new_files = [x for x in current_files_list_path if x not in self.files_list]
                new_files_no = len(new_files)
                if new_files_no > 0:
                    async with self.lock:
                        self.files_list = copy.deepcopy(current_files_list_path)
                        for new_file in new_files:
                            if self.image_queue.qsize() > self.MAX_IMAGES_NO - 1:
                                _ = await self.image_queue.get()
                            await self.image_queue.put(QPixmap(new_file))
                logger.info(f'Satellite files list updated by new files no: {new_files_no}.')
            await asyncio.sleep(self.REFRESH_IMAGE_TIME_SEC)

    async def a_display(self):
        while True:
            async with self.lock:
                if self.image_queue.qsize() > 0:
                    image_to_display = await self.image_queue.get()
                    if self.vertical:
                        self.label.setPixmap(
                            image_to_display.scaled(
                                self.height(), self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                        )
                    else:
                        self.label.setPixmap(
                            image_to_display.scaled(
                                self.height(), self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                        )
                    await self.image_queue.put(image_to_display)

            await asyncio.sleep(self.IMAGE_CHANGE_SEC)

    @asyncSlot()
    async def async_init(self):
        logger.info('Starting satellite display.')
        await create_task(self.a_image_list_refresh(), 'satellite_refresh_images')
        await create_task(self.a_display(), 'satellite_display_images')
        # logger.info('Starting satellite display started.')



    def _change_update_time(self):
        self.freq = 1000

widget_class = SatelliteAnimationWidget