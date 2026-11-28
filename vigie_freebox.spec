# Fichier PyInstaller — construit « VigieFreebox.exe » (Windows) ou « Vigie Freebox.app » (macOS).
import sys
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(["main.py"], pathex=["."],
             datas=[("assets/icon.png", "assets"), ("assets/logo_56.png", "assets"), ("assets/logo_110.png", "assets"), ("assets/fonts", "assets/fonts")],
             hiddenimports=["vigie.pdf"] + collect_submodules("keyring.backends") + collect_submodules("reportlab.graphics"),
             excludes=["pytest"])
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Vigie Freebox", console=False,
              icon="assets/icon.icns")
    coll = COLLECT(exe, a.binaries, a.datas, name="Vigie Freebox")
    app = BUNDLE(coll, name="Vigie Freebox.app", icon="assets/icon.icns", bundle_identifier="fr.vigie.freebox",
                 info_plist={
                     "CFBundleShortVersionString": "1.2.0",
                     "NSHighResolutionCapable": True,
                     # macOS 15+ : obligatoire pour joindre la Freebox sur le réseau local
                     "NSLocalNetworkUsageDescription":
                         "Vigie Freebox interroge votre Freebox sur le réseau local pour suivre le Wi-Fi et le lien TV.",
                 })
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="VigieFreebox", console=False,
              icon="assets/icon.ico", upx=False)
