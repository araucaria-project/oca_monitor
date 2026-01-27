import asyncio
import copy
import datetime
import logging
import random
from dataclasses import dataclass
from typing import Union, List, Optional

from PyQt6.QtWidgets import  QWidget, QHBoxLayout, QTextEdit
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor
from qasync import asyncSlot
from serverish.base import create_task, dt_from_array
from serverish.base.iterators import AsyncListIter
from serverish.messenger import get_reader

from oca_monitor.utils import get_time_ago_text

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum):
        pass

logger = logging.getLogger(__name__.rsplit('.')[-1])


class LogLevel(StrEnum):
    debug = 'DEBUG'
    info = 'INFO'
    notice = 'NOTICE'
    warning = 'WARNING'
    major = 'MAJOR'

    @property
    def color(self) -> str:
        return {
            LogLevel.debug: 'gray',
            LogLevel.info: 'green',
            LogLevel.notice: 'yellow',
            LogLevel.warning: 'orange',
            LogLevel.major: 'red',
        }[self]

    @property
    def dim_color(self) -> str:
        return {
            LogLevel.debug: "#4f4f4f",  # darker gray
            LogLevel.info: "#1f5f2e",  # darker green
            LogLevel.notice: "#d48806",  # darker amber
            LogLevel.warning: "#cc5200",  # darker orange
            LogLevel.major: "#9f1d1d",  # darker red
        }[self]


@dataclass
class Record:
    dt: datetime.datetime
    txt: str
    level: LogLevel
    show_time: bool = True


class QualityLogWidget(QWidget):

    HIDE_RECORD_SEC = 7200
    REMOVE_RECORD_FROM_DATA_SEC = 86000
    REFRESH_LOG_INTERVAL_SEC = 1
    REMOVE_RECORD_FROM_DISPLAY_SEC = 7200
    DIM_RECORD_SEC = 1200

    def __init__(self, main_window, tel: str, subject='telemetry.weather.davis', vertical_screen = False, **kwargs):
        super().__init__()
        self.parent = main_window
        self.vertical = bool(vertical_screen)
        self.layout = QHBoxLayout(self)
        self.info_e = QTextEdit("")
        self.layout.addWidget(self.info_e)
        self.tel = tel
        self.subject = f'tic.journal.{tel}.quality'
        self.log: List[Record] = []
        self.lock: asyncio.Lock = asyncio.Lock()
        # self.displayed: List[Record] = []
        QTimer.singleShot(0, self.async_init)
        logger.info(f"QualityLogWidget {self.tel} init setup done")

    @asyncSlot()
    async def async_init(self):
        await self.display_log_levels()
        await create_task(self.display_records(), "display_records")
        await create_task(self.records_reader(), "records_reader")
        await create_task(self.clean_records(), "records_reader")
        # await create_task(self.add_test_records(), "add_test_records")

    async def add_record(self, dt: datetime.datetime, txt: str, level: LogLevel, show_time: bool = True) -> None:
        async with self.lock:
            self.log.append(Record(dt=dt, txt=txt, level=level, show_time=show_time))

    async def add_test_records(self):
        while True:
            l = [LogLevel.info, LogLevel.notice, LogLevel.warning, LogLevel.major]
            r = random.randint(0, len(l) - 1)
            await self.add_record(
                dt=datetime.datetime.now(datetime.timezone.utc),
                txt=l[r],
                level=l[r]
            )
            await asyncio.sleep(self.REFRESH_LOG_INTERVAL_SEC)

    @staticmethod
    async def get_log_level(level_int: int) -> Optional[LogLevel]:
        val = {
            'DEBUG': LogLevel.debug,
            'NOTICE': LogLevel.notice,
            'INFO': LogLevel.info,
            'WARNING': LogLevel.warning,
            'ERROR': LogLevel.major
        }
        if level_int == 25:
            lev = 'NOTICE'
        else:
            lev = logging.getLevelName(level_int)
        try:
            return val[lev]
        except (LookupError, ValueError, TypeError):
            return None

    async def records_reader(self) -> None:
        r = get_reader(subject=self.subject, deliver_policy='new')
        async for data, meta in r:
            try:
                dt = dt_from_array(data['timestamp'])
                txt = data['message']
                log_level = await self.get_log_level(data['level'])
                if log_level is None:
                    log_level = LogLevel.info
                await self.add_record(
                    dt=dt,
                    txt=txt,
                    level=log_level
                )
            except (LookupError, TypeError, ValueError):
                logger.error(f'Can not read journal quality msg')

    async def clean_records(self) -> None:
        while True:
            to_remove = []
            async for record in AsyncListIter(self.log.copy()):
                ago = await get_time_ago_text(date=record.dt)
                if ago['total_sec'] >= self.REMOVE_RECORD_FROM_DATA_SEC:
                    to_remove.append(record)

            async for record in AsyncListIter(to_remove):
                async with self.lock:
                    self.log.remove(record)
            await asyncio.sleep(self.REMOVE_RECORD_FROM_DISPLAY_SEC)

    # async def add_msg_to_log(self, txt: str, color: Union[Qt.GlobalColor, QColor]):
    #
    #     self.info_e.setTextColor(color)
    #     self.info_e.append(txt)
    #     self.info_e.repaint()

    async def display_records(self) -> None:
        while True:
            _log = copy.deepcopy(self.log)
            _log.reverse()
            txt = ""
            async for record in AsyncListIter(_log):
                ago = await get_time_ago_text(date=record.dt)
                if ago['total_sec'] <= self.HIDE_RECORD_SEC:
                    if ago['total_sec'] > self.DIM_RECORD_SEC:
                        color = record.level.dim_color
                    else:
                        color = record.level.color
                    if record.show_time:
                        txt += (f"<span style='color: {color}; font-weight: bold; opacity: 0.05;'>"
                                f"[{ago['txt']}] {record.txt}</span><br>")
                        # txt += f'[{ago["txt"]}] {record.txt}<br>'
                    else:
                        txt += (f"<span style='color: {color}; font-weight: bold; opacity: 0.05;'>"
                                f"{record.txt}</span><br>")
                    # await self.add_msg_to_log(txt=txt, color=record.level.color)
            self.info_e.setHtml(txt)
            self.repaint()
            await asyncio.sleep(self.REFRESH_LOG_INTERVAL_SEC)

    async def display_log_levels(self) -> None:

        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt="",
            level=LogLevel.debug,
            show_time = False
        )


        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt=LogLevel.major,
            level=LogLevel.major,
            show_time = False
        )

        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt=LogLevel.warning,
            level=LogLevel.warning,
            show_time=False
        )

        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt=LogLevel.notice,
            level=LogLevel.notice,
            show_time=False

        )

        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt=LogLevel.info,
            level=LogLevel.info,
            show_time=False
        )

        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt='----------------------------------------',
            level=LogLevel.debug,
            show_time=False
        )

        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt='Quality log levels:',
            level=LogLevel.debug,
            show_time=False
        )

        await self.add_record(
            dt=datetime.datetime.now(datetime.timezone.utc),
            txt='',
            level=LogLevel.debug,
            show_time=False
        )


widget_class = QualityLogWidget
