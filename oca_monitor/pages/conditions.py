import logging
import datetime

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QLabel
from PyQt6.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
import numpy as np

logger = logging.getLogger(__name__.rsplit('.')[-1])

class ConditionsWidget(QWidget):
    def __init__(self, main_window, subject='telemetry.water.level', vertical_screen = False, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.water_subject = subject
        self.vertical = bool(vertical_screen)
        QTimer.singleShot(0, self.async_init)
        self.initUI()
        # async init
        

    @asyncSlot()
    async def async_init(self):
        #obs_config = await self.main_window.observatory_config()
        await create_task(self.reader_loop(), "reader")





    def initUI(self):
        # Layout
        self.layout = QVBoxLayout(self)
        self.label = QLabel()
        #try:
        if True:
            self.label.setText(str(self.ts)+'\n'+str(self.water_level))
        #except:
        #    self.label.setText('No data')
        # Matplotlib setup
        '''self.figure = Figure(facecolor='lightgrey')
        self.canvas = FigureCanvas(self.figure)
        if self.vertical:
        
        x = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24]
        self.ax_wind.fill_between(x,10,13,color='orange',alpha=0.3)
        self.ax_wind.fill_between(x,13,20,color='red',alpha=0.3)

        
        self.ax_wind.grid(which='major', axis='both')
       
        self.figure.tight_layout()
        self.layout.addWidget(self.canvas)'''
        self.layout.addWidget(self.label)

    async def reader_loop(self):
        msg = Messenger()

        # We want the data from the midnight of yesterday

        rdr = msg.get_reader(
            self.water_subject,
            deliver_policy='last',
        )
        logger.info(f"Subscribed to {self.water_subject}")

        
        async for data, meta in rdr:
            #try:
            if True:
                # if we crossed the midnight, we want to copy today's data to yesterday's and start today from scratch
                
                self.ts = dt_ensure_datetime(data['ts'])
                measurement = data['measurements']
                self.water_level = measurement['water_level']
                                
            #except:
            #    pass

widget_class = ConditionsWidget