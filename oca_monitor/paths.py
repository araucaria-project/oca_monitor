import importlib.resources


def icon_path(icon_name):
    return importlib.resources.files('oca_monitor.resources.icons').joinpath(icon_name)
