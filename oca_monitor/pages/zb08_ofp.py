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

import ephem
import time
from astropy.time import Time as czas_astro
# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])

def raise_alarm(mess):
    pars = {'token':'adcte9qacd6jhmhch8dyw4e4ykuod2','user':'uacjyhka7d75k5i3gmfhdg9pc2vqyf','message':mess}
    requests.post('https://api.pushover.net/1/messages.json',data=pars)

    # mgorski tez tu nizej
    pars = {'token': "aw8oa41mtt3nqrtg1vu3ny67ajans1", 'user': "ugcgrfrrfn4eefnpiekgwqnxfwtrz5", 'message': mess}
    requests.post('https://api.pushover.net/1/messages.json', data=pars)

def ephemeris():
    arm=ephem.Observer()
    arm.pressure=730
    #arm.horizon = '-0.5'
    arm.lon='-70.201266'
    arm.lat='-24.598616'
    arm.elev=2800
    arm.pressure=730
    date = time.strftime('%Y%m%d',time.gmtime() )
    ut = time.strftime('%Y/%m/%d %H:%M:%S',time.gmtime() )
    t = czas_astro([ut.replace('/','-',2).replace(' ','T',1)])
    jd = str(t.jd[0])[:12]
    lt = time.strftime('%Y/%m/%d %H:%M:%S',time.localtime() )
    arm.date = ut
    sunset=str(arm.next_setting(ephem.Sun()))
    sunrise=str(arm.next_rising(ephem.Sun()))
    sun = ephem.Sun()
    moon = ephem.Moon()
    sun.compute(arm)
    moon.compute(arm)
    arm.horizon = '-18'
    
    lst = arm.sidereal_time()
    if str(sun.alt)[0] == '-':
        text = 'UT:\t'+ut+'\nLT:\t'+lt+'\nSIDT:\t'+str(lst)+'\nJD:\t\t'+str("{:.2f}".format(float(jd)))+'\nSUNRISE(UT):\t'+sunrise[-8:]+'\nSUN ALT:\t'+str(sun.alt)
    else:
        text = 'UT:\t'+ut+'\nLT:\t'+lt+'\nSIDT:\t'+str(lst)+'\nJD:\t\t'+str("{:.2f}".format(float(jd)))+'\nSUNSET(UT):\t'+sunset[-8:]+'\nSUN ALT:\t'+str(sun.alt)
    return text,sun.alt
        



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
        self.tel = "zb08"  # TUTAJ ZMIENIAMY NAZWE TELESKOPU


        QtCore.QTimer.singleShot(0, self.async_init)

    @asyncSlot()
    async def async_init(self):
        # nats_cfg = await single_read(f'tic.config.observatory')
        # self.nats_cfg = nats_cfg[0]
        self.initUI()
        await create_task(self.reader_nats_downloader(),"message_reader")
        await create_task(self.reader_nats_ofp(), "message_reader")


    async def reader_nats_downloader(self):
        try:
            r = get_reader(f'tic.status.{self.tel}.download', deliver_policy='last')
            async for data, meta in r:
                pass
                #self.downloader_data = data
                #self.new_fits()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'TOI: EXCEPTION 4c: {e}')


    async def reader_nats_ofp(self):
        try:
            r = get_reader(f'tic.status.{self.tel}.fits.pipeline.raw', deliver_policy='last')
            async for data, meta in r:
                self.ofp_data = data
                self.update_pictures()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'TOI: EXCEPTION 4a: {e}')

    def update_pictures(self):
        self.info_e.clear()
        pix1 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/thumbnail_display.png")
        pix2 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/last_light_curve_chart_display.png")
        pix1 = pix1.scaled(500,500)
        pix2 = pix2.scaled(500,150)
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

        txt = ""
        txt = txt + f" <p style='font-size: 15pt;'> {date.split('T')[0]} {date.split('T')[1].split('.')[0]} "
        txt = txt + f" <i>{type}</i> <b>{object}</b>"
        txt = txt + f" {n}/{ndit} <b>{filter}</b>  <b>{exptime}</b> s. <br> </p>"
        #txt = txt + f" <hr> <br>"

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
        except (LookupError, TypeError):
            color = 'black' # TODO ??
        self.tel_e.setStyleSheet(f"background-color: {color}; color: black")


        self.fits_pic = QLabel()
        self.curve_pix = QLabel()
        self.info_e = QTextEdit("")



        # DUPA
        pix1 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/thumbnail_display.png")
        pix2 = QtGui.QPixmap(f"/data/fits/{self.tel}/processed-ofp/thumbnails/last_light_curve_chart_display.png")
        pix1 = pix1.scaled(500,500)
        pix2 = pix2.scaled(500,150)
        self.fits_pic.setPixmap(pix1)
        self.curve_pix.setPixmap(pix2)

        #self.layout.addWidget(self.ephem)
        self.layout.addWidget(self.tel_e)
        self.layout.addWidget(self.fits_pic)
        self.layout.addWidget(self.info_e)
        self.layout.addWidget(self.curve_pix)

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
        # if self.prev_sun_alt:
        #     if int(sunalt.split(':')[0]) == 5 and ephem.degrees(self.prev_sun_alt) > ephem.degrees(sunalt):
        #         self.main_window.sound_page.play_sun_alt(True)
        #     elif int(sunalt.split(':')[0]) == -18 and ephem.degrees(self.prev_sun_alt) < ephem.degrees(sunalt):
        #         self.main_window.sound_page.play_sun_alt(True)
        #     elif int(sunalt.split(':')[0]) == 0:
        #         self.main_window.sound_page.play_sun_alt(True)
        #     else:
        #         self.main_window.sound_page.play_sun_alt(False)
        # self.prev_sun_alt = sunalt

        QtCore.QTimer.singleShot(1000, self._update_ephem)


    


widget_class = WidgetTvsControlroom
