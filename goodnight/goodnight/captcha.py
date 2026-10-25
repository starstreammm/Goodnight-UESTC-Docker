"""Relay a person's slider gesture over HTTP; the school decides correctness."""
import asyncio
import base64
import binascii
import json
import math
import secrets
import struct
from uestc_login.client import IDAS, SERVICE_LOGIN_URL
from uestc_login.crypto import encrypt_password


class CaptchaInteractionError(Exception):
    pass


def png(value):
    if not isinstance(value, str) or len(value) > 2_000_000:
        raise CaptchaInteractionError('Invalid school CAPTCHA image.')
    try:
        raw = base64.b64decode(value, validate=True)
        if raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
            raise ValueError()
        width, height = struct.unpack('>II', raw[16:24])
        if not (0 < width <= 4096 and 0 < height <= 4096):
            raise ValueError()
        offset = 8
        while offset + 12 <= len(raw):
            length = struct.unpack('>I', raw[offset:offset+4])[0]
            end = offset + 12 + length
            if end > len(raw):
                raise ValueError()
            if raw[offset+4:offset+8] == b'IEND':
                # Do not disclose the server's trailing verification key to the UI.
                return raw, 'data:image/png;base64,' + base64.b64encode(raw[:end]).decode(), width
            offset = end
    except (ValueError, binascii.Error, struct.error):
        pass
    raise CaptchaInteractionError('Invalid school CAPTCHA image.')


class CaptchaRelay:
    def __init__(self):
        self.ready = asyncio.Event()
        self.resume = asyncio.Event()
        self.context = None
        self.snapshot = None
        self.key = None

    async def __call__(self, context):
        self.context = context
        self.resume.clear()
        self.ready.clear()
        await self.capture()
        self.ready.set()
        try:
            async with asyncio.timeout(300):
                await self.resume.wait()
        finally:
            self.ready.clear()
            self.snapshot = None
            self.key = None

    async def capture(self):
        response = await self.context.request.get(IDAS + '/common/openSliderCaptcha.htl',
            referer=SERVICE_LOGIN_URL)
        try:
            if response.status != 200:
                raise CaptchaInteractionError('The school could not load the CAPTCHA.')
            data = await response.json()
            if not isinstance(data, dict):
                raise CaptchaInteractionError('Invalid school CAPTCHA response.')
            _, background, width = png(data.get('bigImage'))
            raw, piece, piece_width = png(data.get('smallImage'))
            try:
                key = raw[-16:].decode('ascii')
            except UnicodeDecodeError:
                raise CaptchaInteractionError('Invalid school CAPTCHA verification key.') from None
            if not key.isalnum():
                raise CaptchaInteractionError('Invalid school CAPTCHA verification key.')
            self.key = key
            self.snapshot = {'ticket':secrets.token_urlsafe(18), 'image':background,
                'width':280, 'height':199, 'image_height':155/199, 'image_width':278/280,
                'piece':{'image':piece, 'x':0, 'y':0,
                         'width':max(1, piece_width * 280 / width - 2)/280, 'height':155/199},
                'handle':{'x':0, 'y':159/199, 'width':40/280, 'height':40/199}}
            return self.snapshot
        except (ValueError, KeyError):
            raise CaptchaInteractionError('Invalid school CAPTCHA response.') from None
        finally:
            await response.dispose()

    async def drag(self, gesture):
        if not self.ready.is_set() or not self.snapshot or gesture.ticket != self.snapshot['ticket']:
            raise CaptchaInteractionError('This CAPTCHA changed. Refresh it and try again.')
        first, last = gesture.points[0], gesture.points[-1]
        handle = self.snapshot['handle']
        if not (handle['x'] <= first.x <= handle['x']+handle['width'] and
                handle['y'] <= first.y <= handle['y']+handle['height']):
            raise CaptchaInteractionError('Start dragging on the CAPTCHA slider handle.')
        def point(p, elapsed):
            return {'a':(p.x-first.x)*280, 'b':(p.y-first.y)*199, 'c':elapsed}
        tracks, previous, accepted = [{'a':0, 'b':0, 'c':0}], 0, None
        for p in gesture.points[1:-1]:
            q = point(p, p.t-previous)
            if not 0 <= q['a'] <= 240 or q['c'] < 20:
                continue
            if accepted and math.hypot(q['a']-accepted['a'], q['b']-accepted['b']) < 2:
                continue
            tracks.append(q)
            previous, accepted = p.t, q
        end = point(last, last.t-previous)
        if not 0 < end['a'] <= 240:
            raise CaptchaInteractionError('Keep the slider inside its track.')
        tracks.append(end)
        payload = {'canvasLength':280, 'moveLength':end['a'], 'tracks':tracks}
        sign = encrypt_password(json.dumps(payload, separators=(',',':')), self.key)
        response = await self.context.request.post(IDAS + '/common/verifySliderCaptcha.htl',
            form={'sign':sign}, referer=SERVICE_LOGIN_URL)
        try:
            if response.status != 200:
                raise CaptchaInteractionError('The school could not verify the CAPTCHA.')
            result = await response.json()
        finally:
            await response.dispose()
        if isinstance(result, dict) and result.get('errorCode') == 1:
            self.ready.clear()
            self.resume.set()
            return True
        await self.capture()
        return False

    async def refresh(self):
        if not self.ready.is_set():
            raise CaptchaInteractionError('No CAPTCHA is awaiting input.')
        return await self.capture()
