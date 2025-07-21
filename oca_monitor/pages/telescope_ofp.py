import logging
import asyncio
import os.path
from typing import Any
import json

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit, QLineEdit
from PyQt6 import QtCore, QtGui
from qasync import asyncSlot
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader
from PyQt6.QtGui import QPixmap
from oca_monitor.image_display import ImageDisplay
from oca_monitor.utils import a_read_file

# please use logging like here, it will name the log record with the name of the module
logger = logging.getLogger(__name__.rsplit('.')[-1])


class TelescopeOfp(QWidget):

    LC_HEIGHT = 150
    INFO_HEIGHT = 50
    JSON_FILE_NAME = 'thumbnail_display.json'
    PNG_FILE_NAME = 'thumbnail_display.png'
    LC_FILE_NAME = 'last_light_curve_chart_display.png'

    # You can use just def __init__(self, **kwargs) if you don't want to bother with the arguments
    def __init__(self,
                 main_window, # always passed
                 tel: str,
                 example_parameter: str = "Hello OCM!",  # parameters from settings
                 subject='telemetry.weather.davis',#weather subject
                 **kwargs  # other parameters
                 ):
        self.tel = tel
        self.dir = f"/data/fits/{self.tel}/processed-ofp/thumbnails/"
        self.main_window = main_window
        super().__init__()
        self.initUI()

    def initUI(self):
        self.prev_sun_alt = None # mgorski tutaj - musze wiedziec czy jest wschod czy zachod
        self.alarm_weather_kontrolka = 0
        self.layout = QVBoxLayout(self)
        # self.ephem = QLabel("init")
        # self.ephem.setStyleSheet("background-color : silver; color: black")
        # self.ephem.setFont(QtGui.QFont('Arial', 22))
        self.tel_e = QLineEdit(self.tel)
        self.tel_e.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        font = QtGui.QFont()
        font.setBold(True)
        self.tel_e.setFont(font)
        self.tel_e.setStyleSheet(f"background-color: black; color: white")
        try:
            color = self.main_window.nats_cfg["config"]["telescopes"][self.tel]["observatory"]["style"]["color"]
        except (LookupError, TypeError):
            color = 'black'

        self.fits_pic = QLabel()

        self.curve_pix = QLabel()
        self.curve_pix.setFixedHeight(self.LC_HEIGHT)

        self.info_e = QTextEdit("")
        self.info_e.setFixedHeight(self.INFO_HEIGHT)
        self.info_e.setStyleSheet(f"background-color: {color}; color: black")
        # self.set_pix_maps()

        self.layout.addWidget(self.fits_pic)
        self.layout.addWidget(self.info_e)
        self.layout.addWidget(self.curve_pix)


        QtCore.QTimer.singleShot(0, self.async_init)
        logger.info("UI setup done")

    @property
    def thumbnail_path(self) -> str:
        return f"/data/fits/{self.tel}/processed-ofp/thumbnails/thumbnail_display.png"

    @property
    def light_curve_chart_path(self) -> str:
        return f"/data/fits/{self.tel}/processed-ofp/thumbnails/last_light_curve_chart_display.png"


    # @asyncSlot()
    # async def async_init(self):
    #     # nats_cfg = await single_read(f'tic.config.observatory')
    #     # self.nats_cfg = nats_cfg[0]
    #     self.initUI()
    #     await create_task(self.reader_nats_downloader(),"message_reader")
    #     await create_task(self.reader_nats_ofp(), "message_reader")


    # async def reader_nats_downloader(self):
    #     try:
    #         r = get_reader(f'tic.status.{self.tel}.download', deliver_policy='last')
    #         async for data, meta in r:
    #             pass
    #             #self.downloader_data = data
    #             #self.new_fits()
    #     except (asyncio.CancelledError, asyncio.TimeoutError):
    #         raise
    #     except Exception as e:
    #         logger.warning(f'TOI: EXCEPTION 4c: {e}')


    # async def reader_nats_ofp(self):
    #     try:
    #         r = get_reader(f'tic.status.{self.tel}.fits.pipeline.raw', deliver_policy='last')
    #         async for data, meta in r:
    #             self.ofp_data = data
    #             self.update_pictures()
    #     except (asyncio.CancelledError, asyncio.TimeoutError) as e:
    #         logger.warning(f'TOI: EXCEPTION 4b: {e}')
    #     except Exception as e:
    #         logger.warning(f'TOI: EXCEPTION 4a: {e}')

    # def set_pix_maps(self):
    #
    #     pix1 = QtGui.QPixmap(self.thumbnail_path)
    #     pix2 = QtGui.QPixmap(self.light_curve_chart_path)
    #     # pix1 = pix1.scaled(600,600)
    #     width = self.fits_pic.width()
    #     # width = 500
    #     height = self.fits_pic.height()
    #     # height = 600
    #     pix1 = pix1.scaled(
    #         width, height, QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation
    #     )
    #
    #     pix2 = pix2.scaled(width, self.LC_HEIGHT)
    #     self.fits_pic.setPixmap(pix1)
    #     self.fits_pic.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    #     self.curve_pix.setPixmap(pix2)

    # def update_pictures(self):
    #     self.info_e.clear()
    #     try:
    #         color = self.main_window.nats_cfg["config"]["telescopes"][self.tel]["observatory"]["style"]["color"]
    #     except (LookupError, TypeError):
    #         color = 'black'
    #
    #     self.info_e.setStyleSheet(f"background-color: {color}; color: black")
    #
    #     self.set_pix_maps()
    #
    #     object = self.ofp_data["raw"]["header"]["OBJECT"]
    #     date = self.ofp_data["raw"]["header"]["DATE-OBS"]
    #     fname = self.ofp_data["raw"]["file_name"]
    #     type = self.ofp_data["raw"]["header"]["IMAGETYP"]
    #     obs_type = self.ofp_data["raw"]["header"]["OBSTYPE"]
    #     filter = self.ofp_data["raw"]["header"]["FILTER"]
    #     n = self.ofp_data["raw"]["header"]["LOOP"]
    #     ndit = self.ofp_data["raw"]["header"]["NLOOPS"]
    #     exptime = self.ofp_data["raw"]["header"]["EXPTIME"]
    #
    #     txt = ""
    #     txt = txt + f" <p style='font-size: 15pt;'> {date.split('T')[0]} {date.split('T')[1].split('.')[0]} "
    #     txt = txt + f" <i>{type}</i> <b>{object}</b>"
    #     txt = txt + f" {n}/{ndit} <b>{filter}</b>  <b>{exptime}</b> s. <br> </p>"
    #     #txt = txt + f" <hr> <br>"
    #
    #     self.info_e.setHtml(txt)
    #     self.repaint()


    async def info_display(self) -> None:

        try:
            color = self.main_window.nats_cfg["config"]["telescopes"][self.tel]["observatory"]["style"]["color"]
        except (LookupError, TypeError):
            color = 'gray'

        file_content = await a_read_file(path=os.path.join(self.dir, self.JSON_FILE_NAME), raise_err=False)
        if file_content:
            content = json.loads(file_content)
        else:
            content = None
        logger.info(content)
        if content:
            try:
                date = content["date_obs"]
                obj = content["object"]
                # fname = self.ofp_data["raw"]["file_name"]
                type = content["imagetyp"]
                # obs_type = self.ofp_data["raw"]["header"]["OBSTYPE"]
                filter = content["filter"]
                n = content["loop"]
                ndit = content["nloops"]
                exptime = content["exptime"]
            except (ValueError, LookupError) as e:
                logger.warning(f"Can not parse data: {e}")
                return
            txt = ""
            txt = txt + f" <p style='font-size: 15pt;'> {date.split('T')[0]} {date.split('T')[1].split('.')[0]} "
            txt = txt + f" <i>{type}</i> <b>{obj}</b>"
            txt = txt + f" {n}/{ndit} <b>{filter}</b>  <b>{exptime}</b> s. <br> </p>"
            self.info_e.clear()
            self.info_e.setStyleSheet(f"background-color: {color}; color: black")
            self.info_e.setHtml(txt)
            self.repaint()


    @staticmethod
    async def image_instance(image_path: str) -> Any:
        image_instance = QPixmap(image_path)
        if image_instance.isNull():
            return None
        else:
            return QPixmap(image_path)

    async def image_display(self, object_to_display: QPixmap):
        await self.info_display()
        height = self.fits_pic.height()

        self.fits_pic.setPixmap(
            object_to_display.scaled(
                self.info_e.width(),
                height,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation
        ))
        self.fits_pic.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

    async def lc_display(self, object_to_display: QPixmap):

        self.curve_pix.setPixmap(
            object_to_display.scaled(
                self.info_e.width(),
                self.LC_HEIGHT,
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation
        ))
        # self.curve_pix.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)


    @asyncSlot()
    async def async_init(self):

        im_on_init = await self.image_instance(image_path=os.path.join(self.dir, self.PNG_FILE_NAME))
        await self.image_display(object_to_display=im_on_init)
        lc_on_init = await self.image_instance(image_path=os.path.join(self.dir, self.LC_FILE_NAME))
        await self.lc_display(object_to_display=lc_on_init)

        display = ImageDisplay(
            name='telescope', images_dir=self.dir, image_display_clb=self.image_display,
            image_instance_clb=self.image_instance, images_prefix=self.PNG_FILE_NAME,
            image_cascade_sec=0, image_pause_sec=0, refresh_list_sec=1, mode='update_files_show_once',
        )
        await display.display_init()

        lc = ImageDisplay(
            name='light curve', images_dir=self.dir, image_display_clb=self.lc_display,
            image_instance_clb=self.image_instance, images_prefix=self.LC_FILE_NAME,
            image_cascade_sec=0, image_pause_sec=0, refresh_list_sec=1, mode='update_files_show_once',
        )
        await lc.display_init()
