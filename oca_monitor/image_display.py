import asyncio
import copy
import logging
import os
import time
from typing import List, Callable, Optional

from serverish.base.task_manager import create_task

from serverish.base.iterators import AsyncListIter, AsyncRangeIter

logger = logging.getLogger(__name__.rsplit('.')[-1])


class ImageDisplay:

    MODES = {'new_files': {}, 'update_files': {}, 'update_files_show_once': {}}

    def __init__(
            self, name: str, images_dir: str, image_display_clb: Callable, image_instance_clb: Callable,
            images_prefix: str = '', image_cascade_sec: float = 0.75, image_pause_sec: float = 1.5,
            refresh_list_sec: float = 10, mode: str = 'new_files', sort_reverse: bool = False,
            max_age_sec: Optional[float] = None, on_stale_clb: Optional[Callable] = None) -> None:
        self.name = name
        self.images_dir = images_dir
        self.image_queue = asyncio.Queue()
        self.image_display_clb = image_display_clb
        self.image_instance_clb = image_instance_clb
        self.images_prefix = images_prefix
        self.image_cascade_sec = image_cascade_sec
        self.refresh_list_sec = refresh_list_sec
        self.image_pause_sec = image_pause_sec
        self.last_refresh = None
        self.mode = mode
        self.sort_reverse = sort_reverse
        self.max_age_sec = max_age_sec
        self.on_stale_clb = on_stale_clb
        super().__init__()

    async def new_files_refresh(self, files_list: List):
        # logger.info(f'Display {self.name} files list updating...')
        current_images = []
        async for n in AsyncRangeIter(start=1, end=self.image_queue.qsize()):
            image_queue = await self.image_queue.get()
            if image_queue[0] in files_list:
                await self.image_queue.put(image_queue)
                current_images.append(image_queue[0])
        new_files = [x async for x in AsyncListIter(files_list) if x not in current_images]
        new_files_no = len(new_files)
        real_new_files_no = 0
        if new_files_no > 0:
            async for new_file in AsyncListIter(new_files):
                image_object = await self.image_instance_clb(image_path=new_file)
                if image_object is not None:
                    await self.image_queue.put((new_file, image_object))
                    real_new_files_no += 1
                else:
                    logger.warning(f'Image {new_file} in {self.name} is None.')
            logger.debug(f'{self.name} files list updated by new files no: {real_new_files_no}.')

    async def update_files_refresh(self, files_list: List):
        # logger.info(f'Display {self.name} files list updating...')
        ok = True
        if self.image_queue.qsize() == 0:
            ok = False
        elif len(files_list) > self.image_queue.qsize():
            ok = False
        else:
            async for file in AsyncListIter(files_list):
                if not ok:
                    break
                async for n in AsyncRangeIter(start=1, end=self.image_queue.qsize()):
                    image_queue = await self.image_queue.get()
                    await self.image_queue.put(image_queue)
                    if file == image_queue[0]:
                        try:
                            if os.path.getmtime(file) != image_queue[2]:
                                ok = False
                                break
                        except OSError:
                            logger.warning(f'Can not read image {file}  in {self.name}.')
                            ok = False
                            break

        if not ok:
            await self._drain_queue()
            async for new_file in AsyncListIter(files_list):
                try:
                    image_object = await self.image_instance_clb(image_path=new_file)
                    if image_object is not None:
                        last_mod = os.path.getmtime(new_file)
                        # (new_file, image_object, last_mod, showed)
                        await self.image_queue.put((new_file, image_object, last_mod, False))
                    else:
                        logger.warning(f'Image {new_file} in {self.name} is None.')
                except OSError:
                    logger.warning(f'Can not read image {new_file} in {self.name}.')
            logger.debug(f'{self.name} files list updated by new files no: {len(files_list)}.')
            return

    async def _drain_queue(self) -> None:
        """Empty in place — (single-consumer)"""
        while not self.image_queue.empty():
            try:
                self.image_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def _notify_stale(self, reason: str) -> None:
        if self.on_stale_clb is None:
            return
        try:
            await self.on_stale_clb(reason=reason)
        except Exception as e:
            logger.warning(f'{self.name}: on_stale_clb failed: {e}')

    async def image_list_refresh(self):
        try:
            files_found = os.listdir(self.images_dir)
        except OSError as e:
            logger.error(f'Can not access {self.images_dir}: {e}')
            await self._drain_queue()
            await self._notify_stale(f'cannot access {self.images_dir}')
            return

        current_files_list = [f for f in files_found if self.images_prefix in f]
        current_files_list_path = [os.path.join(self.images_dir, f) for f in current_files_list]

        if self.max_age_sec is not None:
            cutoff = time.time() - self.max_age_sec
            fresh: List[str] = []
            newest_mtime = 0.0
            for path in current_files_list_path:
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest_mtime = mtime
                if mtime >= cutoff:
                    fresh.append(path)

            if not fresh:
                await self._drain_queue()
                if newest_mtime > 0:
                    age_min = int((time.time() - newest_mtime) / 60)
                    if age_min < 60:
                        msg = f'last image {age_min} min old'
                    else:
                        msg = f'last image {age_min // 60}h {age_min % 60}min old'
                else:
                    msg = f'no images in {self.images_dir}'
                await self._notify_stale(msg)
                return
            current_files_list_path = fresh

        current_files_list_path.sort(reverse=self.sort_reverse)
        if self.mode in self.MODES:
            if self.mode == 'new_files':
                await self.new_files_refresh(files_list=current_files_list_path)
            elif self.mode in ['update_files', 'update_files_show_once']:
                await self.update_files_refresh(files_list=current_files_list_path)
        else:
            logger.error(f'No mode in modes, select: {self.MODES}.')

    async def display(self) -> None:
        while True:
            async for n in AsyncRangeIter(start=1, end=self.image_queue.qsize()):
                if self.image_queue.qsize() > 0:
                    image_to_display = await self.image_queue.get()
                    if self.mode != 'update_files_show_once':
                        if image_to_display[1] is not None:
                            await self.image_display_clb(object_to_display=image_to_display[1])
                    else:
                        if len(image_to_display) == 4 and image_to_display[3] is False:
                            if image_to_display[1] is not None:
                                await self.image_display_clb(object_to_display=image_to_display[1])
                            image_to_display = (image_to_display[0], image_to_display[1], image_to_display[2], True)

                    await self.image_queue.put(image_to_display)
                await asyncio.sleep(self.image_cascade_sec)
            if not self.last_refresh or time.time() > self.last_refresh + self.refresh_list_sec:
                await self.image_list_refresh()
                self.last_refresh = time.time()
            await asyncio.sleep(self.image_pause_sec)

    async def display_init(self):
        logger.info(f'Starting {self.name} display.')
        await create_task(self.display(), f'{self.name}_display_images')
