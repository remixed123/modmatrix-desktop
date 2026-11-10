# Third-party software in Perkons Mod Matrix

Perkons Mod Matrix is unofficial. It is not affiliated with or endorsed by Erica Synths.
Modded firmware is flashed entirely at your own risk.

The app contains no Erica Synths firmware and no mods. You supply your own official firmware
image; the Mod Matrix (perkons-re) and the mods are downloaded from GitHub when the app runs.

| Component | Version | Licence | Source |
|---|---|---|---|
| Arm GNU Toolchain (GCC, binutils), arm-none-eabi, trimmed to the compiler, assembler, linker, objcopy, nm and objdump | 15.3.rel2 | GPL-3.0 (`GPL-3.0.txt`), GCC Runtime Library Exception 3.1 (`GCC-RUNTIME-LIBRARY-EXCEPTION-3.1.txt`) | https://gitlab.arm.com/api/v4/projects/tooling%2Fgnu-toolchains-for-arm/packages/generic/gnu-toolchain/15.3.rel2/arm-gnu-toolchain-src-snapshot-15.3.rel2.tar.xz (SHA-256 59bf354b14755172eb238511542c599a6ec3540a19164b8dfe1accbe084c8089); a copy is attached to each release of this app |
| perkons-re (downloaded at run time, not bundled) | main | MIT (`perkons-re-MIT.txt`) | https://github.com/kiteless/perkons-re |
| Python (python-build-standalone) | 3.12.16 (20261026) | PSF License (`python-LICENSE.txt`) | https://github.com/astral-sh/python-build-standalone |
| capstone | 5.0.9 | BSD-3-Clause (`capstone-*`) | https://github.com/capstone-engine/capstone |
| unicorn | 2.1.4 | GPL-2.0 (`GPL-2.0.txt`, `unicorn-*`) | https://github.com/unicorn-engine/unicorn |
| pywebview | 6.2.1 | BSD-3-Clause (`launcher-*`) | https://github.com/r0x0r/pywebview |
| PyObjC (macOS) | see `launcher-*` | MIT | https://github.com/ronaldoussoren/pyobjc |
| PyInstaller bootloader | 6.22.3 | GPL-2.0 with the bootloader exception | https://github.com/pyinstaller/pyinstaller |
