import logging
from typing import Any

from PyQt6.QtWidgets import QWidget, QVBoxLayout,QLabel
from PyQt6.QtCore import QTimer
from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap

from qasync import asyncSlot

from oca_monitor.image_display import ImageDisplay

#from PyQt6 import Qt
#from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
#from matplotlib.figure import Figure
#from qasync import asyncSlot
#from serverish.base import dt_ensure_datetime
#from serverish.base.task_manager import create_task_sync, create_task
#from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

class AllskyAnimationWidget(QWidget):
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
        if self.vertical:
            self.label.resize(self.width(),self.width())
        else:
            self.label.resize(self.height(),self.height())
        self.layout.addWidget(self.label,1)
        QTimer.singleShot(0, self.async_init)
        # self.update()

    @staticmethod
    async def image_instance(image_path: str) -> Any:
        image_instance = QPixmap(image_path)
        if image_instance.isNull():
            return None
        else:
            return QPixmap(image_path)

    async def image_display(self, object_to_display: QPixmap):

        if self.vertical:
            self.label.setPixmap(object_to_display.scaled(self.width(),self.width(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.label.setPixmap(object_to_display.scaled(self.height(),self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))

    @asyncSlot()
    async def async_init(self):
        logger.info('Starting allsky display.')
        display = ImageDisplay(
            name='allsky', images_dir=self.dir, image_display_clb=self.image_display,
            image_instance_clb=self.image_instance, images_prefix = 'lastimage',
            image_cascade_sec = 0.75, image_pause_sec=1.25, refresh_list_sec = 10, mode='update_files',
            sort_reverse=True
        )
        await display.display_init()

    # def update(self):
    #     lista = os.popen('ls -tr '+self.dir+'lastimage*.jpg').read().split('\n')[:-1]
    #     if len(lista) > 0:
    #         try:
    #             figure = QPixmap(lista[self.counter])
    #             if self.vertical:
    #                 self.label.setPixmap(figure.scaled(self.width(),self.width(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))
    #             else:
    #                 self.label.setPixmap(figure.scaled(self.height(),self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio))
    #
    #             self.counter = self.counter + 1
    #             if self.counter == len(lista):
    #                 self.counter = 0
    #         except:
    #             pass
    #
    #
    #
    #     QTimer.singleShot(self.freq, self.update)
    #     self._change_update_time()
    #
    #
    #
    # def _change_update_time(self):
    #     self.freq = 2000

widget_class = AllskyAnimationWidget
