"""Encrypted local credentials and non-sliding, seven-day session leases."""
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from cryptography.fernet import Fernet
from .client import PasswordRequired, sign_in, exchange, check_session

TTL = 7 * 86400


def service_session(state):
    return next((cookie.get('value') for cookie in (state or {}).get('cookies', [])
                 if cookie.get('name') == 'SESSION' and
                 cookie.get('domain', '').lstrip('.') == 'jzsz.uestc.edu.cn' and
                 cookie.get('path', '/') == '/'), None)


class LoginManager:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = self.directory / 'key'
        try:
            fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as f:
                f.write(Fernet.generate_key())
        self.cipher = Fernet(key.read_bytes())
        self._issued_fingerprints = set()

    def path(self, username):
        return self.directory / (hashlib.sha256(username.encode()).hexdigest() + '.enc')

    def load(self, username):
        path = self.path(username)
        if not path.exists():
            return {}
        return json.loads(self.cipher.decrypt(path.read_bytes()))

    def write(self, username, data):
        path = self.path(username)
        tmp = path.with_suffix('.' + secrets.token_hex(6) + '.tmp')
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(self.cipher.encrypt(json.dumps(data).encode()))
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    def fingerprint(self, username):
        data = self.load(username)
        if not data.get('fingerprint'):
            data['fingerprint'] = self.new_fingerprint(username)
            self.write(username, data)
        return data['fingerprint']

    def new_fingerprint(self, username):
        """Stage a replacement identity without changing the saved account."""
        used = set(self._issued_fingerprints)
        for path in self.directory.glob('*.enc'):
            saved = json.loads(self.cipher.decrypt(path.read_bytes())).get('fingerprint')
            if isinstance(saved, str):
                used.add(saved.upper())
        fingerprint = secrets.token_hex(16).upper()
        while fingerprint in used:
            fingerprint = secrets.token_hex(16).upper()
        self._issued_fingerprints.add(fingerprint)
        return fingerprint

    def save(self, username, state, password=None, save_password=False, *, fingerprint=None):
        data = self.load(username)
        expires_at = time.time() + TTL
        if (fingerprint is None and data.get('expires_at', 0) > time.time() and service_session(state)
                and service_session(state) == service_session(data.get('state'))):
            # Confirming a reused login must not turn the lease into a sliding one.
            expires_at = data.get('expires_at', expires_at)
        data.update(state=state, expires_at=expires_at,
                    password=password if save_password else None)
        if fingerprint is not None:
            data['fingerprint'] = fingerprint
        self.write(username, data)

    def metadata(self, username):
        data = self.load(username)
        return {'uestc_expires_at': data.get('expires_at'), 'save_password': bool(data.get('password'))}

    def forget_password(self, username):
        data = self.load(username)
        data['password'] = None
        self.write(username, data)

    def delete(self, username):
        self.path(username).unlink(missing_ok=True)

    async def login(self, sessions, username, password, *, new_fingerprint=None, force=False, **kwargs):
        if new_fingerprint is not None:
            # Explicit reset bypasses both portal-session reuse and saved CAS cookies.
            kwargs.pop('state', None)
            return await sign_in(sessions, username, password, fingerprint=new_fingerprint, **kwargs)
        data = self.load(username)
        if not force and data.get('state') and data.get('expires_at', 0) > time.time():
            context = await sessions.new_context(storage_state=data['state'])
            try:
                try:
                    await check_session(context)
                except PasswordRequired:
                    pass
                else:
                    data['state'] = await context.storage_state()
                    self.write(username, data)
                    return data['state']
            finally:
                await context.close()
        if force:
            kwargs.pop('state', None)
        return await sign_in(sessions, username, password, fingerprint=self.fingerprint(username), **kwargs)

    async def session(self, sessions, username, cached=None):
        data = self.load(username)
        if data.get('expires_at', 0) > time.time():
            context = await sessions.new_context(storage_state=cached or data['state'])
            try:
                try:
                    await check_session(context)
                    data['state'] = await context.storage_state()
                    self.write(username, data)  # Preserve the original local lease.
                    return data['state']
                except PasswordRequired:
                    pass
            finally:
                await context.close()
            context = await sessions.new_context(storage_state=data['state'])
            try:
                try:
                    # Check a different saved state, but do not repeat the same
                    # rejected session probe before renewing through CAS.
                    state = await exchange(context, check_existing=bool(cached and cached != data['state']))
                    data['state'] = state
                    self.write(username, data)  # Never extend the original lease.
                    return state
                except PasswordRequired:
                    pass
            finally:
                await context.close()
        password = data.get('password')
        if not password:
            raise PasswordRequired('Your school session expired. Enter your password again.')
        state = await sign_in(sessions, username, password,
            fingerprint=self.fingerprint(username), interactive=False)
        self.save(username, state, password, True)
        return state
