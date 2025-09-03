import logging
import datetime

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QLabel
from PyQt6.QtCore import QTimer
from PyQt6 import QtGui
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
from nats.errors import TimeoutError as NatsTimeoutError

logger = logging.getLogger(__name__.rsplit('.')[-1])

class ConditionsWidget(QWidget):
    def __init__(self, main_window, subject='telemetry.water.level', subject2 = 'telemetry.power.data-manager', vertical_screen = False, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.water_subject = subject
        self.energy_subject = subject2
        self.vertical = bool(vertical_screen)
        self.initUI()
        self.water_level = 0
        QTimer.singleShot(0, self.async_init)
        logger.info(f"ConditionsWidget init setup done")
        

    @asyncSlot()
    async def async_init(self):
        #obs_config = await self.main_window.observatory_config()
        await create_task(self.reader_loop_water(), "nats_reader_water_conditions")
        await create_task(self.reader_loop_energy(), "nats_reader_energy_conditions")

    def initUI(self):
        # Layout
        self.layout = QVBoxLayout(self)
        self.label_water = QLabel()
        self.label_water.setStyleSheet("background-color : cyan; color: black")
        self.label_water.setFont(QtGui.QFont('Arial', 24))
        self.label_energy = QLabel()
        self.label_energy.setStyleSheet("background-color : pink; color: black")
        self.label_energy.setFont(QtGui.QFont('Arial', 24))
        self.layout.addWidget(self.label_water)
        self.layout.addWidget(self.label_energy)

    async def reader_loop_water(self):

        msg = Messenger()
        rdr = msg.get_reader(
            self.water_subject,
            deliver_policy='all',
        )
        logger.info(f"Subscribed to {self.water_subject}")

        async for data, meta in rdr:
            try:
                self.ts = dt_ensure_datetime(data['ts'])
                measurement = data['measurements']
                self.water_level = measurement['water_level']
                logger.debug(f"Measured water level {self.water_level}")
                self.label_water.setText('Water '+str(self.water_level)+ ' litres')
            except (ValueError, TypeError, LookupError, TimeoutError, NatsTimeoutError) as e:
                logger.warning(f"reader_loop_water get error: {e}")
                self.label_water.setText('No data')

    async def reader_loop_energy(self):
        msg = Messenger()

        # We want the data from the midnight of yesterday
        today_midnight = datetime.datetime.combine(datetime.date.today(), datetime.time(0))
        yesterday_midnight = today_midnight - datetime.timedelta(days=1)

        rdr = msg.get_reader(
            self.energy_subject,
            deliver_policy='by_start_time',
            opt_start_time=today_midnight,
        )
        logger.info(f"Subscribed to {self.energy_subject}")

        async for data, meta in rdr:
            try:
                measurement = data['measurements']
                soc = measurement['state_of_charge']
                pv = measurement['pv_power']
                if pv < 0:
                    pv = 0
                bc = measurement['battery_charge']
                bd = measurement['battery_discharge']
                ec = bd + pv - bc
            except (ValueError, TypeError, LookupError, TimeoutError, NatsTimeoutError) as e:
                logger.warning(f"reader_loop_energy get error: {e}")
                soc = 'NaN'
                pv = 'NaN'
                ec = 'NaN'

            try:
                text = 'ENERGY:\nClusters state of charge\t'+str(soc)+' %\n' + 'Solar Power\t\t'+str(pv)+' W\n'+ 'Power consumption\t'+str(ec)+' W'
                self.label_energy.setText(text)
            except (ValueError, TypeError, LookupError):
                self.label_energy.setText('No data')
        
                                

widget_class = ConditionsWidget