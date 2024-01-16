import logging
import datetime

from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout
from PyQt5.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger

logger = logging.getLogger(__name__.rsplit('.')[-1])

class WindDataWidget(QWidget):
    def __init__(self, main_window, subject='telemetry.weather.davis', **kwargs):
        super().__init__()
        self.main_window = main_window
        self.weather_subject = subject
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
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.ax = self.figure.add_subplot(111)

        # setting a limits
        self.ax.set_xlim([0, 23])
        self.ax.set_ylim([0, 20])

        self.ln_yesterday_wind = self.ax.plot([],[], '.-', color='gray', label='Yesterday wind')[0]
        self.ln_today_wind = self.ax.plot([],[], '.-', color='blue', label='Today wind')[0]
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

        smaple_measurement = {
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
            # if we crossed the midnight, we want to copy doday's data to yesterday's and start today from scratch
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

            # handle current datapoint. it has measurement timestamp in data.ts, and the measurement in data.measurement
            ts = dt_ensure_datetime(data['ts']).astimezone()
            measurement = data['measurements']
            wind_speed10 = measurement['wind_10min_ms']
            # depending on the date of the measurement, we want to add point to the yesterday or today data
            hour = ts.hour + ts.minute / 60 + ts.second / 3600
            if ts < today_midnight.astimezone():
                logger.info(f'Adding point to yesterday data {wind_speed10}')
                self.ln_yesterday_wind.set_data(
                    list(self.ln_yesterday_wind.get_xdata()) + [hour],
                    list(self.ln_yesterday_wind.get_ydata()) + [wind_speed10]
                )
            else:
                logger.info(f'Adding point to today data {wind_speed10}')
                self.ln_today_wind.set_data(
                    list(self.ln_today_wind.get_xdata()) + [hour],
                    list(self.ln_today_wind.get_ydata()) + [wind_speed10]
                )
            # lazy redraw
            self.ax.relim()
            self.ax.autoscale_view()
            self.canvas.draw_idle()

widget_class = WindDataWidget