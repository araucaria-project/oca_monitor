import logging
import asyncio
import os.path
from typing import Any
import json

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit, QLineEdit
from PyQt6 import QtCore, QtGui
from qasync import asyncSlot
from PyQt6.QtGui import QPixmap
from oca_monitor.image_display import ImageDisplay
from oca_monitor.utils import a_read_file


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
        logger.info(f"TelescopeOfp {self.tel} init setup done")

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
        # logger.info(f"TelescopeOfp {self.tel} UI setup done")

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
        # logger.info(content)
        if content:
            try:
                date = content["date_obs"]
                obj = content["object"]
                type = content["imagetyp"]
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
            txt = txt + f" {n}/{ndit} <b>{filter}</b>  <b>{exptime:.1f}</b> s. <br> </p>"
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

    async def image_display(self, object_to_display: QPixmap or None) -> None:
        await self.info_display()
        height = self.fits_pic.height()
        if object_to_display:
            self.fits_pic.setPixmap(
                object_to_display.scaled(
                    self.info_e.width(),
                    height,
                    QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                    QtCore.Qt.TransformationMode.SmoothTransformation
            ))
            self.fits_pic.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

    async def lc_display(self, object_to_display: QPixmap) -> None:

        self.curve_pix.setPixmap(
            object_to_display.scaled(
                self.info_e.width(),
                self.LC_HEIGHT,
                QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation
        ))
        # self.curve_pix.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)


    @asyncSlot()
    async def async_init(self) -> None:

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
