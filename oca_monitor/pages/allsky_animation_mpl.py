import asyncio
import datetime
import logging
import os
from typing import Any

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import QTimer
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.patches import Arrow, Polygon
import matplotlib.pyplot as plt
import math

from qasync import asyncSlot
from serverish.base.task_manager import create_task
from serverish.messenger import get_reader

from oca_monitor.image_display import ImageDisplay

logger = logging.getLogger(__name__.rsplit('.')[-1])

# Camera model of the allsky frames (lastimage*.jpg are the archive frames): (x0, y0, theta, k1, k2),
# z = 90 - alt, r = k1 z + k2 z^3, x = x0 + r sin(az + theta), y = y0 - r cos(az + theta). allsky_overwatch
# publishes it with the segment geometry; this is the default until that message arrives.
CAMERA_PARAMS = (610.88, 624.52, -9.094, 6.21458, -3.7e-05)
STATE_COLORS = {'clear': '#4caf50', 'thin': '#ffc107', 'cloudy': '#ff7043', 'overcast': '#bdbdbd'}


class AllskyAnimationMplWidget(QWidget):
    def __init__(self, main_window, allsky_dir='/data/misc/allsky/', vertical_screen=False,
                 clouds_subject='tic.status.ocm.allsky_overwatch.clouds',
                 segments_subject='tic.status.ocm.allsky_overwatch.segments', **kwargs):
        super().__init__()
        self.main_window = main_window
        self.dir = allsky_dir
        self.clouds_subject = clouds_subject
        self.segments_subject = segments_subject
        self.camera = CAMERA_PARAMS
        self.segments = None        # segment geometry from allsky_overwatch: {"star": [...], "diff": [...]}
        self.clouds = {}            # (file size, mtime) -> allsky_overwatch message of that frame (last few)
        self.unmatched = set()      # (file size, mtime) of frames drawn before their message came
        self.display = None
        self.freq = 500
        self.vertical = bool(vertical_screen)
        self.counter = 0
        self.initUI()
        logger.info(f"AllskyAnimationMplWidget init setup done")

    def initUI(self):
        self.layout = QVBoxLayout(self)
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.layout.addWidget(self.canvas, 1)
        QTimer.singleShot(0, self.async_init)
        # logger.info(f"AllskyAnimationMplWidget UI setup done")

    def sky_xy(self, alt, az):
        """Pixel (x, y) of a sky position (alt, az in deg, az from N through E) on the allsky frame."""
        x0, y0, theta, k1, k2 = self.camera
        z = 90. - alt
        r = k1 * z + k2 * z ** 3
        a = math.radians(az + theta)
        return x0 + r * math.sin(a), y0 - r * math.cos(a)

    def segment_polygon(self, seg, step=3.):
        """Pixel outline of a sky segment (alt_lo..alt_hi x az_lo..az_hi), arcs sampled every `step` deg."""
        n = max(int((seg['az_hi'] - seg['az_lo']) / step), 1)
        azs = [seg['az_lo'] + (seg['az_hi'] - seg['az_lo']) * i / n for i in range(n + 1)]
        return [self.sky_xy(seg['alt_lo'], a) for a in azs] + [self.sky_xy(seg['alt_hi'], a) for a in reversed(azs)]

    @staticmethod
    def same_frame(a, b):
        """(size, mtime) of an archive frame and of a lastimage*.jpg: the same bytes, written a few s later."""
        return a[0] == b[0] and abs(a[1] - b[1]) < 60

    def frame_clouds(self, image_path):
        """allsky_overwatch message of this frame (matched by file size and mtime), or None."""
        try:
            st = os.stat(image_path)
        except OSError:
            return None
        frame = (st.st_size, st.st_mtime)
        for key, data in self.clouds.items():
            if self.same_frame(key, frame):
                return data
        self.unmatched = {f for f in self.unmatched if abs(f[1] - frame[1]) < 3600}     # no messages by day: keep it small
        self.unmatched.add(frame)
        return None

    def draw_clouds(self, ax, image_path):
        """Segments flagged by allsky_overwatch on this frame: red = expected stars missing, orange = moving
        cloud; white outlines = the star segments; the sky state in the corner. In twilight the star segments are
        not filled: the expected stars assume a dark sky."""
        data = self.frame_clouds(image_path)
        if data is None or self.segments is None:
            return
        layers = [('diff', 'moving', 'orange')] + ([] if data['twilight'] else [('star', 'missing', 'red')])
        for kind, flag, color in layers:
            for seg, flagged in zip(self.segments[kind], data['segments'][kind][flag]):
                if flagged:
                    ax.add_patch(Polygon(self.segment_polygon(seg), closed=True, facecolor=color, alpha=0.25, edgecolor='none'))
        for seg in self.segments['star']:
            ax.add_patch(Polygon(self.segment_polygon(seg), closed=True, fill=False, edgecolor='white', alpha=0.3, lw=0.6))
        state = data['state'] + (' (twilight)' if data['twilight'] else '')
        ax.text(1230, 30, f"{state}  {data['time'][11:16]} UT", color=STATE_COLORS.get(data['state'], 'white'),
                fontsize=12, ha='right')

    def calc_wind_arrow(self, x_0, y_0, r, r_prim):
        pi = 3.14159
        try:
            winddir = self.main_window.winddir
            x = x_0 - r * math.cos((270. - winddir) * pi / 180.)
            y = y_0 + r * math.sin((270. - winddir) * pi / 180.)
            x_prim = x_0 - r_prim * math.cos((270. - winddir) * pi / 180.)
            y_prim = y_0 + r_prim * math.sin((270. - winddir) * pi / 180.)

        except:
            winddir = 180.
            x = x_0 - r * math.cos((270. - winddir) * pi / 180.)
            y = y_0 + r * math.sin((270. - winddir) * pi / 180.)
            x_prim = x_0 - r_prim * math.cos((270. - winddir) * pi / 180.)
            y_prim = y_0 + r_prim * math.sin((270. - winddir) * pi / 180.)

        return x, y, x_prim - x, y_prim - y

    # def update(self):
    #     lista = os.popen('ls -tr '+self.dir+'lastimage*.jpg').read().split('\n')[:-1]
    #     if len(lista) > 0:
    #         try:
    #         #if True:
    #             self.figure.clf()
    #             ax = self.figure.add_subplot(111)
    #             image = plt.imread(lista[self.counter])
    #             ax.imshow(image)
    #
    #             try:
    #                 for t in self.main_window.telescope_names:
    #                     if self.main_window.telescopes_alt and self.main_window.telescopes_az:
    #                         if t in self.main_window.telescopes_alt.keys() and t in self.main_window.telescopes_az.keys():
    #                             x,y = self.calc_tel_xy(625,625,float(self.main_window.telescopes_alt[t]),float(self.main_window.telescopes_az[t]))
    #                             if t == "wk06":
    #                                 ax.plot(x,y,"o", color='#14AD4E')
    #                                 ax.text(10,30,"wk06", color='#14AD4E', fontsize = 12)
    #                             if t == "zb08":
    #                                 ax.plot(x, y, "o", color='#0082E8')
    #                                 ax.text(10, 70, "zb08", color='#0082E8', fontsize=12)
    #                             if t == "jk15":
    #                                 ax.plot(x, y, "o", color='#67F4F5')
    #                                 ax.text(10, 110, "jk15", color='#67F4F5', fontsize=12)
    #             except Exception as e:
    #                 print(f"EXCEPTION 32: {e}")
    #
    #
    #             x_arrow,y_arrow,dx_arrow,dy_arrow = self.calc_wind_arrow(600,600,550.,500.)
    #             wind_arrow = Arrow(x_arrow,y_arrow,dx_arrow,dy_arrow,width=20.,color="magenta")
    #             ax.add_artist(wind_arrow)
    #             ax.axis('off')
    #
    #             self.canvas.draw()
    #
    #             self.counter = self.counter + 1
    #             if self.counter == len(lista):
    #                 self.counter = 0
    #         except:
    #             pass
    #
    #
    #
    #     QTimer.singleShot(self.freq, self.update)
    #     self._change_update_time()
    #
    # def _change_update_time(self):
    #     self.freq = 2000

    async def image_instance(self, image_path: str) -> Any:

        figure = Figure(facecolor='black')
        figure.clf()
        ax = figure.add_subplot(111)
        image = plt.imread(image_path)
        ax.imshow(image)

        try:
            for t in self.main_window.telescope_names:
                if self.main_window.telescopes_alt and self.main_window.telescopes_az:
                    if t in self.main_window.telescopes_alt.keys() and t in self.main_window.telescopes_az.keys():
                        x, y = self.sky_xy(float(self.main_window.telescopes_alt[t]),
                                           float(self.main_window.telescopes_az[t]))
                        if t == "wk06":
                            ax.plot(x, y, "o", color='#14AD4E')
                            ax.text(10, 30, "wk06", color='#14AD4E', fontsize=12)
                        if t == "zb08":
                            ax.plot(x, y, "o", color='#0082E8')
                            ax.text(10, 70, "zb08", color='#0082E8', fontsize=12)
                        if t == "jk15":
                            ax.plot(x, y, "o", color='#67F4F5')
                            ax.text(10, 110, "jk15", color='#67F4F5', fontsize=12)
        except Exception as e:
            print(f"EXCEPTION 32: {e}")

        try:
            self.draw_clouds(ax, image_path)
        except Exception as e:
            logger.warning(f'allsky clouds overlay failed: {e!r}')

        x_arrow, y_arrow, dx_arrow, dy_arrow = self.calc_wind_arrow(600, 600, 550., 500.)
        wind_arrow = Arrow(x_arrow, y_arrow, dx_arrow, dy_arrow, width=20., color="magenta")
        ax.add_artist(wind_arrow)
        ax.axis('off')

        figure.tight_layout()
        canvas = FigureCanvas(figure)

        return canvas

    async def image_display(self, object_to_display: Any):

        self.layout.removeWidget(self.canvas)
        self.canvas.setParent(None)
        self.canvas = object_to_display
        self.layout.insertWidget(0, object_to_display)
        self.canvas.draw()

    async def segments_reader(self):
        try:
            reader = get_reader(self.segments_subject, deliver_policy='last')
            async for data, meta in reader:
                try:
                    self.segments = {'star': data['star'], 'diff': data['diff']}
                    self.camera = tuple(float(p) for p in data['camera']['params'])
                except (LookupError, TypeError, ValueError):
                    continue
                if self.display:
                    self.display.force_refresh()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'allsky reader {self.segments_subject} failed: {e}')

    async def clouds_reader(self):
        try:
            t0 = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=15)
            reader = get_reader(self.clouds_subject, deliver_policy='by_start_time', opt_start_time=t0)
            async for data, meta in reader:
                try:
                    frame = (int(data['size']), float(data['mtime']))
                except (LookupError, TypeError, ValueError):
                    continue
                self.clouds[frame] = data
                for key in sorted(self.clouds, key=lambda f: f[1])[:-10]:
                    del self.clouds[key]
                # a frame already drawn without its message: draw the frames again
                drawn = [f for f in self.unmatched if self.same_frame(frame, f)]
                if drawn:
                    self.unmatched.difference_update(drawn)
                    if self.display:
                        self.display.force_refresh()
        except (asyncio.CancelledError, asyncio.TimeoutError):
            raise
        except Exception as e:
            logger.warning(f'allsky reader {self.clouds_subject} failed: {e}')

    @asyncSlot()
    async def async_init(self):
        logger.info('Starting allsky display.')
        await create_task(self.segments_reader(), 'allsky_segments')
        await create_task(self.clouds_reader(), 'allsky_clouds')
        self.display = display = ImageDisplay(
            name='allsky', images_dir=self.dir, image_display_clb=self.image_display,
            image_instance_clb=self.image_instance, images_prefix='lastimage',
            image_cascade_sec=0.75, image_pause_sec=1.25, refresh_list_sec=10, mode='update_files',
            sort_reverse=True
        )
        await display.display_init()


widget_class = AllskyAnimationMplWidget