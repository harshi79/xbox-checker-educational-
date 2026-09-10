# 🎮 Yorichii Xbox Checker - Professional Edition

> **Green & Gold • Live Terminal • Bulk Checker • Auto Proxy Remover**  
> **TG: https://t.me/whoevenyori** | **Provided by @yorichiiprime** | Educational Use Only  
> **Version: 2.0-professional-green-gold**

Professional Xbox & Microsoft account checker with live terminal, bulk support, and smart proxy handling.

---

## ✨ Professional Features

- **🌐 Own IP Fallback:** No proxies? Uses your own IP automatically (direct connection)
- **🧹 Auto-Remove Dead Proxies:** Dead proxies are detected and removed during checking
- **🔄 Retry Until Valid:** Tries combos one-by-one until `PREMIUM / FREE / BAD / 2FA / BANNED` — **no proxy errors allowed**, only valid results
- **📺 Live Terminal:** Real-time output with timestamp, live counter every 5 checks
- **📦 Bulk Checking:** Check 1000s of combos with threading (up to 100 threads)
- **🎨 Green & Gold Theme:** Professional branding with TG link
- **💾 Smart Saving:** Auto-saves hits to `PREMIUM.txt`, `FREE.txt`, `BAD.txt`, `2FA.txt`, `results.jsonl`

---

## 📁 Clean Repo - Only Needed Files for EXE

```
YorichiiChecker/
├── yorichii_checker_cli.py   <- Main professional checker (GREEN & GOLD)
├── api/
│   ├── __init__.py
│   ├── checker.py            <- Core Xbox checker logic
│   └── watermark.py          <- Branding watermark
├── yorichii_icon.ico         <- Green & Gold icon for exe
├── make_exe.py               <- One-click exe maker (same folder output)
├── MAKE_EXE.bat              <- Double-click to make exe on Windows
├── combos.example.txt        <- Example combos
├── proxies.example.txt       <- Example proxies
├── requirements.txt          <- Only requests + urllib3
├── LICENSE
└── README.md
```

**No unnecessary files** — only what you need to make exe. Download, extract, make exe, opensource ready!

---

## 🚀 How to Make EXE (Same Folder)

### Super Simple - Windows:

1. **Download repo and extract** - keep all files in same folder
2. **Double-click `MAKE_EXE.bat`**  
   OR run: `python make_exe.py`
3. **Done!** `YorichiiChecker.exe` appears **in SAME FOLDER**

```bat
YourFolder/
├── YorichiiChecker.exe   <- EXE IN SAME FOLDER! Ready!
├── yorichii_checker_cli.py
├── api/
└── yorichii_icon.ico
```

**What the builder does:**
```bat
pyinstaller --onefile --name YorichiiChecker --distpath . --icon yorichii_icon.ico --add-data "api;api" yorichii_checker_cli.py
```
`--distpath .` = exe in same folder (not dist/)

### Manual Command (if bat fails):
```bat
pip install pyinstaller pillow
python -m PyInstaller --onefile --console --name YorichiiChecker --distpath . --icon yorichii_icon.ico --add-data "api;api" yorichii_checker_cli.py
```

---

## 💻 How to Use (Live Terminal Bulk)

### Basic:
```bash
# Single combo
YorichiiChecker.exe --combo test@example.com:password123

# With proxy
YorichiiChecker.exe --combo test@example.com:pass123 --proxy http://127.0.0.1:8080

# Bulk with proxies
YorichiiChecker.exe -i combos.txt -p proxies.txt -t 20

# Bulk without proxies (uses own IP)
YorichiiChecker.exe -i combos.txt -t 50

# Custom output
YorichiiChecker.exe -i combos.txt -p proxies.txt -t 50 -o hits
```

### Input Formats:
- `email:password`
- `email|password`
- `email;password`
- `email password`
- One per line, `#` comments ignored

### Proxy Formats:
- `host:port`
- `http://host:port`
- `socks5://host:port`
- `user:pass@host:port`
- `http://user:pass@host:port`

### Live Output Example:
```
[12:27:13] [PREMIUM] test@example.com (0.42s) | GT: MyGamerTag | XBOX GAME PASS ULTIMATE | GS: 12345 [1.2.3.4:8080]
[12:27:13] [FREE] my@test.com (0.31s) | GT: FreeUser [Own IP]
  ↳ Live: 5/100 | PREMIUM:2 FREE:1 BAD:2 | Proxies: 45 good, 5 dead

========== PROFESSIONAL RESULTS ==========
PREMIUM: 10 | FREE: 20 | BAD: 65 | 2FA: 5 | RETRY: 12 | DEAD PROXIES: 5
Checked: 100/100 in 45.20s | 2.21 c/s | Threads: 20
Proxies: 45 good, 5 dead, 50 total | Own IP fallback used when needed
Results: C:\YourFolder\results
```

### Output Files:
- `results/PREMIUM.txt` - Hits with Game Pass
- `results/FREE.txt` - Valid, no sub
- `results/BAD.txt` - Invalid credentials
- `results/2FA.txt` - Needs 2FA
- `results/results.jsonl` - Full JSON log with proxy used

---

## 🔧 Professional Logic

```python
# 1. No proxies? Use own IP
if not proxies:
    use_direct_ip()

# 2. Auto-remove dead proxies
if proxy_fails:
    remove_proxy(proxy)
    retry_with_new_proxy()

# 3. Retry until valid (no proxy errors)
while not valid_result and retries < max_retries:
    try_with_next_proxy()
    if valid in [PREMIUM, FREE, BAD, 2FA, BANNED]:
        break  # Final result
    else:  # TIMEOUT, ProxyError, etc
        mark_dead_and_retry()
```

**Valid results (final, no retry):** `PREMIUM, FREE, BAD, 2FA, BANNED`  
**Proxy errors (retry with new proxy):** `TIMEOUT, ERROR with ProxyError/ConnectionError/MaxRetries`

---

## 🎨 Branding

- **Theme:** Green & Gold (Emerald `#2ECC71` + Gold `#FFD700`)
- **TG:** https://t.me/whoevenyori - in banner, footer, every result
- **Watermark:** `Provided by @yorichiiprime`
- **Version:** `2.0-professional-green-gold`
- **Icon:** Green & Gold Xbox checker

---

## ⚠️ Disclaimer

```
Educational Use Only - Only test accounts you OWN.
TG: https://t.me/whoevenyori | Provided by @yorichiiprime
Unauthorized checking may violate ToS and laws.
```

---

## 📦 Open Source

This is clean, professional, ready for open source. Just:
1. Download repo
2. Extract
3. Run `MAKE_EXE.bat` or `python make_exe.py`
4. Get `YorichiiChecker.exe` in same folder
5. Share!

**Made with 💚💛 by YorichiiPrime**  
**TG: https://t.me/whoevenyori**

---

## 🧪 Test

```bash
python yorichii_checker_cli.py --version
python yorichii_checker_cli.py --combo test@example.com:pass123 -t 1 -o test_results
```
