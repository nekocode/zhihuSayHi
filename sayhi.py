#!/usr/bin/env python3
# coding:utf-8
import requests
import time
import hmac
from hashlib import sha1
import json
import base64
import asyncio
import websockets


class ZhihuSayHi:
    STATUS_CODE_UNAUTHORIZED = 401
    CLIENT_ID = 'ee61ede15113741dca8bca59479ce6'
    CLIENT_SECRET = b'8b735aeaecebc6aaf1f0ece3afdc8b'
    SOURCE = 'com.zhihu.android'
    REFRESH_TOKEN_TIME = 60 * 1

    def __init__(self):
        self.looper = None
        self.headers = {
            'Authorization': 'oauth ee61ede15113741dca8bca59479ce6',
            'Cache-Control': 'no-cache'
        }

        self.cookies = None
        self.token = {
            'user_id': 0,
            'uid': '',
            'access_token': '',
            'expires_in': 0,
            'refresh_token': ''
        }

        self.old_followers = []
        self.new_followers = []

    @staticmethod
    def sign(msg, pwd):
        a = hmac.new(pwd, str.encode(msg), sha1)
        return a.hexdigest()

    @staticmethod
    def decode_json(response):
        return json.loads(bytes.decode(response))

    def get_cookit_str(self):
        return 'z_c0=' + self.token['cookie']['z_c0']

    def check_token(self, req):
        if req.status_code == self.STATUS_CODE_UNAUTHORIZED:
            self.refresh_token()

    def login(self, email, pwd):
        grant_type = 'password'
        ts = int(time.time() * 1000)
        signature = self.sign(grant_type + self.CLIENT_ID + self.SOURCE + str(ts), self.CLIENT_SECRET)

        req = requests.post("https://api.zhihu.com/sign_in", data={
            'grant_type': grant_type,
            'username': email,
            'password': pwd,
            'client_id': self.CLIENT_ID,
            'source': self.SOURCE,
            'signature': signature,
            'timestamp': ts
        }, headers=self.headers, cookies=self.cookies)

        self.token = self.decode_json(req.content)
        self.headers['Authorization'] = 'Bearer ' + self.token['access_token']
        print("Login Success.")

    def refresh_token(self):
        grant_type = 'refresh_token'
        ts = int(time.time() * 1000)
        signature = self.sign(grant_type + self.CLIENT_ID + self.SOURCE + str(ts), self.CLIENT_SECRET)

        req = requests.post("https://api.zhihu.com/sign_in", data={
            'grant_type': grant_type,
            'refresh_token': self.token['refresh_token'],
            'client_id': self.CLIENT_ID,
            'source': self.SOURCE,
            'signature': signature,
            'timestamp': ts
        }, headers=self.headers, cookies=self.cookies)

        self.token = self.decode_json(req.content)
        self.headers['Authorization'] = 'Bearer ' + self.token['access_token']
        print("Refresh Token Success.")

    def get_captcha(self):
        req = requests.get('https://api.zhihu.com/captcha', headers=self.headers)
        self.cookies = req.cookies
        rsp = self.decode_json(req.content)

        if rsp['show_captcha']:
            rsp = self.decode_json(
                requests.put('https://api.zhihu.com/captcha', headers=self.headers, cookies=self.cookies).content
            )
            img_b64 = rsp['img_base64']
            img_bin = base64.b64decode(img_b64)
            with open('captcha.png', 'wb') as f:
                f.write(img_bin)

    def input_captcha(self, text):
        req = requests.post('https://api.zhihu.com/captcha', data={
            'input_text': text
        }, headers=self.headers, cookies=self.cookies)

        return self.decode_json(req.content)['success']

    async def get_followers(self):
        is_end = False
        next_page = 'https://api.zhihu.com/notifications/follows?limit=20&offset=0'
        while not is_end:
            req = requests.get(next_page, headers=self.headers, cookies=self.cookies)
            self.check_token(req)

            rsp = self.decode_json(req.content)
            is_end = rsp['paging']['is_end']
            next_page = rsp['paging']['next']

            for data in rsp['data']:
                for fol in data['operators']:
                    finded = False
                    for old_fol in self.old_followers:
                        if fol['id'] == old_fol['id']:
                            finded = True
                            break

                    if not finded:
                        self.new_followers.append(fol)
                        self.old_followers.append(fol)

        print_str = '['
        for fol in self.new_followers:
            print_str += fol['name'] + ', '
        print_str += ']'
        print('New Followers:' + print_str)

    async def send_msg(self, receiver_id, content):
        req = requests.post('https://api.zhihu.com/messages', data={
            'receiver_id': receiver_id,
            'content': content
        }, headers=self.headers, cookies=self.cookies)
        self.check_token(req)

        msg = self.decode_json(req.content)
        print('Send Msg To [%s]: %s' % (msg['receiver']['name'], content))

    async def sayhi_to_followers(self):
        for fol in self.new_followers:
            await self.send_msg(fol['id'],
                                'Hi, %s! Thanks for your following~ \n\n'
                                '[This message sent from https://github.com/nekocode/zhihuSayHi]'
                                % fol['name'])

        self.new_followers.clear()

    async def listener_push(self):
        while True:
            try:
                async with websockets.connect('ws://apilive.zhihu.com/apilive',
                                              extra_headers={'Cookie': self.get_cookit_str()}) as websocket:
                    async def ping():
                        while True:
                            await asyncio.sleep(10)
                            await websocket.ping()
                            print('Ping Success.')

                    self.looper.create_task(ping())

                    while True:
                        push_msg = self.decode_json(await websocket.recv())
                        if push_msg['follow_has_new']:
                            await self.get_followers()
                            await self.sayhi_to_followers()

            except Exception as e:
                try:
                    # Try to refresh token
                    self.refresh_token()

                except:
                    # Refresh token failed
                    print('Listener Push Error:' + str(e))
                    self.looper.stop()
                    return

                # Sleep 10 secends before the next connection
                await asyncio.sleep(10)

    def start(self):
        self.looper = asyncio.get_event_loop()

        self.get_captcha()
        self.input_captcha(input('Captcha:'))
        self.login(input('Email:'), input('Password:'))

        self.looper.run_until_complete(self.get_followers())
        self.looper.run_until_complete(self.sayhi_to_followers())
        self.looper.run_until_complete(self.listener_push())
        self.looper.stop()


if __name__ == '__main__':
    ZhihuSayHi().start()

