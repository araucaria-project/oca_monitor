import asyncio
import copy
import logging
import os

from serverish.base.task_manager import create_task


logger = logging.getLogger(__name__.rsplit('.')[-1])


class ImageDisplay:

    MODES = {'new_files': {}, 'modify_time': {}}

    def __init__(
            self, name: str, images_dir: str, images_prefix: str = '',
            image_change_sec: float = 0.75, refresh_image_time_sec: float = 10, mode: str = 'new_files') -> None:
        self.name = name
        self.images_dir = images_dir
        self.lock = asyncio.Lock()
        self.image_queue = asyncio.PriorityQueue()
        self.files_list = []
        self.images_prefix = images_prefix
        self.image_change_sec = image_change_sec
        self.refresh_image_time_sec = refresh_image_time_sec
        super().__init__()

    async def image_list_refresh(self, image_instance_clb: callable):
        while True:
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
            current_files_list_path.sort()
            if current_files_list_path != self.files_list:
                logger.info(f'{self.name} files list updating...')
                new_files = [x for x in current_files_list_path if x not in self.files_list]
                new_files_no = len(new_files)
                if new_files_no > 0:
                    async with self.lock:
                        self.files_list = copy.deepcopy(current_files_list_path)
                        for new_file in new_files:
                            if self.image_queue.qsize() > len(current_files_list_path) - 1:
                                _ = await self.image_queue.get()
                            await self.image_queue.put((new_file, await image_instance_clb(image_path=new_file)))
                logger.info(f'{self.name} files list updated by new files no: {new_files_no}.')
            await asyncio.sleep(self.refresh_image_time_sec)

    async def display(self, image_display_clb: callable) -> None:
        while True:
            async with self.lock:
                if self.image_queue.qsize() > 0:
                    image_to_display = await self.image_queue.get()
                    await image_display_clb(image_to_display=image_to_display[1])
                    await self.image_queue.put(image_to_display)
            await asyncio.sleep(self.image_change_sec)

    async def display_init(self, image_display_clb: callable, image_instance_clb: callable):
        logger.info(f'Starting {self.name} display.')
        await create_task(
            self.image_list_refresh(image_instance_clb=image_instance_clb), f'{self.name}_refresh_images'
        )
        await create_task(self.display(image_display_clb=image_display_clb), f'{self.name}_display_images')