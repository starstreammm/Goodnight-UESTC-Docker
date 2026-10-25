import asyncio
import base64
import json
import struct
import zlib
from urllib.parse import parse_qs
import httpx
import pytest
from goodnight.captcha import CaptchaRelay, CaptchaInteractionError
from goodnight.models import CaptchaGesture
from uestc_login.http import HttpSession
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def image(width, key=b''):
    def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data))
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,155,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes(width*3))*155))+chunk(b'IEND',b'')
    return base64.b64encode(data+key).decode()


def test_http_human_captcha_refresh_stale_gesture_and_encrypted_tracks():
    posts=[]
    def server(request):
        if request.method=='GET':return httpx.Response(200,json={'bigImage':image(560),'smallImage':image(120,b'0123456789abcdef')})
        sign=parse_qs(request.content.decode())['sign'][0]
        cipher=Cipher(algorithms.AES(b'0123456789abcdef'),modes.CBC(bytes(16))).decryptor()
        value=cipher.update(base64.b64decode(sign))+cipher.finalize()
        unpad=padding.PKCS7(128).unpadder()
        posts.append(json.loads((unpad.update(value)+unpad.finalize())[64:]))
        return httpx.Response(200,json={'errorCode':0 if len(posts)==1 else 1})
    async def run():
        ctx=HttpSession(transport=httpx.MockTransport(server));relay=CaptchaRelay()
        task=asyncio.create_task(relay(ctx))
        try:
            await asyncio.wait_for(relay.ready.wait(),1)
            original=relay.snapshot['ticket']
            assert not base64.b64decode(relay.snapshot['piece']['image'].split(',')[1]).endswith(b'0123456789abcdef')
            def gesture(ticket,x=.05):return CaptchaGesture.model_validate({'ticket':ticket,'points':[{'x':x,'y':.9,'t':0},{'x':.3,'y':.91,'t':120},{'x':.5,'y':.9,'t':400}]})
            with pytest.raises(CaptchaInteractionError):await relay.drag(gesture(original,.5))
            assert not await relay.drag(gesture(original))
            assert relay.snapshot['ticket']!=original
            with pytest.raises(CaptchaInteractionError):await relay.drag(gesture(original))
            prior=relay.snapshot['ticket'];await relay.refresh();assert relay.snapshot['ticket']!=prior
            assert await relay.drag(gesture(relay.snapshot['ticket']))
            await asyncio.wait_for(task,1)
            assert posts[-1]['canvasLength']==280
            assert posts[-1]['moveLength']==pytest.approx(126)
            assert [p['c'] for p in posts[-1]['tracks']]==[0,120,280]
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True);await ctx.close()
    asyncio.run(run())
