#!/usr/bin/env python3
"""
Yorichii Checker - ONE CLICK EXE MAKER FOR WINDOWS
Keep this file + yorichii_checker_cli.py + api folder + yorichii_icon.ico in SAME FOLDER
Then run: python make_exe.py
It will make YorichiiChecker.exe in SAME FOLDER

TG: https://t.me/whoevenyori | Green & Gold Edition
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

def run(cmd):
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True)
    return result.returncode == 0

def main():
    print("""
\033[92m\033[1m
__   __           _      _     _  _  ____       _               
\\ \\ / /__  _ __  (_) ___| |__ (_)(_)/ ___|  ___| |__   ___  ___ 
 \\ V / _ \\| '__| | |/ __| '_ \\| || | |  _ / __| '_ \\ / _ \\/ __|
  | | (_) | |    | | (__| | | | || | |_| | (__| | | |  __/ (__ 
  |_|\\___/|_|    |_|\\___|_| |_|_|_|\\____|\\___|_| |_|\\___|\\___|
\033[93m
  ONE CLICK EXE MAKER - SAME FOLDER OUTPUT
  TG: https://t.me/whoevenyori | Green & Gold
\033[0m
""")
    root = Path(__file__).parent
    os.chdir(root)

    print(f"[*] Folder: {root}")
    print(f"[*] Files in folder: {list(root.glob('*'))[:10]}")

    # Check required files
    required = ["yorichii_checker_cli.py", "api"]
    for f in required:
        if not (root / f).exists():
            print(f"[!] Missing required: {f} - keep cli + api folder in same folder!")
            sys.exit(1)

    # Install pyinstaller
    print("[*] Installing PyInstaller (if needed)...")
    run(f"{sys.executable} -m pip install pyinstaller pillow --quiet")

    # Clean old exe
    exe_name = "YorichiiChecker.exe"
    if (root / exe_name).exists():
        print(f"[*] Removing old {exe_name}")
        try:
            (root / exe_name).unlink()
        except:
            pass
    if (root / "dist").exists():
        shutil.rmtree(root / "dist", ignore_errors=True)
    if (root / "build").exists():
        shutil.rmtree(root / "build", ignore_errors=True)
    for spec in root.glob("*.spec"):
        spec.unlink()

    # Check icon
    icon_arg = ""
    if (root / "yorichii_icon.ico").exists():
        icon_arg = '--icon yorichii_icon.ico'
        print(f"[*] Using icon: yorichii_icon.ico")
    else:
        print("[!] No icon found, building without icon")

    # Build command - OUTPUT IN SAME FOLDER
    # --distpath . = output exe in current folder, not dist/
    # --workpath build = temp files in build/
    # --specpath . = spec in current folder (will be deleted)
    
    is_windows = os.name == "nt"
    
    if is_windows:
        cmd = f'{sys.executable} -m PyInstaller --onefile --console --name YorichiiChecker --distpath . --workpath build --specpath . {icon_arg} --add-data "api;api" yorichii_checker_cli.py'
    else:
        cmd = f'{sys.executable} -m PyInstaller --onefile --console --name YorichiiChecker --distpath . --workpath build --specpath . {icon_arg} --add-data "api:api" yorichii_checker_cli.py'

    print(f"\n[*] Building EXE in SAME FOLDER...")
    print(f"    Command: {cmd}\n")
    
    success = run(cmd)
    if not success:
        print("[!] PyInstaller failed! Trying without icon...")
        if is_windows:
            cmd2 = f'{sys.executable} -m PyInstaller --onefile --console --name YorichiiChecker --distpath . --workpath build --specpath . --add-data "api;api" yorichii_checker_cli.py'
        else:
            cmd2 = f'{sys.executable} -m PyInstaller --onefile --console --name YorichiiChecker --distpath . --workpath build --specpath . --add-data "api:api" yorichii_checker_cli.py'
        success = run(cmd2)
    
    if not success and not is_windows:
        print("[!] PyInstaller failed (common on Debian static Python) - trying cx_Freeze fallback for Linux...")
        print("[*] Installing cx_Freeze...")
        run(f"{sys.executable} -m pip install cx_Freeze --quiet --break-system-packages")
        print("[*] Building with cx_Freeze...")
        # Create simple setup for same-folder output
        setup_content = '''
from cx_Freeze import setup, Executable
build_exe_options = {"packages": ["api", "requests", "urllib3", "encodings", "concurrent", "email"], "include_files": [("api", "api")]}
setup(name="YorichiiChecker", version="1.1.0", options={"build_exe": build_exe_options}, executables=[Executable("yorichii_checker_cli.py", target_name="YorichiiChecker", icon="yorichii_icon.ico" if __import__('pathlib').Path("yorichii_icon.ico").exists() else None)])
'''
        Path("setup_temp.py").write_text(setup_content)
        if run(f"{sys.executable} setup_temp.py build"):
            # Find built binary
            import glob
            bins = glob.glob("build/exe.*/YorichiiChecker")
            if bins:
                bin_path = bins[0]
                print(f"[*] Found binary at {bin_path}, copying to same folder as YorichiiChecker-linux")
                shutil.copy(bin_path, root / "YorichiiChecker-linux")
                # Also copy bundle
                bundle_src = str(Path(bin_path).parent)
                bundle_dst = root / "YorichiiChecker-bundle"
                if bundle_dst.exists():
                    shutil.rmtree(bundle_dst, ignore_errors=True)
                shutil.copytree(bundle_src, bundle_dst)
                print(f"[✓] Linux binary ready: {root / 'YorichiiChecker-linux'}")
                print(f"[✓] Bundle ready: {bundle_dst}")
                # For Linux we consider success even though not .exe
                Path("setup_temp.py").unlink(missing_ok=True)
                success = True
        Path("setup_temp.py").unlink(missing_ok=True)
    
    if not success:
        print("[!] Build failed! Check errors above")
        print("[*] On Windows, make sure Python is installed with 'Add to PATH' checked")
        sys.exit(1)

    # Clean up
    print("\n[*] Cleaning temp files...")
    if (root / "build").exists():
        shutil.rmtree(root / "build", ignore_errors=True)
    for spec in root.glob("*.spec"):
        spec.unlink()
        print(f"    Deleted {spec}")
    Path("setup_temp.py").unlink(missing_ok=True)

    # Check if exe exists in same folder
    exe_path = root / exe_name
    linux_exe = root / "YorichiiChecker-linux"
    linux_bundle = root / "YorichiiChecker-bundle"
    
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024*1024)
        print(f"""
\033[92m\033[1m[✓] SUCCESS! EXE BUILT IN SAME FOLDER!\033[0m
    File: {exe_path}
    Size: {size_mb:.2f} MB
    Branding: Green & Gold | TG https://t.me/whoevenyori

\033[93m[*] How to use (same folder):\033[0m
    YorichiiChecker.exe --version
    YorichiiChecker.exe -i combos.txt -p proxies.txt -t 20
    YorichiiChecker.exe --combo test@example.com:password123 --proxy http://127.0.0.1:8080

\033[92m    EXE is in SAME FOLDER as this script - ready to share!\033[0m
""")
    elif linux_exe.exists():
        size_mb = linux_exe.stat().st_size / (1024*1024)
        print(f"""
\033[92m\033[1m[✓] SUCCESS! LINUX BINARY BUILT IN SAME FOLDER!\033[0m
    File: {linux_exe}
    Size: {size_mb:.2f} MB
    Bundle: {linux_bundle}
    Branding: Green & Gold | TG https://t.me/whoevenyori

\033[93m[*] How to use (same folder):\033[0m
    ./YorichiiChecker-linux --version
    ./YorichiiChecker-linux -i combos.txt -p proxies.txt -t 20

\033[93m[*] On WINDOWS, this same script will build YorichiiChecker.exe\033[0m
    Just run: python make_exe.py  OR  double-click MAKE_EXE.bat

\033[92m    Binary is in SAME FOLDER - ready!\033[0m
""")
    else:
        # Check dist folder fallback
        dist_exe = root / "dist" / exe_name
        if dist_exe.exists():
            print(f"[*] Found in dist folder, moving to same folder...")
            shutil.move(str(dist_exe), str(exe_path))
            print(f"[✓] Moved to {exe_path}")
        else:
            print(f"[!] EXE not found! Check build logs")
            print(f"[*] On Linux, PyInstaller fails due to static Python - but cx_Freeze fallback should have created YorichiiChecker-linux")
            print(f"[*] On Windows, it will create YorichiiChecker.exe in same folder")
            sys.exit(1)

if __name__ == "__main__":
    main()
