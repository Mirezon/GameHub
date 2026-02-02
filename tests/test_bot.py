import pytest
from datetime import datetime, timedelta

import bot
from config import Config


def test_validate_url():
    assert bot.validate_url('https://example.com')
    assert bot.validate_url('http://127.0.0.1:8080/path')
    assert not bot.validate_url('not a url')


def test_validate_datetime():
    assert bot.validate_datetime('01.01.2025 12:00')
    assert not bot.validate_datetime('2025-01-01')


def test_format_time_remaining():
    future = (datetime.now() + timedelta(minutes=65)).strftime("%d.%m.%Y %H:%M")
    s = bot.format_time_remaining(future)
    assert 'Осталось' in s or 'мин' in s


def test_config_and_db_loads():
    # Config should create data files if missing and return defaults
    cfg_list = Config.load_admins()
    assert isinstance(cfg_list, list)

    db = bot.Database()
    assert isinstance(db.apps, list)
