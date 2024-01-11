import os

from dynaconf import Dynaconf

# For the configuration values, see settings.toml and (optionally) .secrets.toml

# Default configuration is in [oca] section

settings = Dynaconf(
    envvar_prefix="OCAMONITOR",
    settings_files=['settings.toml', '.secrets.toml'],
    environments=True,
    env_switcher='OCAMONITOR_ENV',
)

# `envvar_prefix` = export envvars with `export DYNACONF_FOO=bar`.
# `settings_files` = Load these files in the order.
