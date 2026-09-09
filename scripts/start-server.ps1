# BLOODBLINK — dựng máy chủ tạm trên laptop (P3)
#
# Kiến trúc:
#   Postgres 16 + PostGIS  → chạy trong WSL Ubuntu (không có systemd, phải gọi
#                             pg_ctlcluster bằng tay sau mỗi lần WSL khởi động lại)
#   bb-core (FastAPI)      → chạy trên Windows, bind 0.0.0.0:8000 để máy khác
#                             trong tailnet gọi được qua Tailscale
#
# Dùng:  powershell -ExecutionPolicy Bypass -File scripts\start-server.ps1
#        thêm -Seed để nạp lại dữ liệu mẫu (XOÁ sạch dữ liệu đang có)

param(
    [switch]$Seed,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$core = Join-Path $repo 'bb-core'

Write-Host '== 1/4 Đánh thức WSL và khởi động Postgres ==' -ForegroundColor Cyan
# WSL2 tắt máy ảo ngay khi lệnh cuối cùng kết thúc, kéo sập luôn cầu chuyển cổng
# localhost — từ Windows nhìn vào là "WinError 1225 connection refused" dù bên
# trong Postgres vẫn online. Giữ một tiến trình sống suốt thời gian máy chủ chạy.
# (~/.wslconfig đặt vmIdleTimeout=-1 nhưng một mình nó không đủ.)
$keepAlive = Start-Process -FilePath 'wsl.exe' `
    -ArgumentList '-d','Ubuntu','-u','root','-e','sleep','infinity' `
    -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 3

wsl.exe -d Ubuntu -u root -e bash -lc "pg_ctlcluster 16 main start 2>/dev/null; pg_lsclusters | tail -1"
if ($LASTEXITCODE -ne 0) { throw 'Không khởi động được Postgres trong WSL' }

Write-Host '== 2/4 Kiểm tra kết nối từ Windows ==' -ForegroundColor Cyan
# Phải là 127.0.0.1, KHÔNG dùng localhost: localhost ra ::1 trước mà cầu chuyển
# cổng của WSL2 chỉ chuyển IPv4 → asyncpg báo WinError 1225 dù Postgres đang chạy.
Push-Location $core
python -c "import asyncio,asyncpg; asyncio.run(asyncpg.connect('postgresql://bloodblink:bloodblink@127.0.0.1:5432/bloodblink'))"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Windows không gọi được Postgres trong WSL' }

if ($Seed) {
    Write-Host '== 3/4 Nạp lại dữ liệu mẫu (xoá dữ liệu cũ) ==' -ForegroundColor Yellow
    wsl.exe -d Ubuntu -u root -e bash -lc "su postgres -c `"psql -d bloodblink -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;' -c 'CREATE EXTENSION IF NOT EXISTS postgis'`""
    $env:PYTHONIOENCODING = 'utf-8'
    python -m seed.seed_db
} else {
    Write-Host '== 3/4 Bỏ qua seed (thêm -Seed nếu muốn nạp lại) ==' -ForegroundColor DarkGray
}

Write-Host "== 4/4 Chạy bb-core trên cổng $Port ==" -ForegroundColor Cyan
$ts = (& 'C:\Program Files\Tailscale\tailscale.exe' status --json | ConvertFrom-Json).Self.DNSName.TrimEnd('.')
Write-Host "   API docs:  http://127.0.0.1:$Port/api/docs"
Write-Host "   Cho điện thoại (Tailscale):  http://${ts}:$Port/api"
Write-Host ''

$env:PYTHONIOENCODING = 'utf-8'
try {
    python -m uvicorn app.main:app --host 0.0.0.0 --port $Port
} finally {
    Pop-Location
    if ($keepAlive -and -not $keepAlive.HasExited) { Stop-Process -Id $keepAlive.Id -Force }
}
