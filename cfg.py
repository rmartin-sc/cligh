import json
import os

from pathlib import Path

CONFIG_PATH = os.path.join(Path.home(), ".cligh")
CONFIG_FILE_NAME = "config.json"
CONFIG_FILE_PATH = os.path.join(CONFIG_PATH, CONFIG_FILE_NAME)

cfg = {}

def is_initialized():
    return os.path.exists(CONFIG_FILE_PATH)

def load():
    global cfg
    if is_initialized():
        with open(CONFIG_FILE_PATH) as file:
            cfg = json.load(file)

def get_all():
    return cfg

def get(key):
    return cfg[key]

def update(new_cfg):
    cfg.update(new_cfg)

    if not is_initialized():
        Path(CONFIG_PATH).mkdir(parents=True, exist_ok=True)

    with open(CONFIG_FILE_PATH, 'w+') as config_file:
        json.dump(cfg, config_file, indent=4, sort_keys=True)

