import asyncio
import copy
import logging
import os
import time
from typing import List

from serverish.base.task_manager import create_task


logger = logging.getLogger(__name__.rsplit('.')[-1])


class ImageDisplay:

    MODES = {'new_files': {}, 'update_files': {}}

    def __init__(
            self, name: str, images_dir: str, image_display_clb: callable, image_instance_clb: callable,
            images_prefix: str = '', image_cascade_sec: float = 0.75, image_pause_sec: float = 1.5,
            refresh_list_sec: float = 10, mode: str = 'new_files', sort_reverse: bool = False) -> None:
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
        super().__init__()

    async def new_files_refresh(self, files_list: List):
        # logger.info(f'Display {self.name} files list updating...')
        current_images = []
        for n in range(self.image_queue.qsize()):
            image_queue = await self.image_queue.get()
            if image_queue[0] in files_list:
                await self.image_queue.put(image_queue)
                current_images.append(image_queue[0])
        new_files = [x for x in files_list if x not in current_images]
        new_files_no = len(new_files)
        if new_files_no > 0:
            for new_file in new_files:
                await self.image_queue.put((new_file, await self.image_instance_clb(image_path=new_file)))
            logger.info(f'{self.name} files list updated by new files no: {new_files_no}.')

    async def update_files_refresh(self, files_list: List):
        # logger.info(f'Display {self.name} files list updating...')
        ok = True
        if self.image_queue.qsize() == 0:
            logger.info(self.image_queue)
            ok = False
        else:
            for file in files_list:
                if not ok:
                    break
                for n in range(self.image_queue.qsize()):
                    image_queue = await self.image_queue.get()
                    await self.image_queue.put(image_queue)
                    if file == image_queue[0]:
                        if os.path.getmtime(file) != image_queue[2]:
                            logger.info(f'{os.path.getmtime(file)}!={image_queue[2]}')
                            ok = False
                            break

        if not ok:
            self.image_queue = asyncio.Queue()
            for new_file in files_list:
                last_mod = os.path.getmtime(new_file)
                await self.image_queue.put((new_file, await self.image_instance_clb(image_path=new_file), last_mod))
            logger.info(f'{self.name} files list updated by new files no: {len(files_list)}.')
            return
        # current_images = []
        # for n in range(self.image_queue.qsize()):
        #     image_queue = await self.image_queue.get()
        #     if image_queue[0] in files_list:
        #         await self.image_queue.put(image_queue)
        #         current_images.append(image_queue[0])
        # new_files = [x for x in files_list if x not in current_images]
        # new_files_no = len(new_files)
        # if new_files_no > 0:
        #     for new_file in new_files:
        #         await self.image_queue.put((new_file, await self.image_instance_clb(image_path=new_file)))
        # logger.info(f'{self.name} files list updated by new files no: {new_files_no}.')

    async def image_list_refresh(self):
        current_files_list = []
        try:
            files_found = os.listdir(self.images_dir)
        except OSError:
            logger.error(f'Can not access {self.images_dir}.')
            files_found = []

        for file in files_found:
            if self.images_prefix in file:
                current_files_list.append(file)
        current_files_list_path = [os.path.join(self.images_dir, f) for f in current_files_list]
        current_files_list_path.sort(reverse=self.sort_reverse)
        if self.mode in self.MODES:
            if self.mode == 'new_files':
                await self.new_files_refresh(files_list=current_files_list_path)
            elif self.mode == 'update_files':
                await self.update_files_refresh(files_list=current_files_list_path)
        else:
            logger.error(f'No mode in modes, select: {self.MODES}.')

    async def display(self) -> None:
        while True:
            for n in range(self.image_queue.qsize()):
                if self.image_queue.qsize() > 0:
                    image_to_display = await self.image_queue.get()
                    await self.image_display_clb(object_to_display=image_to_display[1])
                    await self.image_queue.put(image_to_display)
                await asyncio.sleep(self.image_cascade_sec)
            if not self.last_refresh or time.time() > self.last_refresh + self.refresh_list_sec:
                await self.image_list_refresh()
                self.last_refresh = time.time()
            await asyncio.sleep(self.image_pause_sec)

    async def display_init(self):
        logger.info(f'Starting {self.name} display.')
        await create_task(self.display(), f'{self.name}_display_images')