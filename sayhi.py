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
import logging


class ZhihuSayHi:
    STATUS_CODE_UNAUTHORIZED = 401
    CLIENT_ID = '8d5227e0aaaa4797a763ac64e0c3b8'
    CLIENT_SECRET = b'ecbefbf6b17e47ecb9035107866380'
    SOURCE = 'com.zhihu.android'
    REFRESH_TOKEN_TIME = 60 * 1

    def __init__(self):
        self.looper = None
        self.headers = {
            'Authorization': 'oauth 8d5227e0aaaa4797a763ac64e0c3b8',
            'Connection': 'keep-alive',
            'Cache-Control': 'no-cache',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) '
                          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/51.0.2704.103 Safari/537.36',
            'Host': 'api.zhihu.com',
        }

        self.cookies = None
        self.show_captcha = True
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
            raise TokenException()

    def login(self, email, pwd):
        grant_type = 'password'
        ts = int(time.time())
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
        logging.info("Login Success.")

    def refresh_token(self):
        grant_type = 'refresh_token'
        ts = int(time.time())
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
        logging.info("Refresh Token Success.")

    def get_captcha(self):
        req = requests.get('https://api.zhihu.com/captcha', headers=self.headers)
        self.cookies = req.cookies
        rsp = self.decode_json(req.content)
        self.show_captcha = rsp['show_captcha']

        if self.show_captcha:
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
        logging.info('New Followers:' + print_str)

    async def send_msg(self, receiver_id, content):
        req = requests.post('https://api.zhihu.com/messages', data={
            'receiver_id': receiver_id,
            'content': content
        }, headers=self.headers, cookies=self.cookies)
        self.check_token(req)

        msg = self.decode_json(req.content)
        logging.info('Send Msg To [%s]: %s' % (msg['receiver']['name'], content))

    async def sayhi_to_followers(self):
        for fol in self.new_followers:
            await self.send_msg(fol['id'],
                                'Hi, %s! Thanks for your following~ \n'
                                '[This message sent from https://github.com/nekocode/zhihuSayHi]'
                                % fol['name'])

        self.new_followers.clear()

    async def listen_push(self):
        listen_retry_count = 0
        while True:
            try:
                async with websockets.connect('ws://apilive.zhihu.com/apilive',
                                              extra_headers={'Cookie': self.get_cookit_str()}) as websocket:
                    listen_retry_count = 0  # Reset

                    # Pinging task
                    async def ping():
                        logging.info("Start Pinging...")
                        ping_retry_count = 0

                        while True:
                            try:
                                await asyncio.sleep(10)
                                await websocket.ping()
                                ping_retry_count = 0  # Reset

                            except Exception as e1:
                                ping_retry_count += 1

                                # Retry over 5 times
                                if ping_retry_count > 5:
                                    logging.error("Pinging Error: " + str(e1))
                                    raise e1

                    # Add pinging task to event loop
                    self.looper.create_task(ping())

                    # Listening task
                    logging.info("Start Listening...")
                    recv_retry_count = 0
                    while True:
                        try:
                            push_msg = self.decode_json(await websocket.recv())
                            recv_retry_count = 0  # Reset
                            if push_msg['follow_has_new']:
                                await self.get_followers()
                                await self.sayhi_to_followers()

                        except TokenException:
                            # Token is invaild, refresh it
                            try:
                                self.refresh_token()
                            except Exception as e3:
                                logging.error("Refresh Token Error: " + str(e3))
                                raise e3

                            raise TokenException()

                        except Exception as e2:
                            recv_retry_count += 1

                            # Retry over 3 times
                            if recv_retry_count > 3:
                                logging.error("Listening Error: " + str(e2))
                                raise e2

            except TokenException:
                # Sleep 5 secends before the next connection
                await asyncio.sleep(5)

            except Exception:
                logging.info("Reconnecting...")
                listen_retry_count += 1
                await asyncio.sleep(10)

                if listen_retry_count > 5:
                    self.looper.stop()
                    return

    def start(self):
        self.looper = asyncio.get_event_loop()

        self.get_captcha()
        if self.show_captcha:
            self.input_captcha(input('Captcha:'))

        self.login(input('Email:'), input('Password:'))

        self.looper.run_until_complete(self.get_followers())
        self.looper.run_until_complete(self.sayhi_to_followers())
        self.looper.run_until_complete(self.listen_push())
        self.looper.stop()


class TokenException(Exception):
    pass


# Logging config
fmt = '%(asctime)s [%(levelname)s] %(message)s'
datefmt = '%Y-%m-%d,%H:%M:%S'

logging.basicConfig(
    level=logging.INFO,
    format=fmt,
    datefmt=datefmt,
    filename='sayhi.log',
    filemode='w')

console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter(fmt, datefmt)
console.setFormatter(formatter)
logging.getLogger('').addHandler(console)

logging.getLogger('requests').setLevel(logging.CRITICAL)


if __name__ == '__main__':
    ZhihuSayHi().start()

