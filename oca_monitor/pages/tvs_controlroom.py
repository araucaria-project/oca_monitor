import logging
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel,QSlider,QDial,QScrollBar,QPushButton,QCheckBox, QTextEdit, QLineEdit
from PyQt6 import QtCore, QtGui
import json,requests
import asyncio
import oca_monitor.config as config
from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import Messenger, single_read, get_reader
from nats.errors import TimeoutError as NatsTimeoutError
import datetime
import time
from astropy.time import Time as czas_astro

from oca_monitor.utils.ephem_ocm import (
    next_sun_alt_event, sidereal_time_str, sun_alt_deg,
)

# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

def raise_alarm(mess):
    pars = {'token':'adcte9qacd6jhmhch8dyw4e4ykuod2','user':'uacjyhka7d75k5i3gmfhdg9pc2vqyf','message':mess}
    requests.post('https://api.pushover.net/1/messages.json',data=pars)

    # mgorski tez tu nizej
    pars = {'token': "aw8oa41mtt3nqrtg1vu3ny67ajans1", 'user': "ugcgrfrrfn4eefnpiekgwqnxfwtrz5", 'message': mess}
    requests.post('https://api.pushover.net/1/messages.json', data=pars)

def ephemeris():
    now = datetime.datetime.now(datetime.timezone.utc)
    ut = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime())
    lt = time.strftime('%Y/%m/%d %H:%M:%S', time.localtime())
    jd = czas_astro(now).jd
    sun_alt = sun_alt_deg(now)
    sidt = sidereal_time_str(now)
    if sun_alt < 0:
        rise = next_sun_alt_event(now, 0.0, 'rising')
        rise_s = rise.strftime('%H:%M:%S') if rise else '—'
        text = (f'UT:\t{ut}\nLT:\t{lt}\nSIDT:\t{sidt}\nJD:\t\t{jd:.2f}'
                f'\nSUNRISE(UT):\t{rise_s}\nSUN ALT:\t{sun_alt:+.1f}')
    else:
        sset = next_sun_alt_event(now, 0.0, 'setting')
        set_s = sset.strftime('%H:%M:%S') if sset else '—'
        text = (f'UT:\t{ut}\nLT:\t{lt}\nSIDT:\t{sidt}\nJD:\t\t{jd:.2f}'
                f'\nSUNSET(UT):\t{set_s}\nSUN ALT:\t{sun_alt:+.1f}')
    return text, sun_alt
        



class WidgetTvsControlroom(QWidget):
    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 **kwargs  # other parameters
                 ):
        super().__init__()
        self.main_window = main_window
        self.tel = "wk06"  # TUTAJ ZMIENIAMY NAZWE TELESKOPU


        QtCore.QTimer.singleShot(0, self.async_init)

    @asyncSlot()
    async def async_init(self):
        # nats_cfg = await single_read(f'tic.config.observatory')
        # self.nats_cfg = nats_cfg[0]
        self.initUI()
        await create_task(self.reader_nats_downloader(),"nats_nats_downloader")
        await create_task(self.reader_nats_ofp(), "nats_reader_nats_ofp")


    async def reader_nats_downloader(self):
        # try:
        #     r = get_reader(f'tic.status.{self.tel}.download', deliver_policy='last')
        #     async for data, meta in r:
        #         pass
        #         #self.downloader_data = data
        #         #self.new_fits()
        # except (asyncio.CancelledError, asyncio.TimeoutError):
        #     raise
        # except Exception as e:
        #     logger.warning(f'TOI: EXCEPTION 4c: {e}')
        pass


    async def reader_nats_ofp(self):
        try:
            r = get_reader(f'tic.status.{self.tel}.fits.pipeline.raw', deliver_policy='last')
            async for data, meta in r:
                try:
                    self.ofp_data = data
                    self.update_pictures()
                except (ValueError, TypeError, LookupError, TimeoutError, NatsTimeoutError) as e:
                    logger.warning(f"reader_nats_ofp get error: {e}")
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'TOI: EXCEPTION 4a: {e}')

    def update_pictures(self):
        pix1 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/thumbnail_a.png")
        pix2 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/last_diff_light_curve_chart.png")
        pix1 = pix1.scaledToWidth(400)
        pix2 = pix2.scaledToWidth(400)
        self.fits_pic.setPixmap(pix1)
        self.curve_pix.setPixmap(pix2)

        object = self.ofp_data["raw"]["header"]["OBJECT"]
        date = self.ofp_data["raw"]["header"]["DATE-OBS"]
        fname = self.ofp_data["raw"]["file_name"]
        type = self.ofp_data["raw"]["header"]["IMAGETYP"]
        obs_type = self.ofp_data["raw"]["header"]["OBSTYPE"]
        filter = self.ofp_data["raw"]["header"]["FILTER"]
        n = self.ofp_data["raw"]["header"]["LOOP"]
        ndit = self.ofp_data["raw"]["header"]["NLOOPS"]
        exptime = self.ofp_data["raw"]["header"]["EXPTIME"]
        print(self.ofp_data)
        txt = ""
        txt = txt + f" {date.split('T')[0]} <br>"
        txt = txt + f" {date.split('T')[1].split('.')[0]} <br>"
        txt = txt + f" {fname} <br>"
        txt = txt + f" <hr> <br>"
        txt = txt + f" OBJECT: <b>{object}</b> <br>"
        txt = txt + f" TYPE: <i>{type}</i> <i>{obs_type}</i> <br>"
        txt = txt + f" FILTER: <b>{filter}</b> {n}/{ndit} <br>"
        txt = txt + f" EXP: <b>{exptime}</b> s. <br>"
        txt = txt + f" <hr> <br>"

        self.info_e.setHtml(txt)
        self.repaint()


    def initUI(self):
        self.prev_sun_alt = None # mgorski tutaj - musze wiedziec czy jest wschod czy zachod
        self.alarm_weather_kontrolka = 0
        self.layout = QVBoxLayout(self)
        self.ephem = QLabel("init")
        self.ephem.setStyleSheet("background-color : silver; color: black")
        self.ephem.setFont(QtGui.QFont('Arial', 22))

        self.tel_e = QLineEdit(self.tel)
        self.tel_e.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font = QtGui.QFont()
        font.setBold(True)
        self.tel_e.setFont(font)
        try:
            color = self.main_window.nats_cfg["config"]["telescopes"][self.tel]["observatory"]["style"]["color"]
        except LookupError:
            color = 'black' # TODO ??
        self.tel_e.setStyleSheet(f"background-color: {color};")


        self.fits_pic = QLabel()
        self.curve_pix = QLabel()
        self.info_e = QTextEdit("")


        # DUPA
        pix1 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/thumbnail_a.png")
        pix2 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/last_diff_light_curve_chart.png")
        pix1 = pix1.scaledToWidth(400)
        pix2 = pix2.scaledToWidth(400)
        self.fits_pic.setPixmap(pix1)
        self.curve_pix.setPixmap(pix2)

        #self.layout.addWidget(self.ephem)
        self.layout.addWidget(self.tel_e)
        self.layout.addWidget(self.curve_pix)
        self.layout.addWidget(self.fits_pic)
        self.layout.addWidget(self.info_e)

        # Some async operation
        self._update_ephem()
        logger.info("UI setup done")

    def _update_ephem(self):
        text,sunalt = ephemeris()
        sunalt = str(sunalt)
        self.ephem.setText(text)
        if float(sunalt.split(':')[0]) <0. and float(sunalt.split(':')[0])  > -17.:
            self.ephem.setStyleSheet("background-color : yellow; color: black")
        elif float(sunalt.split(':')[0])  <= -17.:
            self.ephem.setStyleSheet("background-color : lightgreen; color: black")
        else:
            self.ephem.setStyleSheet("background-color : coral; color: black")

        # obsluiga buczkow
        if self.prev_sun_alt:
            cur = float(sunalt.split(':')[0])
            prev = float(str(self.prev_sun_alt).split(':')[0])
            if int(cur) == 5 and prev > cur:
                self.main_window.sound_page.play_sun_alt(True)
            elif int(cur) == -18 and prev < cur:
                self.main_window.sound_page.play_sun_alt(True)
            elif int(cur) == 0:
                self.main_window.sound_page.play_sun_alt(True)
            else:
                self.main_window.sound_page.play_sun_alt(False)
        self.prev_sun_alt = sunalt

        QtCore.QTimer.singleShot(1000, self._update_ephem)


    


widget_class = WidgetTvsControlroom
