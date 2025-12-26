# file: runme.ps1

param(
    [Parameter(Mandatory=$true)]
    [string]$folder,

    [Parameter(Mandatory=$true)]
    [string]$filename
)

$cwd = Get-Location

mkdir $folder -ErrorAction SilentlyContinue
cp $filename $folder/

# Start time
$date = Get-Date
Write-Host "Simulation started at: $date"

cd $folder

fds_local.bat $filename

$t1 = (Get-Date) - $date

python $cwd/fds2txt.py

$t2 = (Get-Date) - $date

python $cwd/txt2gif.py

$t3 = (Get-Date) - $date

cd $cwd

# End time, with time consuming
$cost = (Get-Date) - $date
Write-Host "Simulation ended at: $(Get-Date)"
Write-Host "Total time consuming: $cost ($t1, $t2, $t3)"
