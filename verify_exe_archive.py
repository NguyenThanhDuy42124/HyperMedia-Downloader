"""
verify_exe_archive.py
Kiểm tra cấu trúc CArchive và PYZ archive của tệp dist_verified/HyperMedia_Downloader_Pro.exe
"""
import os
import sys
import tempfile

from PyInstaller.utils.cliutils.archive_viewer import CArchiveReader, ZlibArchiveReader

exe_path = os.path.abspath("dist_verified/HyperMedia_Downloader_Pro.exe")
if not os.path.exists(exe_path):
    print(f"ERROR: File not found: {exe_path}")
    sys.exit(1)

carc = CArchiveReader(exe_path)
print(f"CArchive total entries: {len(carc.toc)}")

# 8. Xác nhận binaries & resources trong CArchive
print("\n--- BINARY & RESOURCE VERIFICATION (CArchive) ---")
qjs_found = any("qjs.exe" in str(x) for x in carc.toc)
ffmpeg_found = any("ffmpeg.exe" in str(x) for x in carc.toc)
ejs_found = any("yt_dlp_ejs" in str(x) for x in carc.toc)

print(f"  [+] qjs.exe: {'PASS' if qjs_found else 'FAIL'}")
print(f"  [+] ffmpeg.exe: {'PASS' if ffmpeg_found else 'FAIL'}")
print(f"  [+] yt_dlp_ejs resources: {'PASS' if ejs_found else 'FAIL'}")

# 6 & 7. Kiểm tra PYZ archive
print("\n--- PYZ ARCHIVE MODULE VERIFICATION ---")
pyz_name = None
for name in carc.toc:
    if "PYZ" in name:
        pyz_name = name
        break

if not pyz_name:
    print("ERROR: PYZ entry not found in CArchive!")
    sys.exit(1)

print(f"PYZ entry name: {pyz_name}")

extracted = carc.extract(pyz_name)
pyz_bytes = extracted[1] if isinstance(extracted, tuple) else extracted

with tempfile.NamedTemporaryFile(suffix=".pyz", delete=False) as f:
    f.write(pyz_bytes)
    temp_pyz_path = f.name

try:
    zar = ZlibArchiveReader(temp_pyz_path)
    pyz_toc = set(zar.toc.keys()) if hasattr(zar.toc, "keys") else set(zar.toc)
    print(f"Total modules in PYZ: {len(pyz_toc)}")

    required_modules = [
        "miniapp_browse_widget",
        "miniapp_episode_dialog",
        "drama_path_utils",
        "providers.miniapp_douyin_provider",
        "providers.miniapp_douyin_client",
    ]

    all_found = True
    for m in required_modules:
        found = m in pyz_toc
        status = "PASS" if found else "FAIL"
        if not found:
            all_found = False
        print(f"  [+] {m}: {status}")

    # Kiểm tra các module providers nền tảng khác
    other_providers = [
        "providers.base",
        "providers.registry",
        "providers.crypto_utils",
        "providers.dramabox_provider",
        "providers.kisskh_provider",
        "providers.hongguo_provider",
        "providers.goodshort_provider",
        "providers.shortmax_provider",
        "providers.netshort_provider",
        "providers.freereels_provider",
        "providers.dramawave_provider",
        "providers.raptdrama_provider",
        "providers.flextv_provider",
        "providers.stardusttv_provider",
        "drama_dialog",
        "drama_browse_widget",
    ]

    print("\n--- OTHER DRAMA PROVIDERS & WIDGETS IN PYZ ---")
    for p in other_providers:
        found = p in pyz_toc
        print(f"  [*] {p}: {'PASS' if found else 'FAIL'}")
finally:
    if os.path.exists(temp_pyz_path):
        try:
            os.remove(temp_pyz_path)
        except Exception:
            pass

if not (qjs_found and ffmpeg_found and ejs_found and all_found):
    print("\nVERIFICATION FAILED")
    sys.exit(1)

print("\nALL ARCHIVE VERIFICATIONS PASSED SUCCESSFULLY!")
