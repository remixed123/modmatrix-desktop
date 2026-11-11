# Build the Windows app (x64), unsigned: dist\Perkons Mod Matrix\ and a zip of it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
#
# Same steps as build_macos.sh: download the pinned parts (runtime.lock.json, checked by
# SHA-256), assemble the runtime (standalone Python + capstone + unicorn, trimmed Arm
# toolchain), build the launcher with PyInstaller, put the runtime and licences next to it.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Platform = 'windows-x64'
$AppName = 'Perkons Mod Matrix'
$Build = Join-Path $Root 'build'
$DL = Join-Path $Build 'downloads'
$RT = Join-Path $Build 'runtime'
$Dist = Join-Path $Root 'dist'
$Lock = Get-Content (Join-Path $Root 'runtime.lock.json') -Raw | ConvertFrom-Json

function Say($msg) { Write-Host "`n== $msg" }

function Fetch($url, $sha) {
  $name = [uri]::UnescapeDataString((Split-Path -Leaf ([uri]$url).AbsolutePath))
  New-Item -ItemType Directory -Force $DL | Out-Null
  $path = Join-Path $DL $name
  if (-not (Test-Path $path) -or (Get-FileHash $path -Algorithm SHA256).Hash -ne $sha.ToUpper()) {
    Write-Host "downloading $name"
    # curl.exe, not Invoke-WebRequest: .NET turns the %2F in Arm's GitLab URLs into /, and
    # GitLab then answers with an error page
    & curl.exe -fsSL --retry 3 -o "$path.part" $url
    if ($LASTEXITCODE -ne 0) { throw "download failed ($LASTEXITCODE): $url" }
    Move-Item -Force "$path.part" $path
  }
  if ((Get-FileHash $path -Algorithm SHA256).Hash -ne $sha.ToUpper()) { throw "checksum mismatch: $name" }
  return $path
}

function Run($exe) {
  & $exe @args
  if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $exe $args" }
}

# ---------------------------------------------------------------------------------------------
Say "runtime: Python $($Lock.python.version)"
$py = $Lock.python.platforms.$Platform
$tc = $Lock.toolchain.platforms.$Platform
$PyTgz = Fetch $py.url $py.sha256
$TcZip = Fetch $tc.url $tc.sha256

Remove-Item -Recurse -Force $RT, (Join-Path $Build 'tc') -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $RT, (Join-Path $Build 'tc') | Out-Null
Run tar -xzf $PyTgz -C $RT                     # -> runtime\python
$P = Join-Path $RT 'python'
$PyExe = Join-Path $P 'python.exe'
$req = Join-Path $Build 'requirements-runtime.txt'
$Lock.python.wheels.$Platform | Set-Content -Encoding ascii $req
Run $PyExe -m pip install -q --disable-pip-version-check --no-compile --only-binary :all: --require-hashes -r $req
Run $PyExe -I -c "import capstone, unicorn, importlib.metadata as m; print('capstone', m.version('capstone'), 'unicorn', m.version('unicorn'))"

Run $PyExe -m pip uninstall -q -y pip
foreach ($d in 'include', 'tcl', 'Scripts', 'Lib\test', 'Lib\idlelib', 'Lib\tkinter', 'Lib\turtledemo',
               'Lib\ensurepip', 'Lib\lib2to3') {
  Remove-Item -Recurse -Force (Join-Path $P $d) -ErrorAction SilentlyContinue
}
Get-ChildItem (Join-Path $P 'DLLs') -Include '_tkinter*', 'tcl*', 'tk*', '_test*' -Recurse | Remove-Item -Force
Get-ChildItem $P -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
& $PyExe -I -m compileall -q -j0 --invalidation-mode unchecked-hash (Join-Path $P 'Lib') | Out-Null

Say "runtime: Arm GNU Toolchain $($Lock.toolchain.version), trimmed"
Expand-Archive -Path $TcZip -DestinationPath (Join-Path $Build 'tc')
$TcSrc = Join-Path $Build 'tc'
$top = Get-ChildItem $TcSrc -Directory
if ($top.Count -eq 1 -and -not (Test-Path (Join-Path $TcSrc 'bin'))) { $TcSrc = $top[0].FullName }
foreach ($rel in $Lock.toolchain.keep_windows) {   # not $p: PowerShell names ignore case ($P)
  $src = Join-Path $TcSrc $rel
  $dst = Join-Path (Join-Path $RT 'toolchain') $rel
  New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
  Copy-Item -Recurse -Force $src $dst
}
Remove-Item -Recurse -Force (Join-Path $Build 'tc')
Run (Join-Path $RT 'toolchain\bin\arm-none-eabi-gcc.exe') --version

$pk = @{}
foreach ($l in $Lock.python.wheels.$Platform) { $n, $v = ($l -split ' ')[0] -split '=='; $pk[$n] = $v }
@{ platform = $Platform; python = $Lock.python.version; packages = $pk; toolchain = $Lock.toolchain.version } |
  ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $RT 'runtime.json')

# ---------------------------------------------------------------------------------------------
Say "launcher: PyInstaller $($Lock.launcher.pyinstaller), pywebview $($Lock.launcher.pywebview)"
$Venv = Join-Path $Build 'venv'
$VPy = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path (Join-Path $Venv 'Scripts\pyinstaller.exe'))) {
  $BP = Join-Path $Build 'buildpython'
  Remove-Item -Recurse -Force $BP, $Venv -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force $BP | Out-Null
  Run tar -xzf $PyTgz -C $BP
  Run (Join-Path $BP 'python\python.exe') -m venv $Venv
  Run $VPy -m pip install -q --disable-pip-version-check "pyinstaller==$($Lock.launcher.pyinstaller)" "pywebview==$($Lock.launcher.pywebview)"
}
Remove-Item -Recurse -Force $Dist, (Join-Path $Build 'pyinstaller') -ErrorAction SilentlyContinue
Run (Join-Path $Venv 'Scripts\pyinstaller.exe') --noconfirm --clean --log-level WARN --distpath $Dist --workpath (Join-Path $Build 'pyinstaller') modmatrix.spec
$App = Join-Path $Dist $AppName

Say "app: runtime and licences"
Copy-Item -Recurse $RT (Join-Path $App 'runtime')
$Lic = Join-Path $App 'licenses'
New-Item -ItemType Directory -Force $Lic | Out-Null
Copy-Item licenses\* $Lic
Copy-Item (Join-Path $RT 'toolchain\share\doc\arm-none-eabi\readme.txt') (Join-Path $Lic 'arm-gnu-toolchain-readme.txt')
Copy-Item (Join-Path $P 'LICENSE.txt') (Join-Path $Lic 'python-LICENSE.txt') -ErrorAction SilentlyContinue
foreach ($sp in @((Join-Path $P 'Lib\site-packages'), (Join-Path $Venv 'Lib\site-packages'))) {
  foreach ($d in Get-ChildItem $sp -Directory -Filter '*.dist-info') {
    $pkg = ($d.Name -split '-')[0]
    if ($pkg -notin 'capstone', 'unicorn', 'pywebview', 'pythonnet', 'pyinstaller', 'clr_loader') { continue }
    Get-ChildItem $d.FullName -Recurse -File | Where-Object { $_.Name -match '^(LICEN[CS]E|COPYING)' } |
      ForEach-Object { Copy-Item $_.FullName (Join-Path $Lic "$pkg-$($_.Name)") }
  }
}

Say "zip"
$Zip = Join-Path $Dist "ModMatrixDesktop-Windows.zip"   # no version: README links to releases/latest/download/
Compress-Archive -Path $App -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "-> $Zip"
