import asyncio
import logging
from typing import Any

from PyQt6.QtWidgets import QWidget, QVBoxLayout,QLabel,QSizePolicy
from PyQt6.QtCore import QTimer
from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap

from qasync import asyncSlot

#from PyQt6 import Qt
#from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
#from matplotlib.figure import Figure
#from qasync import asyncSlot
#from serverish.base import dt_ensure_datetime

from oca_monitor.image_display import ImageDisplay

#from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

class SatelliteAnimationWidget(QWidget):

    IMAGE_PREFIX = '600x600'
    REFRESH_IMAGE_TIME_SEC = 10
    IMAGE_CHANGE_SEC = 0.75
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
        logger.info(f"SatelliteAnimationWidget init setup done")
        
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
        # logger.info(f"SatelliteAnimationWidget UI setup done")

    @staticmethod
    async def image_instance(image_path: str) -> Any:
        image_instance = QPixmap(image_path)
        if image_instance.isNull():
            return None
        else:
            return QPixmap(image_path)

    async def image_display(self, object_to_display: QPixmap):
        if self.vertical:
            self.label.setPixmap(
                object_to_display.scaled(
                    self.height(), self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        else:
            self.label.setPixmap(
                object_to_display.scaled(
                    self.height(), self.height(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            )
            self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

    @asyncSlot()
    async def async_init(self):
        logger.info('Starting satellite display.')
        display = ImageDisplay(
            name='satellite', images_dir=self.dir, image_display_clb=self.image_display,
            image_instance_clb=self.image_instance, images_prefix = '600x600',
            image_cascade_sec = 0.75, image_pause_sec=1.25, refresh_list_sec = 10, mode='new_files'
        )
        await display.display_init()


widget_class = SatelliteAnimationWidget
