import logging
import os
import re
import subprocess
import time

from PyQt6.QtWidgets import  QWidget, QHBoxLayout, QTextEdit
from PyQt6.QtCore import QTimer, Qt

from qasync import asyncSlot
from serverish.base import dt_ensure_datetime
from serverish.base.task_manager import create_task_sync, create_task
from serverish.messenger import get_reader


logger = logging.getLogger(__name__.rsplit('.')[-1])

# etykieta komunikatu z message.*.*.*.notice -> (dzwiek z sounds/ - plik, krotka plikow granych po kolei (liczba w
# krotce = przerwa w sekundach) albo None, kolor tekstu). Klasy (2026-11-02,
# knowledge-base: Operator sound alerts): notification = obserwator ma sprawdzic, czy wszystko ok; WEATHER WARNING =
# ograniczenia rosna; WEATHER ALERT = zamknac wszystko; WEATHER LEVEL DOWN = krok w dol (weather_overwatch);
# SYSTEM ALERT = zagrozony sprzet (bateria, temperatura serwerowni / baterii / pomieszczenia elektrycznego)
NOTIFICATION = "notification_computerbeep_12.wav"
LABEL_SOUNDS = {
    "INFO": (None, Qt.GlobalColor.gray),
    "PING": ("ping_tos_alien_sound_4.wav", Qt.GlobalColor.darkYellow),
    "PROGRAM STOP": ("stop_alert07.wav", Qt.GlobalColor.gray),
    "PROGRAM BELL": ("bell_romulan_alarm.wav", Qt.GlobalColor.gray),
    "PROGRAM ERROR": ("error_tone.wav", Qt.GlobalColor.red),
    "WEATHER ALERT": ("weather_alarm_klingon_alert.wav", Qt.GlobalColor.red),
    "WEATHER WARNING": ("warning_weather_alert09.wav", Qt.GlobalColor.darkYellow),
    "WEATHER LEVEL DOWN": ("level_down.wav", Qt.GlobalColor.darkGreen),
    "SUN WARNING": ("alert23.wav", Qt.GlobalColor.darkYellow),
    "EVENT": ("gong.wav", Qt.GlobalColor.darkBlue),     # eventy conditions_overwatch (Slonce +5 / -18, ut, ...);
                                                        # pole "sound" komunikatu zamienia dzwiek
    "SYSTEM ALERT": (("mixkit-facility-alarm-908.wav", 3, "mixkit-facility-alarm-908.wav"), Qt.GlobalColor.red),   # 2x    # bateria, serwerownia, ... (weather_overwatch)
    "FWHM WARNING": (NOTIFICATION, Qt.GlobalColor.darkYellow),
    "ZERO POINT WARNING": (NOTIFICATION, Qt.GlobalColor.darkYellow),
    "CLOUDS INFO": (NOTIFICATION, Qt.GlobalColor.darkYellow),
}
DEFAULT_SOUND = (NOTIFICATION, Qt.GlobalColor.gray)
# dzwieki eventow (pole "sound"): najpierw wspolny katalog conditions_overwatch (ten sam wybieraja TOI i overwatch),
# potem sounds/ w repo; nazwa pliku bez sciezki
SHARED_SOUNDS = "/data/misc/oca_overwatch/sounds"
SOUND_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_. -]*$")


def sound_path(name):
    shared = os.path.join(SHARED_SOUNDS, name)
    return shared if os.path.isfile(shared) else f"{os.getcwd()}/sounds/{name}"


def event_sound(data):
    """Dzwiek z pola "sound" komunikatu (EVENT), jesli to sama nazwa istniejacego pliku; inaczej None"""
    name = data.get("sound")
    if not isinstance(name, str) or not SOUND_NAME.match(name) or ".." in name:
        return None
    return name if os.path.isfile(sound_path(name)) else None


def play(sound):
    """Gra plik albo krotke plikow po kolei w tle (Popen nie blokuje GUI). Liczba w krotce = przerwa w sekundach:
    wtedy przez sh (aplay i sleep na zmiane, sciezki jako argumenty), bez przerw jedno aplay z kilkoma plikami"""
    parts = (sound,) if isinstance(sound, str) else tuple(sound)
    if not any(isinstance(p, (int, float)) for p in parts):
        subprocess.Popen(["aplay"] + [sound_path(p) for p in parts])
        return
    script, args = [], []
    for p in parts:
        if isinstance(p, (int, float)):
            script.append(f"sleep {float(p):g}")
        else:
            args.append(sound_path(p))
            script.append(f'aplay "${len(args)}"')
    subprocess.Popen(["sh", "-c", "; ".join(script), "sh"] + args)

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
            r = get_reader('message.*.*.*.notice', deliver_policy='new')     # komunikaty wszystkich nadawcow (TOI, overwatche), od 2026-11-10
            async for data, meta in r:
                try:
                    label = data["label"]
                    sound, c = LABEL_SOUNDS.get(label, DEFAULT_SOUND)
                    sound = event_sound(data) or sound
                    if sound:
                        play(sound)


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