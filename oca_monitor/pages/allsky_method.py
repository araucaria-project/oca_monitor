import asyncio
import datetime
import logging

from PyQt6 import QtCore
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSizePolicy
from qasync import asyncSlot
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

logger = logging.getLogger(__name__.rsplit('.')[-1])

STATE_COLORS = {'clear': '#4caf50', 'veil': '#ffc107', 'thin': '#ffc107', 'cloudy': '#ff7043', 'overcast': '#e53935',
                'twilight': '#90caf9'}     # twilight: Sun above -18 deg, clouds not measured (blue as TOI's UT)
LEGENDS = {
    'stars': 'stars a clear sky would show, ringed: green seen, red missing (large = sure ones); '
             'outlined yellow = possible cloud, red = cloud that hides everything; dashed yellow circle = veil; cyan area = Moon',
    'diff': 'change since the previous frame, coloured over the frame: red brighter, blue darker; '
            'outlined yellow = changing region, black = strong change; dashed yellow circle = veil; cyan area = Moon',
}
MAX_AGE = 600       # s; an older picture is shown as not current (day, service down)


class AllskyMethodWidget(QWidget):
    """One of the two method pictures of allsky_overwatch (kind = "stars" or "diff"): the newest picture the service
    wrote for its last frame (path in the `files` of its clouds message), with the sky state and a short legend."""

    def __init__(self, main_window, kind='stars', clouds_subject='tic.status.ocm.allsky_overwatch.clouds',
                 vertical_screen=False, **kwargs):
        super().__init__()
        if kind not in LEGENDS:
            raise ValueError(f'kind must be one of {list(LEGENDS)}')
        self.main_window = main_window
        self.kind = kind
        self.clouds_subject = clouds_subject
        self.vertical = bool(vertical_screen)
        self.pixmap = None
        self.data = None
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
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.show_state)        # the age grows without new messages
        self.timer.start(30000)

    def show_state(self):
        d = self.data
        if not d or not d.get('time'):
            self.state.setText('--')
            self.state.setStyleSheet('font-size: 14pt; color: #bdbdbd;')
            return
        age = (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(d['time'])).total_seconds()
        state = 'twilight' if d.get('twilight') else 'veil' if d.get('veil') and d.get('state') == 'thin' else d.get('state')
        text = f"{state}  {d['time'][11:16]} UT"
        if age > MAX_AGE:
            text += f'  (not current: {age / 60:.0f} min old)'
        self.state.setText(text)
        color = STATE_COLORS.get(state, '#bdbdbd') if age <= MAX_AGE else '#bdbdbd'
        self.state.setStyleSheet(f'font-size: 14pt; color: {color};')

    def show_image(self):
        if self.pixmap is None or self.pixmap.isNull():
            return
        self.image.setPixmap(self.pixmap.scaled(self.image.width(), self.image.height(),
                                                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                                                QtCore.Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_image()

    async def clouds_reader(self):
        try:
            reader = get_reader(self.clouds_subject, deliver_policy='last')
            async for data, meta in reader:
                path = (data.get('files') or {}).get(self.kind)
                self.data = data
                if path:
                    pixmap = QPixmap(path)       # the service writes it before the message (temporary file + rename)
                    if not pixmap.isNull():
                        self.pixmap = pixmap
                        self.show_image()
                self.show_state()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'allsky method reader {self.clouds_subject} failed: {e}')

    @asyncSlot()
    async def async_init(self):
        await create_task(self.clouds_reader(), f'allsky_method_{self.kind}')


widget_class = AllskyMethodWidget
