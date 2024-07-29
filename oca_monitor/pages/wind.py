import logging
import datetime

from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt6.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger
import numpy as np

logger = logging.getLogger(__name__.rsplit('.')[-1])

class WindDataWidget(QWidget):
    def __init__(self, main_window, subject='telemetry.weather.davis', vertical_screen = False, **kwargs):
        super().__init__()
        self.main_window = main_window
        self.weather_subject = subject
        self.vertical = bool(vertical_screen)
        self.initUI()
        # async init
        QTimer.singleShot(0, self.async_init)

    @asyncSlot()
    async def async_init(self):
        obs_config = await self.main_window.observatory_config()
        await create_task(self.reader_loop(), "wind reader")





    def initUI(self):
        # Layout
        self.layout = QVBoxLayout(self)

        # Matplotlib setup
        self.figure = Figure(facecolor='lightgrey')
        self.canvas = FigureCanvas(self.figure)
        if self.vertical:
            self.ax_wind = self.figure.add_subplot(221)
            self.ax_temp = self.figure.add_subplot(222)
            self.ax_hum = self.figure.add_subplot(223)
            self.ax_pres = self.figure.add_subplot(224)
        else:
            self.ax_wind = self.figure.add_subplot(411)
            self.ax_temp = self.figure.add_subplot(412)
            self.ax_hum = self.figure.add_subplot(413)
            self.ax_pres = self.figure.add_subplot(414)

        self.ax_wind.set_title("Wind [m/s]")
        self.ax_temp.set_title("Temperature [C]")
        self.ax_hum.set_title("Humidity [%]")
        self.ax_pres.set_title("Pressure [hPa]")
        # setting a limits
        self.ax_wind.set_xlim([0, 24])
        self.ax_wind.set_ylim([0, 20])
        self.ax_temp.set_xlim([0, 24])
        self.ax_hum.set_xlim([0, 24])
        self.ax_hum.set_ylim([0, 90])
        self.ax_pres.set_xlim([0, 24])
        x = [0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24]
        self.ax_wind.fill_between(x,10,13,color='orange',alpha=0.3)
        self.ax_wind.fill_between(x,13,20,color='red',alpha=0.3)

        self.ax_hum.fill_between(x,70,80,color='orange',alpha=0.3)
        self.ax_hum.fill_between(x,80,90,color='red',alpha=0.3)

        self.ln_yesterday_wind = self.ax_wind.plot([],[], '.', color='silver', alpha=0.1, label='Yesterday')[0]
        self.ln_today_wind = self.ax_wind.plot([],[], '.-', color='blue', label='Today')[0]

        self.ln_yesterday_temp = self.ax_temp.plot([],[], '.', color='silver', alpha=0.1, label='Yesterday')[0]
        self.ln_today_temp = self.ax_temp.plot([],[], '.-', color='blue', label='Today')[0]

        self.ln_yesterday_hum = self.ax_hum.plot([],[], '.', color='silver', alpha=0.1, label='Yesterday')[0]
        self.ln_today_hum = self.ax_hum.plot([],[], '.-', color='blue', label='Today')[0]

        self.ln_yesterday_pres = self.ax_pres.plot([],[], '.', color='silver', alpha=0.1, label='Yesterday')[0]
        self.ln_today_pres = self.ax_pres.plot([],[], '.-', color='blue', label='Today')[0]
        self.ax_wind.grid(which='major', axis='both')
        self.ax_temp.grid(which='major', axis='both')
        self.ax_hum.grid(which='major', axis='both')
        self.ax_pres.grid(which='major', axis='both')
        self.figure.tight_layout()
        self.layout.addWidget(self.canvas)

    async def reader_loop(self):
        msg = Messenger()

        # We want the data from the midnight of yesterday
        today_midnight = datetime.datetime.combine(datetime.date.today(), datetime.time(0))
        yesterday_midnight = today_midnight - datetime.timedelta(days=1)

        rdr = msg.get_reader(
            self.weather_subject,
            deliver_policy='by_start_time',
            opt_start_time=yesterday_midnight,
        )
        logger.info(f"Subscribed to {self.weather_subject}")

        sample_measurement = {
                "temperature_C": 10,
                "humidity": 50,
                "wind_dir_deg": 180,
                "wind_ms": 5,
                "wind_10min_ms": 5,
                "pressure_Pa": 101325,
                "bar_trend": 0,
                "rain_mm": 0,
                "rain_day_mm": 0,
                "indoor_temperature_C": 20,
                "indoor_humidity": 50,
        }
        async for data, meta in rdr:
            try:
                # if we crossed the midnight, we want to copy today's data to yesterday's and start today from scratch
                now = datetime.datetime.now()
                if now.date() > today_midnight.date():
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
                    self.ln_today_pres.set_data([], [])

                # handle current datapoint. it has measurement timestamp in data.ts, and the measurement in data.measurement
                ts = dt_ensure_datetime(data['ts']).astimezone()
                measurement = data['measurements']
                wind_speed10 = measurement['wind_10min_ms']
                temp = measurement['temperature_C']
                hum = measurement['humidity']
                pres = measurement['pressure_Pa']/100.
                # depending on the date of the measurement, we want to add point to the yesterday or today data
                hour = ts.hour + ts.minute / 60 + ts.second / 3600
                if ts < today_midnight.astimezone():
                    logger.info(f'Adding point to yesterday data {wind_speed10}')
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
                    logger.info(f'Adding point to today data {wind_speed10}')
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
                self.canvas.draw_idle()
            except:
                pass

widget_class = WindDataWidget