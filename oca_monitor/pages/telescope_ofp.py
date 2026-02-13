import asyncio
import datetime
import logging
import os.path
from typing import Any, Optional
import json

from serverish.base import create_task
from serverish.base.iterators import AsyncDictItemsIter

from oca_monitor.utils import get_time_ago_text
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit, QLineEdit
from PyQt6 import QtCore, QtGui
from PyQt6.QtCore import Qt
from qasync import asyncSlot
from PyQt6.QtGui import QPixmap
from oca_monitor.image_display import ImageDisplay
from oca_monitor.utils import a_read_file


logger = logging.getLogger(__name__.rsplit('.')[-1])


class TelescopeOfp(QWidget):

    LC_HEIGHT = 150
    INFO_HEIGHT = 75
    JSON_FILE_NAME = 'thumbnail_display.json'
    PNG_FILE_NAME = 'thumbnail_display.png'
    LC_FILE_NAME = 'last_light_curve_chart_display.png'
    REPAINT_INFO_E_INTERVAL = 0.5 # seconds
    OBSERV_AGO_WARN_TIME = 1800
    OBSERV_AGO_WARN_COLOR = 'yellow'
    OBSERV_AGO_BAD_TIME = 3600
    OBSERV_AGO_BAD_COLOR = 'red'

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
        self.info_e_txt: str = ''
        self.info_e_last_date_obs: Optional[datetime.datetime] = None
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
        self.info_e.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.info_e.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.info_e.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.info_e.setFixedHeight(self.INFO_HEIGHT)
        self.info_e.setStyleSheet(f"background-color: {color}; color: white")
        # self.set_pix_maps()

        self.layout.addWidget(self.fits_pic)
        self.layout.addWidget(self.info_e)
        self.layout.addWidget(self.curve_pix)


        QtCore.QTimer.singleShot(0, self.async_init)
        # logger.info(f"TelescopeOfp {self.tel} UI setup done")

    async def repaint_info_e(self) -> None:
        while True:
            try:
                bkg_color = self.main_window.nats_cfg["config"]["telescopes"][self.tel]["observatory"]["style"]["color"]
                if bkg_color == '#67F4F5':
                    text_color = 'black'
                else:
                    text_color = 'white'
            except (LookupError, TypeError):
                bkg_color = 'gray'
                text_color = 'black'

            ago_txt = await get_time_ago_text(date=self.info_e_last_date_obs)

            if ago_txt is not None:
                if self.OBSERV_AGO_BAD_TIME > ago_txt['total_sec'] >= self.OBSERV_AGO_WARN_TIME:
                    t_col = self.OBSERV_AGO_WARN_COLOR
                elif ago_txt['total_sec'] >= self.OBSERV_AGO_BAD_TIME:
                    t_col = self.OBSERV_AGO_BAD_COLOR
                else:
                    t_col = text_color
                txt = f" <p style='font-size: 15pt;'>"
                txt +=  f"<span style='color: {t_col}; font-weight: bold;'> [{ago_txt['txt']}] </span> "
                txt += self.info_e_txt
                self.info_e.clear()
                self.info_e.setStyleSheet(f"background-color: {bkg_color}; color: {text_color}")
                self.info_e.setHtml(txt)
                self.repaint()

            await asyncio.sleep(self.REPAINT_INFO_E_INTERVAL)

    async def info_display(self) -> None:

        """
        {"fits_id": "devc_1055_85806", "telescope": "dev", "date_obs": "2026-01-15T08:35:36.703790",
         "imagetyp": "science", "object": "W_Tuc", "loop": 1, "nloops": 1, "filter": "B", "exptime": 1.0,
          "min": 269.0, "max": 64479.0, "mean": 338.7979793548584, "median": 338.0, "rms": 162.9519195516698,
           "sigma_quantile": 10.0, "fwhm_x": 3.066431900922051, "fwhm_y": 3.553626041588144,
            "fwhm": 3.3100289712550977,
             "objects": {
             "w_tuc": {"ra": 14.540435, "dec": -63.395658, "per": 0.6422382, "hjd0": null, "mode": "lc",
              "B": null, "V": null, "Rc": null, "Ic": null, "u": null, "g": null, "r": null, "i": null,
               "z": null, "x_pix": 943.0337994128126, "y_pix": 867.0749773159023, "in_frame": 1,
                "naxis_1": 2048, "naxis_2": 2048, "x_edge_dist": 943.0337994128126, "y_edge_dist": 867.0749773159023,
                 "moon_separation": 77.31975147253051, "adu_max": 30479.0, "adu_aperture_rad": 6}}}
        """

        file_content = await a_read_file(path=os.path.join(self.dir, self.JSON_FILE_NAME), raise_err=False)
        if file_content:
            try:
                content = json.loads(file_content)
            except json.decoder.JSONDecodeError as e:
                logger.warning(f"Can not decode file {self.JSON_FILE_NAME}: {e}")
                content = None
        else:
            content = None

        txt = ""
        if content:
            try:
                date = content["date_obs"]
                obj = content["object"]
                type = content["imagetyp"]
                filter_ = content["filter"]
                n = content["loop"]
                n_dit = content["nloops"]
                exptime = content["exptime"]

                txt = txt + f"<i>{type}</i> <b>{obj}</b>"
                txt = txt + f" | {n}/{n_dit} <b>{filter_}</b>  <b>{exptime:.1f}</b>s |<br>"
            except (ValueError, LookupError) as e:
                logger.warning(f"Can not parse data: {e}")
                return
            try:
                self.info_e_last_date_obs = datetime.datetime.fromisoformat(date).replace(tzinfo=datetime.timezone.utc)
            except (ValueError, TypeError):
                return



            try:
                fwhm_x = content["fwhm_x"]
                fwhm_y = content["fwhm_y"]
                arr_min = content["min"]
                arr_max = content["max"]
                mean = content["mean"]
                median = content["median"]
                scale = content["scale"]

                txt = txt + (
                    f'<font size="3">| fwhm x:{fwhm_x * scale:.1f} y:{fwhm_y * scale:.1f} min:{arr_min:.0f}'
                    f' max:{arr_max:.0f} mean:{mean:.0f} median:{median:.0f}</font>|<br>')

            except (ValueError, LookupError) as e:
                arr_min = content["min"]
                arr_max = content["max"]
                mean = content["mean"]
                median = content["median"]

                txt = txt + (
                    f'<font size="3">| min:{arr_min:.0f}'
                    f' max:{arr_max:.0f} mean:{mean:.0f} median:{median:.0f}</font>|<br>')

            try:
                if len(content["objects"]) > 0:
                    txt = txt + f'|'
                    async for obj_name, obj_data in AsyncDictItemsIter(content["objects"]):
                        adu_max = obj_data["adu_max"]
                        moon_sep = obj_data["moon_separation"]

                        txt = txt + (f' <font size="3"><b>{obj_name}</b>'
                                     f' max-adu:{adu_max:.0f} moon-dist:{moon_sep:.0f} </font>|')

            except (ValueError, LookupError) as e:
                pass

            txt = txt + f" </p>"

        self.info_e_txt = txt

    @staticmethod
    async def image_instance(image_path: str) -> Any:
        image_instance = QPixmap(image_path)
        if image_instance.isNull():
            return None
        else:
            return QPixmap(image_path)

    async def image_display(self, object_to_display: Optional[QPixmap]) -> None:
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

        await create_task(self.repaint_info_e(), "repaint_info_e")

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


widget_class = TelescopeOfp
