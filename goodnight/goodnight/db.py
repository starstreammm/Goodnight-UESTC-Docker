import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from cryptography.fernet import Fernet
from .models import Config
from uestc_login import LoginManager


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = self.directory / 'session.key'
        if not key.exists():
            with key.open('xb') as f:
                f.write(Fernet.generate_key())
            key.chmod(0o600)
        self.cipher = Fernet(key.read_bytes())
        self.path = self.directory / 'goodnight.sqlite3'
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, alias TEXT NOT NULL,
                    session BLOB NOT NULL, status TEXT NOT NULL DEFAULT 'ready');
                CREATE TABLE IF NOT EXISTS jobs (
                    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
                    date TEXT, due TEXT NOT NULL, cutoff TEXT NOT NULL,
                    scheduled_at TEXT, checked INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'scheduled', submitted INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, message TEXT,
                    PRIMARY KEY(account_id,date));
            ''')
            account_columns = {row['name'] for row in db.execute('PRAGMA table_info(accounts)')}
            for column in ('location_key', 'location_name', 'wechat_ref', 'details', 'schedule', 'checkin_time'):
                if column not in account_columns:
                    db.execute(f'ALTER TABLE accounts ADD COLUMN {column} TEXT')
            for column in ('wechat_lease_started_at', 'wechat_lease_expires_at'):
                if column not in account_columns:
                    db.execute(f'ALTER TABLE accounts ADD COLUMN {column} REAL')
            job_columns = {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}
            if 'scheduled_at' not in job_columns:
                db.execute('ALTER TABLE jobs ADD COLUMN scheduled_at TEXT')
            if 'checked' not in job_columns:
                db.execute('ALTER TABLE jobs ADD COLUMN checked INTEGER NOT NULL DEFAULT 0')
            if 'submission_diagnostic' not in job_columns:
                db.execute('ALTER TABLE jobs ADD COLUMN submission_diagnostic TEXT')
            # Legacy jobs only retain their latest due time; preserve that once.
            db.execute('UPDATE jobs SET scheduled_at=due WHERE scheduled_at IS NULL')
            db.execute("UPDATE jobs SET checked=1 WHERE status='success'")
            db.execute('INSERT OR IGNORE INTO config VALUES(1,?)', (Config().model_dump_json(),))
        self.path.chmod(0o600)
        self.login = LoginManager(self.directory / "login")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def config(self):
        with self.connect() as db:
            return Config.model_validate_json(db.execute('SELECT value FROM config').fetchone()[0])

    def save_session(self, username, alias, state):
        encrypted = self.cipher.encrypt(json.dumps(state).encode())
        with self.connect() as db:
            db.execute('''INSERT INTO accounts(username,alias,session) VALUES(?,?,?)
                ON CONFLICT(username) DO UPDATE SET alias=excluded.alias,session=excluded.session,status='ready' ''',
                (username, alias, encrypted))
            # Reauthentication may resume verification, but never clears a submission journal.
            db.execute("UPDATE jobs SET status='scheduled',attempts=0 WHERE account_id=(SELECT id FROM accounts WHERE username=?) AND status IN ('need_login','wechat_expired','wechat_code_invalid')", (username,))

    def state(self, account):
        return json.loads(self.cipher.decrypt(account['session']))
