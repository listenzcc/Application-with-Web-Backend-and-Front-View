# file: run3d.ps1
#
# 在单个模拟目录里跑完三维流程：
#   fds -> fds2ascii(PL3D) -> 体数据二进制
# 最后按产物判定成功与否，落 success / failed 标记文件。
#
# 由 python/fds3d/simulate.py 调用：
#   powershell -ExecutionPolicy Bypass -File run3d.ps1 `
#       -folder <会话目录> -filename template3d.fds -python <python.exe>

param(
    [Parameter(Mandatory = $true)][string]$folder,
    [Parameter(Mandatory = $true)][string]$filename,
    [string]$python = 'python'
)

$ErrorActionPreference = 'Continue'

# 让中文和 fds 的输出按 UTF-8 出去，被 simulate.py 的 stdout.txt 原样接住
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
}
catch { }

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- 1. 定位运行目录（相对路径按 fds3d/ 解析）---
if ([System.IO.Path]::IsPathRooted($folder)) {
    $dst = $folder
}
else {
    $dst = Join-Path $scriptDir $folder
}
if (-not (Test-Path $dst)) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
}

$logFile = Join-Path $dst 'run.log'
$utf8 = New-Object System.Text.UTF8Encoding($false)

function Write-Log([string]$msg) {
    $line = '{0}  {1}' -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    [System.IO.File]::AppendAllText($logFile, $line + [Environment]::NewLine, $utf8)
}

function Write-Marker([string]$name, [string]$content) {
    [System.IO.File]::WriteAllText((Join-Path $dst $name), $content, $utf8)
}

# --- 2. 找 FDS 可执行文件，并把它的目录塞进 PATH ---
$fdsBat = Get-Command 'fds_local.bat' -ErrorAction SilentlyContinue
if ($fdsBat) {
    $fdsBat = $fdsBat.Source
}
else {
    $fdsBat = 'C:\Program Files\firemodels\FDS6\bin\fds_local.bat'
}
$fdsBin = Split-Path -Parent $fdsBat
if (Test-Path $fdsBin) {
    $env:PATH = "$fdsBin;$env:PATH"
}

# --- 3. 清掉上一次的标记 ---
foreach ($m in @('success', 'failed')) {
    $f = Join-Path $dst $m
    if (Test-Path $f) { Remove-Item $f -Force }
}

$start = Get-Date
$reason = ''

Write-Log '== FDS 3D simulation start =='
Write-Log "folder : $dst"
Write-Log "input  : $filename"
Write-Log "python : $python"
Write-Log "fds    : $fdsBat"

Push-Location $dst
try {
    # --- step 1/4: FDS ---
    Write-Log '-- step 1/4: fds --'
    if (-not (Test-Path $fdsBat)) {
        $reason = "fds_local.bat not found: $fdsBat"
    }
    elseif (-not (Test-Path (Join-Path $dst $filename))) {
        $reason = "fds input file not found: $filename"
    }
    else {
        & $fdsBat $filename
        $devcCsv = @(Get-ChildItem -Filter '*_devc.csv' -File -ErrorAction SilentlyContinue)
        $plt3d = @(Get-ChildItem -Filter '*.q' -File -ErrorAction SilentlyContinue)
        if ($devcCsv.Count -eq 0) {
            $reason = 'fds did not produce any *_devc.csv'
        }
        elseif ($plt3d.Count -eq 0) {
            $reason = 'fds did not produce any PL3D .q file'
        }
        else {
            Write-Log "fds output: $($devcCsv[0].Name), PL3D files: $($plt3d.Count)"
        }
    }

    # --- step 2/4: PL3D .q -> ./p3d/*.txt ---
    if (-not $reason) {
        Write-Log '-- step 2/4: fds2ascii -> ./p3d --'
        & $python (Join-Path $scriptDir 'p3d2txt.py')
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $dst 'p3d/index.json'))) {
            $reason = 'p3d2txt did not produce p3d/index.json'
        }
    }

    # --- step 3/4: ./p3d/*.txt -> ./volume/*.bin + frames.json ---
    if (-not $reason) {
        Write-Log '-- step 3/4: volume bins + frames.json --'
        & $python (Join-Path $scriptDir 'p3d2volume.py')
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $dst 'frames.json'))) {
            $reason = 'p3d2volume did not produce frames.json'
        }
    }

    # --- step 4/4: 校验体数据 ---
    if (-not $reason) {
        Write-Log '-- step 4/4: verify volume bins --'
        $bins = @(Get-ChildItem -Path (Join-Path $dst 'volume') -Filter '*.bin' -File -ErrorAction SilentlyContinue)
        Write-Log "volume bins: $($bins.Count)"
        if ($bins.Count -eq 0) {
            $reason = 'no volume .bin produced'
        }
    }
}
catch {
    $reason = "exception: $_"
}
finally {
    Pop-Location
}

$cost = (Get-Date) - $start
if ($reason) {
    Write-Log "== FAILED after $cost :: $reason =="
    Write-Marker 'failed' $reason
}
else {
    Write-Log "== SUCCESS after $cost =="
    Write-Marker 'success' ("finished at {0}, total {1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $cost)
}
