import logging

from oca_monitor.pages.telescope_ofp import TelescopeOfp


logger = logging.getLogger(__name__.rsplit('.')[-1])


class WidgetTvsControlroom(TelescopeOfp):

    def __init__(self, main_window, **kwargs):
        super().__init__(main_window=main_window, tel='wk06', kwargs=kwargs)

widget_class = WidgetTvsControlroom
