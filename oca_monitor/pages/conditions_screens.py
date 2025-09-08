import logging
import datetime
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout,QHBoxLayout, QLabel
from PyQt6.QtCore import QTimer
from PyQt6 import QtGui
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.image as mpimg
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
import oca_monitor.config as config


logger = logging.getLogger(__name__.rsplit('.')[-1])


class sensor():
    def __init__(self,name,name_to_display='',x=0,y=0):
        self.name = name
        self.name_to_display = name_to_display
        self.temp = "Undef"
        self.hum = "Undef"
        self.x = x
        self.y = y


class ConditionsScreensWidget(QWidget):
    def __init__(self, main_window, subject_conditions='telemetry.conditions', subject_water='telemetry.water.level', subject_energy='telemetry.power.data-manager', vertical_screen = True, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.subject_water = subject_water
        self.subject_energy = subject_energy
        self.subject_conditions = subject_conditions
        self.vertical = bool(vertical_screen)
        self.sensors = {}
        self.htsensors = config.ht_subjects
        self.initUI()
        QTimer.singleShot(0, self.async_init)
        # async init

    @asyncSlot()
    async def async_init(self):
        await create_task(self.reader_loop_water(), "nats_reader_water")
        await create_task(self.reader_loop_energy(), "nats_reader_energy")
        for sens, params in self.htsensors.items():
            if sens not in self.sensors.keys():
                self.sensors[sens]=sensor(sens,params[0],x=params[1],y=params[2])
                logger.info(sens,params[1],params[2])
            subject = self.subject_conditions+'.'+sens
            await create_task(self.reader_loop_conditions(subject,sens), f"nats_reader_conditions_{sens}")

    def initUI(self):
        # Layout
        self.layout = QVBoxLayout(self)
        self.label_water = QLabel()
        self.label_water.setStyleSheet("background-color : cyan; color: black")
        self.label_water.setFont(QtGui.QFont('Arial', 22))
        self.label_conditions = QLabel()
        self.label_conditions.setStyleSheet("background-color : white; color: black")
        self.label_energy = QLabel()
        self.label_energy.setStyleSheet("background-color : pink; color: black")
        self.label_energy.setFont(QtGui.QFont('Arial', 22))
        # Matplotlib setup
        self.figure = Figure(figsize=(24,16),facecolor='lightgrey')
        self.canvas = FigureCanvas(self.figure)
        self.layout.addWidget(self.canvas)
        # self.draw_figure()
        self.layout.addWidget(self.label_water)
        self.layout.addWidget(self.label_energy)
        self.temp_layout = QHBoxLayout(self)
        self.temp_layout.addWidget(self.label_conditions)
        self.temp_layout.addWidget(self.canvas)
        self.layout.addLayout(self.temp_layout)


    async def reader_loop_conditions(self,subject,sens):
        msg = Messenger()

        rdr = msg.get_reader(
            subject,
            deliver_policy='last',
        )
        logger.info(f"Subscribed to {subject}")

        async for data, meta in rdr:
            # async with self.locks[sens]:
            try:
                self.sensors[sens].temp = data['measurements']['temperature']
                self.sensors[sens].hum = data['measurements']['humidity']
                await self.draw_figure()
            except (ValueError, LookupError, TypeError):
                pass

    async def draw_figure(self):
        self.figure.clear()
        self.figure.gca().tick_params(axis='both', left=False, top=False, right=False, bottom=False, labelleft=False, labeltop=False, labelright=False, labelbottom=False)
        img = mpimg.imread('./oca_monitor/resources/gfx/oca_main_building.png')
        self.figure.gca().imshow(img)
        text = ''
        for s,sens in self.sensors.items():
            if int(sens.x)+int(sens.y)!=0:
                if sens.temp != "Undef":
                    if sens.name_to_display != '':
                        self.figure.gca().text(int(sens.x),int(sens.y)-90,sens.name_to_display,backgroundcolor='lightgreen',color='red',fontsize='large')
                    self.figure.gca().text(int(sens.x),int(sens.y)-20,str(int(sens.temp))+'$^{\circ} C$',backgroundcolor='lightgreen',color='red',fontsize='large')
                if sens.hum != "Undef":
                    self.figure.gca().text(int(sens.x),int(sens.y)+50,str(int(sens.hum))+'%',backgroundcolor='lightgreen',color='red',fontsize='large')
            else:
                if sens.temp != "Undef":
                    text = text+'\n'+sens.name_to_display+'\t'
                    text = text+str(int(sens.temp))+'C\t'
                if sens.hum != "Undef":
                   text = text + str(int(sens.hum))+'%'

        self.label_conditions.setText(text)
        self.canvas.draw()

    async def reader_loop_water(self):
        msg = Messenger()

        rdr = msg.get_reader(
            self.subject_water,
            deliver_policy='last'
        )
        logger.info(f"Subscribed to {self.subject_water}")

        async for data, meta in rdr:
            try:
                self.label_water.setText('Water '+str(data['measurements']['water_level'])+ ' litres')
            except (LookupError, ValueError, TypeError):
                self.label_water.setText('No data')

    async def reader_loop_energy_clb(self, data, meta) -> bool:
        try:
            measurement = data['measurements']
            soc = measurement['state_of_charge']
            pv = measurement['pv_power']
            if pv < 0:
                pv = 0
            bc = measurement['battery_charge']
            bd = measurement['battery_discharge']
            ec = bd + pv - bc
            text = 'ENERGY:\nClusters state of charge\t' + str(soc) + ' %\n' + 'Solar Power\t\t' + str(
                pv) + ' W\n' + 'Power consumption\t' + str(ec) + ' W'
            self.label_energy.setText(text)
        except (ValueError, TypeError, LookupError):
            pass
        return True

    async def reader_loop_energy(self):
        await self.main_window.run_reader(
            clb=self.reader_loop_energy_clb,
            subject=self.subject_energy,
            deliver_policy='last'
        )

    # async def reader_loop_energy(self):
    #     msg = Messenger()
    #
    #     # We want the data from the midnight of yesterday
    #     today_midnight = datetime.datetime.combine(datetime.date.today(), datetime.time(0))
    #     # yesterday_midnight = today_midnight - datetime.timedelta(days=1)
    #
    #     rdr = msg.get_reader(
    #         self.subject_energy,
    #         deliver_policy='by_start_time',
    #         opt_start_time=today_midnight,
    #     )
    #     logger.info(f"Subscribed to {self.subject_energy}")
    #
    #     # sample_measurement = {
    #     #         "state_of_charge": 100,
    #     #         "pv_power": 0,
    #     #         "battery charge": 0,
    #     #         "battery_discharge": 0,
    #     # }
    #     async for data, meta in rdr:
    #         try:
    #             # now = datetime.datetime.now()
    #             # handle current datapoint. it has measurement timestamp in data.ts, and the measurement in data.measurement
    #             # ts = dt_ensure_datetime(data['ts']).astimezone()
    #             measurement = data['measurements']
    #             soc = measurement['state_of_charge']
    #             pv = measurement['pv_power']
    #             if pv < 0:
    #                 pv = 0
    #             bc = measurement['battery_charge']
    #             bd = measurement['battery_discharge']
    #             ec = bd + pv - bc
    #             # depending on the date of the measurement, we want to add point to the yesterday or today data
    #             # hour = ts.hour + ts.minute / 60 + ts.second / 3600
    #         except (ValueError, TypeError, LookupError):
    #             soc = 'NaN'
    #             pv = 'NaN'
    #             ec = 'NaN'
    #
    #         text = 'ENERGY:\nClusters state of charge\t'+str(soc)+' %\n' + 'Solar Power\t\t'+str(pv)+' W\n'+ 'Power consumption\t'+str(ec)+' W'
    #         self.label_energy.setText(text)
                                       

widget_class = ConditionsScreensWidget