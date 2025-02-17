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
import numpy as np

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
        # async init
        

    @asyncSlot()
    async def async_init(self):
        #obs_config = await self.main_window.observatory_config()
        await create_task(self.reader_loop_water(), "reader_water")
        await create_task(self.reader_loop_energy(), "reader_water")




    def initUI(self):
        # Layout
        self.layout = QVBoxLayout(self)
        self.label_water = QLabel()
        self.label_water.setStyleSheet("background-color : cyan; color: black")
        self.label_water.setFont(QtGui.QFont('Arial', 26))
        self.label_energy = QLabel()
        self.label_energy.setStyleSheet("background-color : pink; color: black")
        self.label_energy.setFont(QtGui.QFont('Arial', 26))
        # Matplotlib setup
        '''self.figure = Figure(facecolor='lightgrey')
        self.canvas = FigureCanvas(self.figure)
        if self.vertical:
        
        x = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24]
        self.ax_wind.fill_between(x,10,13,color='orange',alpha=0.3)
        self.ax_wind.fill_between(x,13,20,color='red',alpha=0.3)

        
        
        self.layout.addWidget(self.canvas)'''
        self.layout.addWidget(self.label_water)
        self.layout.addWidget(self.label_energy)

    async def reader_loop_water(self):
        msg = Messenger()
        try:
            # We want the data from the midnight of yesterday

            rdr = msg.get_reader(
                self.water_subject,
                deliver_policy='all',
            )
            logger.info(f"Subscribed to {self.water_subject}")

            
            async for data, meta in rdr:
                
                if True:
                    # if we crossed the midnight, we want to copy today's data to yesterday's and start today from scratch
                    
                    self.ts = dt_ensure_datetime(data['ts'])
                    measurement = data['measurements']
                    self.water_level = measurement['water_level']
                    logger.info(f"Measured water level {self.water_level}")
                    try:
            
                        self.label_water.setText('Water '+str(self.water_level)+ ' litres')
                    except:
                        self.label_water.setText('No data')
        except:
            pass


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

        sample_measurement = {
                "state_of_charge": 100,
                "pv_power": 0,
                "battery charge": 0,
                "battery_discharge": 0,
        }
        async for data, meta in rdr:
            try:
                # if we crossed the midnight, we want to copy today's data to yesterday's and start today from scratch
                now = datetime.datetime.now()
                '''if now.date() > today_midnight.date():
                    logger.info("Crossed the midnight, resetting the data")
                    yesterday_midnight = today_midnight
                    today_midnight = datetime.datetime.combine(now.date(), datetime.time(0))
                    self.ln_yesterday_wind.set_data(
                        self.ln_today_wind.get_xdata(),
                        self.ln_today_wind.get_ydata()
                    )
                    self.ln_today_wind.set_data([], [])

                    self.ln_yesterday_temp.set_data(
                        self.ln_today_temp.get_xdata(),
                        self.ln_today_temp.get_ydata()
                    )
                    self.ln_today_temp.set_data([], [])

                    self.ln_yesterday_hum.set_data(
                        self.ln_today_hum.get_xdata(),
                        self.ln_today_hum.get_ydata()
                    )
                    self.ln_today_hum.set_data([], [])

                    self.ln_yesterday_pres.set_data(
                        self.ln_today_pres.get_xdata(),
                        self.ln_today_pres.get_ydata()
                    )
                    self.ln_today_pres.set_data([], [])'''

                # handle current datapoint. it has measurement timestamp in data.ts, and the measurement in data.measurement
                ts = dt_ensure_datetime(data['ts']).astimezone()
                measurement = data['measurements']
                soc = measurement['state_of_charge']
                pv = measurement['pv_power']
                if pv < 0:
                    pv = 0
                bc = measurement['battery_charge']
                bd = measurement['battery_discharge']
                ec = bd + pv - bc
                # depending on the date of the measurement, we want to add point to the yesterday or today data
                hour = ts.hour + ts.minute / 60 + ts.second / 3600
                '''if ts < today_midnight.astimezone():
                    #logger.info(f'Adding point to yesterday data {wind_speed10}')
                    self.ln_yesterday_wind.set_data(
                        list(self.ln_yesterday_wind.get_xdata()) + [hour],
                        list(self.ln_yesterday_wind.get_ydata()) + [wind_speed10]
                    )

                    self.ln_yesterday_temp.set_data(
                        list(self.ln_yesterday_temp.get_xdata()) + [hour],
                        list(self.ln_yesterday_temp.get_ydata()) + [temp]
                    )

                    self.ln_yesterday_hum.set_data(
                        list(self.ln_yesterday_hum.get_xdata()) + [hour],
                        list(self.ln_yesterday_hum.get_ydata()) + [hum]
                    )

                    self.ln_yesterday_pres.set_data(
                        list(self.ln_yesterday_pres.get_xdata()) + [hour],
                        list(self.ln_yesterday_pres.get_ydata()) + [pres]
                    )
                else:
                    #logger.info(f'Adding point to today data {wind_speed10}')
                    self.ln_today_wind.set_data(
                        list(self.ln_today_wind.get_xdata()) + [hour],
                        list(self.ln_today_wind.get_ydata()) + [wind_speed10]
                    )
                    self.ln_today_temp.set_data(
                        list(self.ln_today_temp.get_xdata()) + [hour],
                        list(self.ln_today_temp.get_ydata()) + [temp]
                    )

                    self.ln_today_hum.set_data(
                        list(self.ln_today_hum.get_xdata()) + [hour],
                        list(self.ln_today_hum.get_ydata()) + [hum]
                    )

                    self.ln_today_pres.set_data(
                        list(self.ln_today_pres.get_xdata()) + [hour],
                        list(self.ln_today_pres.get_ydata()) + [pres]
                    )
                # lazy redraw
                
                self.ax_wind.relim()
                self.ax_wind.autoscale_view()

                self.ax_temp.relim()
                self.ax_temp.autoscale_view()

                self.ax_hum.relim()
                self.ax_hum.autoscale_view()

                self.ax_pres.relim()
                self.ax_pres.autoscale_view()
                self.canvas.draw_idle()'''
            except:
                soc = 'NaN'
                pv = 'NaN'
                bc = 'NaN'
                bd = 'NaN'
                ec = 'NaN'

            try:
                text = 'ENERGY:\nClusters state of charge\t'+str(soc)+' %\n' + 'Solar Power\t\t'+str(pv)+' W\n'+ 'Power consumption\t'+str(ec)+' W\n'
                self.label_energy.setText(text)
            except:
                self.label_energy.setText('No data')
        
                                

widget_class = ConditionsWidget