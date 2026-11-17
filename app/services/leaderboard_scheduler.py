"""Run idempotent weekly settlements, including downtime recovery, in one worker."""
import logging
import threading
from app.db import connect
from app.services import leaderboard

_logger = logging.getLogger(__name__)
_stop = threading.Event()
_thread = None


def _run():
    while not _stop.is_set():
        try:
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                leaderboard.settle_due(db)
        except Exception:
            _logger.exception('Weekly leaderboard settlement failed; retrying in 60 seconds')
        if _stop.wait(60):
            return


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_run, name='leaderboard-settlement', daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=2)
