# file: runme.ps1
#
# 在单个模拟目录里跑完 FDS -> fds2ascii -> gif 三步，
# 最后按产物判定成功与否，落 success / failed 标记文件。
#
# 由 python/fds/simulate.py 调用：
#   powershell -ExecutionPolicy Bypass -File runme.ps1 `
#       -folder <会话目录> -filename template.fds -python <python.exe>

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

# --- 1. 定位运行目录（相对路径按 fds/ 解析）---
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

Write-Log '== FDS simulation start =='
Write-Log "folder : $dst"
Write-Log "input  : $filename"
Write-Log "python : $python"
Write-Log "fds    : $fdsBat"

Push-Location $dst
try {
    # --- step 1/3: FDS ---
    Write-Log '-- step 1/3: fds --'
    if (-not (Test-Path $fdsBat)) {
        $reason = "fds_local.bat not found: $fdsBat"
    }
    elseif (-not (Test-Path (Join-Path $dst $filename))) {
        $reason = "fds input file not found: $filename"
    }
    else {
        & $fdsBat $filename
        $devcCsv = @(Get-ChildItem -Filter '*_devc.csv' -File -ErrorAction SilentlyContinue)
        if ($devcCsv.Count -eq 0) {
            $reason = 'fds did not produce any *_devc.csv'
        }
        else {
            Write-Log "fds output: $($devcCsv[0].Name)"
        }
    }

    # --- step 2/3: fds2ascii -> ./output ---
    if (-not $reason) {
        Write-Log '-- step 2/3: fds2ascii -> ./output --'
        & $python (Join-Path $scriptDir 'fds2txt.py')
        $txtCount = @(Get-ChildItem -Path (Join-Path $dst 'output') -Filter '*.txt' -File -ErrorAction SilentlyContinue).Count
        Write-Log "slice text files: $txtCount"
        if ($txtCount -eq 0) {
            $reason = 'fds2txt produced no slice text file'
        }
    }

    # --- step 3/3: frames + gif ---
    if (-not $reason) {
        Write-Log '-- step 3/3: frames + generated.gif --'
        & $python (Join-Path $scriptDir 'txt2gif.py')
        if (-not (Test-Path (Join-Path $dst 'generated.gif'))) {
            $reason = 'txt2gif produced no generated.gif'
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
