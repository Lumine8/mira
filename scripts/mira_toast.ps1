# mira_toast.ps1 — Mira's companion-free Windows toasts.
#
# Polls the API for self-initiated reach-outs that haven't been shown yet and
# pops each one as a real Windows toast. Works with no Electron companion and no
# browser open — just PowerShell and a registered app identity.
#
# Run once now:
#   powershell -ExecutionPolicy Bypass -File .\scripts\mira_toast.ps1 -Once
#
# Run forever (recommended — a small loop, ~15s cadence):
#   powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File .\scripts\mira_toast.ps1
#
# Needs the shared token when auth is on: pass -Token or set MIRA_ACCESS_TOKEN.
#
# How the toast works: Windows only allows toasts from an app with an App
# User Model ID, so on first run the script registers one by creating a Start
# Menu shortcut that carries the ID (a trick BurntToast popularized — no module
# needed, just user32 + WinRT). Toasts then pop through ToastNotificationManager.

param(
    [string]$ApiUrl = "http://localhost:8000",
    [string]$Token = $env:MIRA_ACCESS_TOKEN,
    [int]$PollSeconds = 15,
    [switch]$Once
)

$Aumid = "Mira.HostToasts"

# ---- register an app identity the toast system will accept -------------------

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class ToastAumid {
    [StructLayout(LayoutKind.Sequential)]
    public struct PROPERTYKEY { public Guid fmtid; public uint pid; }
    [StructLayout(LayoutKind.Sequential)]
    public struct PROPVARIANT { public ushort vt; public ushort w1, w2, w3; public IntPtr p; }
    [ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IPropertyStore {
        uint GetCount(out uint cProps);
        uint GetAt(uint iProp, out PROPERTYKEY key);
        uint GetValue(ref PROPERTYKEY key, out PROPVARIANT pv);
        uint SetValue(ref PROPERTYKEY key, ref PROPVARIANT pv);
        uint Commit();
    }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern int SHGetPropertyStoreFromParsingName(string path, IntPtr pbc, uint flags, ref Guid iid, out IPropertyStore store);
    static readonly Guid PKEY_APP_USER_MODEL_ID = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");
    public static void SetAppUserModelID(string lnkPath, string aumid) {
        var iid = typeof(IPropertyStore).GUID;
        IPropertyStore store;
        if (SHGetPropertyStoreFromParsingName(lnkPath, IntPtr.Zero, 2 /* GPS_READWRITE */, ref iid, out store) != 0) return;
        var key = new PROPERTYKEY { fmtid = PKEY_APP_USER_MODEL_ID, pid = 5 };
        var pv = new PROPVARIANT { vt = 31 /* VT_LPWSTR */, p = Marshal.StringToCoTaskMemUni(aumid) };
        try {
            store.SetValue(ref key, ref pv);
            store.Commit();
        } finally {
            Marshal.FreeCoTaskMem(pv.p);
        }
    }
}
"@

function Ensure-AppIdentity {
    $programs = [Environment]::GetFolderPath("Programs")
    if (-not $programs) { $programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs" }
    $lnkPath = Join-Path $programs "Mira Host Toasts.lnk"
    if (Test-Path -LiteralPath $lnkPath) { return }
    try {
        $ws = New-Object -ComObject WScript.Shell
        $lnk = $ws.CreateShortcut($lnkPath)
        $lnk.TargetPath = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
        $lnk.Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden"
        $lnk.Description = "Mira's companion-free toast app identity"
        $lnk.Save()
        [ToastAumid]::SetAppUserModelID($lnkPath, $Aumid)
    } catch {
        Write-Output "toast: could not register app identity: $_"
    }
}

# ---- the toast itself --------------------------------------------------------

[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

function Show-Toast {
    param([string]$Title, [string]$Body)
    try {
        $body = [System.Security.SecurityElement]::Escape($Body)
        $title = [System.Security.SecurityElement]::Escape($Title)
        $xml = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>$title</text>
      <text>$body</text>
    </binding>
  </visual>
</toast>
"@
        $doc = New-Object Windows.Data.Xml.Dom.XmlDocument
        $doc.LoadXml($xml)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $doc
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($Aumid).Show($toast) | Out-Null
        return $true
    } catch {
        Write-Output "toast: failed to pop: $_"
        return $false
    }
}

# ---- poll loop ---------------------------------------------------------------

$headers = @{}
if ($Token) { $headers["X-Mira-Token"] = $Token }

function Invoke-Poll {
    try {
        $pending = Invoke-RestMethod -Method Get -Uri "$ApiUrl/mira/toasts/pending" -Headers $headers -TimeoutSec 10
    } catch {
        return $false
    }
    foreach ($t in @($pending)) {
        if (Show-Toast -Title $t.title -Body $t.content) {
            try {
                Invoke-RestMethod -Method Post -Uri "$ApiUrl/mira/toasts/$($t.id)/delivered" -Headers $headers -TimeoutSec 10 | Out-Null
            } catch {
                Write-Output "toast: failed to mark #$($t.id) delivered"
            }
        }
    }
    return $true
}

Ensure-AppIdentity

if ($Once) {
    Invoke-Poll | Out-Null
    exit 0
}

while ($true) {
    Invoke-Poll | Out-Null
    Start-Sleep -Seconds $PollSeconds
}