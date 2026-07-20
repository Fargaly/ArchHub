param(
  [int]$TimeoutSec = 35,
  [switch]$Watch,
  [string]$LogPath = "$env:TEMP\archhub_rhino_watchdog.log"
)

# Keeps the ArchHub Rhino bridge (127.0.0.1:9879) running inside the CURRENT
# visible Rhino 8 document instance. Focuses that window and pastes the start
# command (clipboard paste = autocomplete-popup-proof). Only acts when 9879 is
# dead AND a real doc window exists, so it fires rarely (on instance switch),
# not while you model.

$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type @'
using System; using System.Text; using System.Runtime.InteropServices;
public class AHB {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern int GetWindowTextLength(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  public static IntPtr Main = IntPtr.Zero;
  public static string Title = "";
  public static void Find() {
    Main = IntPtr.Zero; Title = "";
    EnumWindows(delegate(IntPtr h, IntPtr p) {
      if (!IsWindowVisible(h)) return true;
      int l = GetWindowTextLength(h); if (l <= 0) return true;
      StringBuilder sb = new StringBuilder(l + 1); GetWindowText(h, sb, sb.Capacity);
      string t = sb.ToString();
      if (t.Contains("- Rhinoceros 8")) { Main = h; Title = t; return false; }
      return true;
    }, IntPtr.Zero);
  }
  public static bool Focus(IntPtr h) {
    uint cur = GetCurrentThreadId(); IntPtr fg = GetForegroundWindow();
    uint a; GetWindowThreadProcessId(fg, out a);
    uint b; GetWindowThreadProcessId(h, out b);
    AttachThreadInput(cur, a, true); AttachThreadInput(cur, b, true);
    SetForegroundWindow(h); System.Threading.Thread.Sleep(350);
    AttachThreadInput(cur, a, false); AttachThreadInput(cur, b, false);
    return GetForegroundWindow() == h;
  }
}
'@

function Test-Bridge {
  try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', 9879); $c.Close(); return $true }
  catch { return $false }
}
function Write-WLog([string]$m) {
  ((Get-Date).ToString('HH:mm:ss') + '  ' + $m) | Out-File -Append -FilePath $LogPath -Encoding utf8
}

$scriptPath = Join-Path $env:APPDATA 'McNeel\Rhinoceros\8.0\scripts\archhub_mcp.py'
$cmd = "_-RunPythonScript $scriptPath`r`n"
$infinite = ($TimeoutSec -le 0)
$deadline = (Get-Date).AddSeconds([Math]::Max($TimeoutSec, 1))
Write-WLog ('watchdog start timeout=' + $TimeoutSec + ' watch=' + $Watch + ' infinite=' + $infinite)

do {
  if (Test-Bridge) {
    Write-WLog 'bridge already up'
    if (-not $Watch) { 'UP'; exit 0 }
    Start-Sleep -Seconds 3
    continue
  }
  [AHB]::Find()
  if ([AHB]::Main -eq [IntPtr]::Zero) { Start-Sleep -Seconds 2; continue }
  $title = [AHB]::Title
  $saved = $null
  try { $saved = Get-Clipboard -Raw } catch {}
  if ([AHB]::Focus([AHB]::Main)) {
    [System.Windows.Forms.SendKeys]::SendWait('{ESC}'); Start-Sleep -Milliseconds 150
    [System.Windows.Forms.SendKeys]::SendWait('{ESC}'); Start-Sleep -Milliseconds 200
    Set-Clipboard -Value $cmd
    if ([AHB]::Focus([AHB]::Main)) {
      [System.Windows.Forms.SendKeys]::SendWait('^v'); Start-Sleep -Milliseconds 400
      [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
      for ($i = 0; $i -lt 8; $i++) { Start-Sleep -Milliseconds 1200; if (Test-Bridge) { break } }
    }
  }
  if ($saved) { try { Set-Clipboard -Value $saved } catch {} }
  if (Test-Bridge) {
    Write-WLog ('bridge started in ' + $title)
    if (-not $Watch) { ('UP: ' + $title); exit 0 }
  } else {
    Write-WLog ('attempt failed for ' + $title)
  }
  Start-Sleep -Seconds 2
} while ($infinite -or (Get-Date) -lt $deadline)

if (Test-Bridge) { 'UP'; exit 0 } else { Write-WLog 'timeout'; 'TIMEOUT'; exit 1 }
