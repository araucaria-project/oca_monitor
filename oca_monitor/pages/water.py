import logging
import datetime

from PyQt6.QtWidgets import QApplication, QWidget, QGridLayout,QLabel,QProgressBar
from PyQt6.QtCore import QTimer, Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.dates import date2num
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger


logger = logging.getLogger(__name__.rsplit('.')[-1])

class WaterWindow(QWidget):
    def __init__(self, main_window, subject='telemetry.water.level', vertical_screen = False, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.vertical = bool(vertical_screen)
        self.initUI()
        self.telemetry_start_time = datetime.datetime.combine(datetime.date.today(), datetime.time(0)) - datetime.timedelta(days=30)
        self.water_level = []
        self.ts = []
        QTimer.singleShot(0, self.async_init)
        # async init
        

    @asyncSlot()
    async def async_init(self):
        await create_task(self.water_loop(), "nats_reader_water")

    def initUI(self):
        # Layout
        self.grid = QGridLayout(self)
        self.label = QLabel("")
        self.water_b = QProgressBar(self)
        self.water_b.setOrientation(Qt.Orientation.Vertical)
        self.water_b.setRange(0,8000)
        self.water_b.setValue(0)
        # self.water_b.setStyleSheet("""
        #                     QProgressBar{
        #                         border: 2px solid grey;
        #                         border-radius: 5px;
        #                         background-color: white;
        #                         }
        #                     QProgressBar::chunk{
        #                         background-color: red;
        #                         width: 10px;
        #                         }""")

        # Matplotlib setup
        self.figure = Figure(facecolor='black')
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)

        self.figure.tight_layout()
        self.grid.addWidget(self.canvas,0,1,1,1)
        self.grid.addWidget(self.water_b,0,0)

    def update_window(self):
        if len(self.water_level)>0:
            self.water_b.setValue(int(self.water_level[-1]))
            self.ax.plot(date2num(self.ts),self.water_level,"b.")
            self.canvas.draw()
        #print(self.water_level)
        #print(self.ts)


    async def water_loop(self):
        msg = Messenger()
        r = msg.get_reader("telemetry.water.level", deliver_policy='by_start_time', opt_start_time=self.telemetry_start_time)
        async for data, meta in r:
            if True:
                ts = data['ts']
                level = float(data["measurements"]["water_level"])
                #print(ts)
                self.ts.append(ts)
                self.water_level.append(level)
                if len(self.ts) > 100:
                    self.ts = self.ts[len(self.ts)-100:]
                    self.water_level = self.water_level[len(self.ts)-100:]
                self.update_window()

        
                                

widget_class = WaterWindow