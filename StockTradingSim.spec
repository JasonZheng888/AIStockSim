# -*- mode: python ; coding: utf-8 -*-
import ast
from pathlib import Path

# Keep the Explorer file version and application title tied to one source.
source = Path(SPECPATH) / 'StockTradingSim.py'
tree = ast.parse(source.read_text(encoding='utf-8-sig'))
app_version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'APP_VERSION'
                           for target in node.targets))
version_tuple = tuple(int(part) for part in app_version.split('-')[0].split('.'))
version_tuple = (version_tuple + (0, 0, 0, 0))[:4]
version_file = Path(SPECPATH) / 'build' / 'windows-version.txt'
version_file.parent.mkdir(parents=True, exist_ok=True)
version_file.write_text(f'''VSVersionInfo(
 ffi=FixedFileInfo(filevers={version_tuple!r}, prodvers={version_tuple!r},
                  mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
 kids=[StringFileInfo([StringTable('080404b0', [
   StringStruct('CompanyName', 'AIStockSim'),
   StringStruct('FileDescription', 'AIStockSim'),
   StringStruct('FileVersion', '{app_version}'),
   StringStruct('InternalName', 'StockTradingSim'),
   StringStruct('OriginalFilename', 'StockTradingSim.exe'),
   StringStruct('ProductName', 'AIStockSim'),
   StringStruct('ProductVersion', '{app_version}')])]),
   VarFileInfo([VarStruct('Translation', [2052, 1200])])])
''', encoding='utf-8')


a = Analysis(
    ['StockTradingSim.py'],
    pathex=[],
    binaries=[],
    datas=[('.\\StockWidget.ico', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='StockTradingSim',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['StockWidget.ico'],
    version=str(version_file),
)
