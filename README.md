# Perkons Mod Matrix (desktop)

The [Pērkons HD-01 Mod Matrix](https://github.com/kiteless/perkons-re) as a desktop app:
download, open, drop in your own official firmware image, tick mods, build, download the
modded image. No Git, Python, compiler or terminal needed.

> Unofficial. Not affiliated with or endorsed by Erica Synths. Modded firmware is flashed
> entirely at your own risk. The app contains no Erica Synths firmware: you supply your own.

## How it works

The app is a runtime and a small launcher. It holds:

* a standalone Python 3.12 with capstone and unicorn (what perkons-re needs),
* the Arm GNU Toolchain (arm-none-eabi), trimmed to the compiler, assembler, linker,
  objcopy, nm and objdump,
* the launcher (`launcher/modmatrix_launcher.py`, built with PyInstaller, window by pywebview).

It does not hold perkons-re or any mods. On each start the launcher downloads the newest
perkons-re (`main`) as a zip from GitHub, or uses the last one when offline, and starts its
Mod Matrix with the bundled Python and compiler. The Mod Matrix gets the mods itself, from
the repos in [repos.json](https://github.com/kiteless/perkons-re-mods/blob/main/repos.json).
An update of perkons-re that needs other Python packages than the app holds is not used
(the app keeps the one it has and says so).

Everything downloaded or built goes in the data folder, never in the app:

* macOS: `~/Library/Application Support/Perkons Mod Matrix/`
* Windows: `%LOCALAPPDATA%\PerkonsModMatrix\`

with `framework/` (perkons-re), `cache/` (mods, measurements), `tmp/` (builds) and
`launcher.log`. Deleting it resets the app.

## Building

Everything the build downloads is pinned, with its SHA-256, in `runtime.lock.json`.

macOS (Apple Silicon):

```sh
scripts/build_macos.sh                         # -> dist/PerkonsModMatrix-<version>-macos-arm64.dmg
SIGN_IDENTITY="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=notary scripts/build_macos.sh
```

Signing uses the hardened runtime on every binary; only the bundled Python has an
entitlement (`com.apple.security.cs.allow-jit`, for the emulator). Notarising needs a
notarytool keychain profile, made once with
`xcrun notarytool store-credentials notary --apple-id <id> --team-id <team> --password <app-specific password>`.

Windows (x64, unsigned for now):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1   # -> dist\PerkonsModMatrix-<version>-windows-x64.zip
```

GitHub Actions (`.github/workflows/release.yml`) builds both; a `v*` tag makes a draft
release with both builds and the toolchain's GPL source.

Launcher tests: `build/venv/bin/python -m unittest discover -s tests`.

Options of the launcher (for development): `--browser` (no window), `--framework DIR`
(a local perkons-re), `--repos-url URL` (another mod repo list), `--runtime DIR`.

## Licences

See `licenses/THIRD_PARTY.md`: the Arm GNU Toolchain is GPL-3.0 (its source is attached to
each release), unicorn is GPL-2.0, perkons-re is MIT, Python is under the PSF licence.
