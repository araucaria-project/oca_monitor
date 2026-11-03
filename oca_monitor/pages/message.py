import logging
import os
import subprocess
import time

from PyQt6.QtWidgets import  QWidget, QHBoxLayout, QTextEdit
from PyQt6.QtCore import QTimer, Qt

from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import get_reader


logger = logging.getLogger(__name__.rsplit('.')[-1])

# etykieta komunikatu z tic.status.ocm.messages -> (dzwiek z sounds/ - plik, krotka plikow granych po kolei albo None,
# kolor tekstu). Klasy (2026-11-02,
# knowledge-base: Operator sound alerts): notification = obserwator ma sprawdzic, czy wszystko ok; WEATHER WARNING =
# ograniczenia rosna; WEATHER ALERT = zamknac wszystko; WEATHER LEVEL DOWN = krok w dol (weather_overwatch);
# SYSTEM ALERT = zagrozony sprzet (bateria, temperatura serwerowni / baterii / pomieszczenia elektrycznego)
NOTIFICATION = "notification_computerbeep_12.wav"
LABEL_SOUNDS = {
    "INFO": (None, Qt.GlobalColor.gray),
    "PING": ("ping_tos_alien_sound_4.wav", Qt.GlobalColor.darkYellow),
    "PROGRAM STOP": ("stop_alert07.wav", Qt.GlobalColor.gray),
    "PROGRAM BELL": ("bell_romulan_alarm.wav", Qt.GlobalColor.gray),
    "PROGRAM ERROR": (("error_mixkit-click-1110.wav", "error_fart.wav"), Qt.GlobalColor.red),     # najpierw click
    "WEATHER ALERT": ("weather_alarm_klingon_alert.wav", Qt.GlobalColor.red),
    "WEATHER WARNING": ("warning_weather_alert09.wav", Qt.GlobalColor.darkYellow),
    "WEATHER LEVEL DOWN": ("level_down.wav", Qt.GlobalColor.darkGreen),
    "SUN WARNING": ("alert23.wav", Qt.GlobalColor.darkYellow),
    "SYSTEM ALERT": ("mixkit-facility-alarm-908.wav", Qt.GlobalColor.red),    # bateria, serwerownia, ... (weather_overwatch)
    "FWHM WARNING": (NOTIFICATION, Qt.GlobalColor.darkYellow),
    "ZERO POINT WARNING": (NOTIFICATION, Qt.GlobalColor.darkYellow),
    "CLOUDS INFO": (NOTIFICATION, Qt.GlobalColor.darkYellow),
}
DEFAULT_SOUND = (NOTIFICATION, Qt.GlobalColor.gray)

class MessageWidget(QWidget):
    def __init__(self, main_window, subject='telemetry.weather.davis', vertical_screen = False, **kwargs):
        super().__init__()
        self.parent = main_window
        self.subject = subject
        self.vertical = bool(vertical_screen)
        self.initUI()
        self.parent.sound_page = self
        self.one_sun_sound = True
        self.one_weather_warning = True
        self.one_weather_stop = True
        QTimer.singleShot(0, self.async_init)
        #self.script_location = os.path.dirname(os.path.abspath(__file__))
        logger.info(f"MessageWidget init setup done")

    @asyncSlot()
    async def async_init(self):
        await create_task(self.reader_ocm_messages(), "nats_ocm_message_reader")

    def initUI(self,):
        self.layout = QHBoxLayout(self)
        self.info_e = QTextEdit()

        self.layout.addWidget(self.info_e)
        # logger.info(f"MessageWidget UI setup done")


    async def reader_ocm_messages(self):
            r = get_reader(f'tic.status.ocm.messages', deliver_policy='new')
            async for data, meta in r:
                try:
                    label = data["label"]
                    sound, c = LABEL_SOUNDS.get(label, DEFAULT_SOUND)
                    if sound:       # aplay gra kilka plikow po kolei, Popen nie blokuje GUI
                        files = (sound,) if isinstance(sound, str) else sound
                        subprocess.Popen(["aplay"] + [f"{os.getcwd()}/sounds/{f}" for f in files])


                    # if label == "TOI RESPONDER":
                    #     c = QtCore.Qt.darkGreen
                    # if label == "PLANRUNNER":
                    #     c = QtCore.Qt.darkGray

                    if data.get("test"):    # sound test from TOI's PING window: the sound, but not the alarm colour
                        c = Qt.GlobalColor.gray
                    txt = f'{data["ut"]} [{data["user"]}] {data["info"]}'
                    self.info_e.setTextColor(c)
                    self.info_e.append(txt)
                    self.info_e.repaint()


                except Exception as e:
                    logger.warning(f'{e} {data}')


widget_class = MessageWidget