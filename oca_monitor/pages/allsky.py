import logging
import datetime

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QLabel,QSizePolicy
from PyQt6.QtCore import QTimer
from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap
#from PyQt6 import Qt
#from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
#from matplotlib.figure import Figure
#from qasync import asyncSlot
#from serverish.base import dt_ensure_datetime
#from serverish.base.task_manager import create_task_sync, create_task
#from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

class AllskyWidget(QWidget):
    def __init__(self, main_window, allsky_dir='/data/misc/allsky/', **kwargs):
        super().__init__()
        self.main_window = main_window
        self.dir = allsky_dir
        self.initUI()
        


    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.label = QLabel()
        self.update()
        self.layout.addWidget(self.label,1)
        
    async def update(self):
        figure = QPixmap(self.dir+'lastimage.jpg')
        self.label.setPixmap(self.figure.scaled(self.label.width(), self.label.height(),,QtCore.Qt.KeepAspectRatio))
        QTimer.singleShot(60000, self.initUI)

widget_class = AllskyWidget