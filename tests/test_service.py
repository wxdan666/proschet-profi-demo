"""
Тесты доработок версии 2.1: ограничение попыток PIN и резервные копии.
"""
import os

import pytest

from services import auth, backup, materials


@pytest.fixture(autouse=True)
def _fresh_limiter():
    auth.reset_limiter()
    yield
    auth.reset_limiter()


def test_pin_lock_after_five_errors():
    t = 1000.0
    for i in range(4):
        ok, msg = auth.check_pin_limited("0000", now=t)
        assert not ok and "Осталось попыток" in msg
    ok, msg = auth.check_pin_limited("0000", now=t)
    assert not ok and "заблокирован" in msg
    # даже верный PIN во время блокировки не принимается
    ok, _ = auth.check_pin_limited("1234", now=t + 10)
    assert ok is False
    # после 5 минут блокировка снимается
    ok, _ = auth.check_pin_limited("1234", now=t + 301)
    assert ok is True


def test_pin_success_resets_counter():
    auth.check_pin_limited("0000", now=1.0)
    auth.check_pin_limited("0000", now=1.0)
    assert auth.check_pin_limited("1234", now=1.0)[0]
    for _ in range(4):
        auth.check_pin_limited("0000", now=2.0)
    assert auth.lock_remaining(now=2.0) == 0


def test_bruteforce_is_slowed_down():
    """Перебор: за 5 попыток блокировка, дальше 10 000 PIN не проверить."""
    tried = 0
    for pin in (f"{i:04d}" for i in range(10000)):
        ok, msg = auth.check_pin_limited(pin, now=50.0)
        tried += 1
        if "заблокирован" in msg:
            break
    assert tried == 5


def test_backup_and_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path))
    m = materials.add_material("БК-001", "Позиция для копии", unit="шт")
    materials.receive(m.id, 10, 100)
    first = backup.create_backup("t1")
    materials.receive(m.id, 5, 100)
    assert materials.get_material(m.id).stock == 15
    before = backup.restore_backup(os.path.basename(first))
    assert materials.get_material(m.id).stock == 10
    assert os.path.exists(before)


def test_backup_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path))
    monkeypatch.setattr(backup, "KEEP", 3)
    for i in range(5):
        (tmp_path / f"proschet_2026010{i}_000000.db").write_bytes(b"")
    backup.create_backup("rot")
    assert len(backup.list_backups()) == 3


def test_restore_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "BACKUP_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        backup.restore_backup("нет_такой.db")
