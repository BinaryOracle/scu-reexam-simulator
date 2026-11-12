import sqlite3
from pathlib import Path
from .config import load_config

def connect():
    path = Path(load_config()['app']['database'])
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db

def initialize():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS interviews(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'active', created REAL NOT NULL, feedback TEXT);
        CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, interview_id INTEGER NOT NULL REFERENCES interviews(id), stage INTEGER NOT NULL, question TEXT NOT NULL, transcript TEXT NOT NULL DEFAULT '', audio_path TEXT, UNIQUE(interview_id, stage));
        CREATE TABLE IF NOT EXISTS contests(id INTEGER PRIMARY KEY, title TEXT NOT NULL, starts REAL NOT NULL, ends REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS problems(id INTEGER PRIMARY KEY, contest_id INTEGER NOT NULL REFERENCES contests(id), title TEXT NOT NULL, statement TEXT NOT NULL, sample_input TEXT NOT NULL, sample_output TEXT NOT NULL, tests TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS submissions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), problem_id INTEGER NOT NULL REFERENCES problems(id), language TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL);
        ''')
