import asyncio
import datetime
import logging

from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from qasync import asyncSlot
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader, single_read

logger = logging.getLogger(__name__.rsplit('.')[-1])

STATE_COLORS = {'clear': '#4caf50', 'veil': '#ffc107', 'thin': '#ffc107', 'cloudy': '#ff7043', 'overcast': '#e53935',
                'twilight': '#90caf9'}     # twilight: Sun above -18 deg, clouds not measured (blue as TOI's UT)
LEGENDS = {
    'stars': 'stars a clear sky would show, ringed: green seen, red missing (large = sure ones); '
             'outlined yellow = possible cloud, red = cloud that hides everything; dashed yellow circle = veil; cyan area = Moon',
    'diff': 'change since the previous frame, coloured over the frame: red brighter, blue darker; '
            'outlined yellow = changing region, red = strong change; dashed yellow circle = veil; cyan area = Moon',
}
MAX_AGE = 600       # s; an older picture is shown as not current (day, service down)
# animation like the Clouds / Allsky tabs (ImageDisplay over lastimage{4,3,2,}.jpg): the last FRAMES pictures, oldest
# first, CASCADE_MS each, the newest held PAUSE_MS longer. allsky_overwatch keeps the pictures of its last 10 frames
FRAMES = 4
CASCADE_MS = 750
PAUSE_MS = 1250
HISTORY_MIN = 15    # minutes of clouds messages read at start, to fill the animation at once


class AllskyMethodWidget(QWidget):
    """One of the two method pictures of allsky_overwatch (kind = "stars" or "diff"), animated over its last FRAMES
    frames like the Clouds tab (paths in the `files` of the clouds messages), with the sky state and time of the frame
    shown and a short legend."""

    def __init__(self, main_window, kind='stars', clouds_subject='data.overwatch.oca.allsky.clouds',
                 vertical_screen=False, **kwargs):
        super().__init__()
        if kind not in LEGENDS:
            raise ValueError(f'kind must be one of {list(LEGENDS)}')
        self.main_window = main_window
        self.kind = kind
        self.clouds_subject = clouds_subject
        self.vertical = bool(vertical_screen)
        self.frames = []        # [(clouds message, QPixmap)], oldest first, at most FRAMES
        self.idx = 0            # frame shown
        self.scaled = {}        # (frame name, w, h) -> scaled pixmap of the frames kept
        self.initUI()
        logger.info(f'AllskyMethodWidget ({kind}) init setup done')

    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.state = QLabel('--')
        self.state.setStyleSheet('font-size: 14pt; color: #bdbdbd;')
        self.image = QLabel()
        self.image.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(100, 100)
        # the picture follows the label, not the other way round (a pixmap would otherwise grow the window)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.legend = QLabel(LEGENDS[self.kind])
        self.legend.setWordWrap(True)
        self.legend.setStyleSheet('font-size: 9pt; color: #9e9e9e;')
        self.layout.addWidget(self.state)
        self.layout.addWidget(self.image, 1)
        self.layout.addWidget(self.legend)
        QtCore.QTimer.singleShot(0, self.async_init)
        self.anim = QtCore.QTimer(self)
        self.anim.setSingleShot(True)
        self.anim.timeout.connect(self.step)
        self.anim.start(CASCADE_MS)

    def step(self):
        """Next frame of the animation (the age of the newest also grows without new messages)"""
        if self.frames:
            self.idx = (self.idx + 1) % len(self.frames)
        self.show_frame()
        last = not self.frames or self.idx == len(self.frames) - 1
        self.anim.start(CASCADE_MS + (PAUSE_MS if last else 0))

    def show_frame(self):
        if not self.frames:
            self.state.setText('--')
            self.state.setStyleSheet('font-size: 14pt; color: #bdbdbd;')
            return
        self.idx = min(self.idx, len(self.frames) - 1)
        d, pixmap = self.frames[self.idx]
        newest = self.frames[-1][0]
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(newest['time'])).total_seconds()
        state = 'twilight' if d.get('twilight') else 'veil' if d.get('veil') and d.get('state') == 'thin' else d.get('state')
        text = f"{state}  {d['time'][11:16]} UT"
        if age > MAX_AGE:
            text += f'  (not current: {age / 60:.0f} min old)'
        self.state.setText(text)
        color = STATE_COLORS.get(state, '#bdbdbd') if age <= MAX_AGE else '#bdbdbd'
        self.state.setStyleSheet(f'font-size: 14pt; color: {color};')
        w, h = self.image.width(), self.image.height()
        key = (d.get('frame'), w, h)
        if key not in self.scaled:
            self.scaled[key] = pixmap.scaled(w, h, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                             QtCore.Qt.TransformationMode.SmoothTransformation)
        self.image.setPixmap(self.scaled[key])

    def add_frame(self, data):
        path = (data.get('files') or {}).get(self.kind)
        if not path or not data.get('time') or any(f[0].get('frame') == data.get('frame') for f in self.frames):
            return
        pixmap = QPixmap(path)       # the service writes it before the message (temporary file + rename)
        if pixmap.isNull():
            return
        self.frames = sorted(self.frames + [(data, pixmap)], key=lambda f: f[0]['time'])[-FRAMES:]
        kept = {f[0].get('frame') for f in self.frames}
        self.scaled = {k: v for k, v in self.scaled.items() if k[0] in kept}

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.scaled = {}
        self.show_frame()

    async def clouds_reader(self):
        try:        # the last picture at least, also by day when the history window is empty (shown as not current)
            data, meta = await asyncio.wait_for(single_read(self.clouds_subject), timeout=10)
            self.add_frame(data)
        except (asyncio.CancelledError, KeyboardInterrupt):
            raise
        except Exception as e:
            logger.info(f'allsky method: no last message on {self.clouds_subject}: {e!r}')
        try:
            t0 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=HISTORY_MIN)
            reader = get_reader(self.clouds_subject, deliver_policy='by_start_time', opt_start_time=t0)
            async for data, meta in reader:
                self.add_frame(data)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'allsky method reader {self.clouds_subject} failed: {e}')

    @asyncSlot()
    async def async_init(self):
        await create_task(self.clouds_reader(), f'allsky_method_{self.kind}')


widget_class = AllskyMethodWidget
