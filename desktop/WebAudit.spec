# PyInstaller build of the desktop program.
#
#   cd web && npm ci && npm run build          # the app's interface (web/dist)
#   pip install -e "core[browser]" -e api -e "desktop[dev]"
#   pyinstaller desktop/WebAudit.spec --noconfirm
#
# Result: dist/WebAudit/WebAudit.exe plus its _internal folder. The program
# creates dist/WebAudit/data on first start. Windows builds run in
# .github/workflows/desktop-windows.yml.
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 - provided by PyInstaller
WEB_DIST = os.path.join(ROOT, "web", "dist")
if not os.path.isfile(os.path.join(WEB_DIST, "index.html")):
    raise SystemExit("Build the web app first: cd web && npm ci && npm run build")

datas = [(WEB_DIST, "web")]
datas += collect_data_files("webaudit")  # defaults/*.json
datas += collect_data_files("webaudit_api")  # search categories and pricing

hiddenimports = []
# uvicorn and SQLAlchemy load these by name at runtime.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("webaudit")
hiddenimports += collect_submodules("webaudit_api")
hiddenimports += ["aiosqlite", "sqlalchemy.dialects.sqlite.aiosqlite", "segno"]  # segno: the vCard QR in the client PDF

a = Analysis(  # noqa: F821
    [os.path.join(SPECPATH, "src", "webaudit_desktop", "__main__.py")],  # noqa: F821
    pathex=[os.path.join(SPECPATH, "src")],  # noqa: F821
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WebAudit",
    console=False,  # a window program, no black console
    icon=os.path.join(SPECPATH, "assets", "webaudit.ico"),  # noqa: F821
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="WebAudit", upx=False)  # noqa: F821
