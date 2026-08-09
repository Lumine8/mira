# Relaunch a dedicated Chrome (its own profile dir) with the CDP debug port
# Mira needs, bound to localhost only. This is the user's own Chrome browser,
# but with a *separate* profile folder (Chrome 136+ refuses --remote-debugging
# on the default profile). The user logs into X in this window once; the session
# persists in the profile, so Mira's posts ride the real logged-in browser.
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = "$env:LOCALAPPDATA\MiraXProfile"

if (!(Test-Path $chrome)) { Write-Error "chrome not found at $chrome"; exit 1 }
New-Item -ItemType Directory -Force -Path $profile | Out-Null

$existing = Get-Process chrome -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -eq $chrome }
if ($existing) {
  # Only stop the *Mira* profile instance (its window title carries the profile),
  # leaving the user's normal Chrome untouched.
  Write-Output "Stopping any existing MiraXProfile Chrome instance..."
  Get-CimInstance Win32_Process -Filter "name='chrome.exe'" |
    Where-Object { $_.CommandLine -like "*MiraXProfile*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
}

Write-Output "Launching Mira's Chrome (profile: $profile) with debug port 9222..."
Start-Process -FilePath $chrome -ArgumentList @(
  "--user-data-dir=`"$profile`"",
  "--remote-debugging-port=9222",
  "--remote-debugging-address=127.0.0.1",
  "--no-first-run",
  "--no-default-browser-check"
)

$deadline = (Get-Date).AddSeconds(25)
$ok = $false
while ((Get-Date) -lt $deadline) {
  try {
    $v = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:9222/json/version" -TimeoutSec 3
    Write-Output "CDP up: $($v.Content.Substring(0, [Math]::Min(220, $v.Content.Length)))"
    $ok = $true
    break
  } catch { Start-Sleep -Milliseconds 500 }
}
if (!$ok) { Write-Output "CDP did not come up in time."; exit 2 }