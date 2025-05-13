import logging

from oca_monitor.pages.telescope_ofp import TelescopeOfp


logger = logging.getLogger(__name__.rsplit('.')[-1])


class WidgetTvsControlroom(TelescopeOfp):

    def __init__(self,
                 main_window
                 ):
        super().__init__(main_window=main_window, tel='zb08')

widget_class = WidgetTvsControlroom
