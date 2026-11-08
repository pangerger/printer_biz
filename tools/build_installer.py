"""Build a local macOS package; never installs or changes a printer queue."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import bizhub

folder=bizhub.external_directory()
root=ROOT/'build/pkgroot'
destination=root/'Library/Printers/bizhub185'
scripts=ROOT/'build/pkg-scripts'
destination.mkdir(parents=True,exist_ok=True)
scripts.mkdir(exist_ok=True)
for src,name in [(ROOT/'build/bizhub185-filter','bizhub185-filter'),
                 (ROOT/'packaging/bizhub185.ppd','bizhub185.ppd'),
                 (ROOT/'packaging/uninstall.sh','uninstall.sh'),
                 (ROOT/'THIRD_PARTY.md','THIRD_PARTY.md')]:
    shutil.copyfile(src,destination/name)
    os.chmod(destination/name,0o755 if name in ('bizhub185-filter','uninstall.sh') else 0o644)
source=destination/'source'
source.mkdir(exist_ok=True)
for name in ['cups-filter.c','raster.c','raster.h']:
    shutil.copyfile(ROOT/'src'/name,source/name)
for name in ['jbig.c','jbig.h','jbig_ar.c','jbig_ar.h','COPYING']:
    shutil.copyfile(folder/'jbigkit-source'/name,source/name)
    os.chmod(source/name,0o644)
(source/'BUILD.txt').write_text('Sources supplied under GPL-2.0-or-later. Build on macOS with Command Line Tools:\nclang -std=c11 -O2 -I. cups-filter.c raster.c jbig.c jbig_ar.c -framework CoreGraphics -framework CoreFoundation -lcups -o bizhub185-filter\n')
shutil.copyfile(ROOT/'packaging/postinstall',scripts/'postinstall')
os.chmod(scripts/'postinstall',0o755)
package=folder/'bizhub185-macOS-0.3.1.pkg'
subprocess.run(['pkgbuild','--root',str(root),'--scripts',str(scripts),'--ownership','recommended',
    '--identifier','local.bizhub185.driver','--version','0.3.1','--install-location','/',str(package)],check=True)
print(package)
