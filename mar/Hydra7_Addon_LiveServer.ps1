#######################################################################
#                                                                     #
#  Hydra Addon - Live Server                                          #
#    Exposes Hydra live state over HTTP (read-only, localhost)        #
#                                                                     #
#  Endpoints: /objects  /running  /stats  /livestatus                 #
#  Enabled with: Hydra7.ps1 -UseLiveServer [-LiveServerPort 8765]     #
#                                                                     #
#######################################################################

if (!$UseLiveServer) { return }  # Only started with -UseLiveServer (port set by -LiveServerPort)

$Script:LiveServerData=[hashtable]::Synchronized(@{ Objects=@(); Stats=@(); LiveStatus=@{}; Updated=$null; Listener=$null })

# Snapshot builder: runs on the UI thread, copies state into plain objects
$Script:LiveServerTimer=New-Object System.Windows.Forms.Timer
$Script:LiveServerTimer.Interval=1000
$Script:LiveServerTimer.Add_Tick({
  try {
    $Snap=foreach ($Tab in $DataGridItemSource) {
      foreach ($Obj in @($Tab)) {
        if ($Obj.Objects -and ($Obj.Objects -ne "DummyPlaceHolder")) {
          [pscustomobject]@{
            Object=[string]$Obj.Objects; State=[string]$Obj.State; Step=$Obj.Step
            InProgress=[bool]$Obj.InProgress; TaskResults=[string]$Obj.TaskResults
            SequenceID=$Obj.SequenceID; Tab=$Obj.Tab
          }
        }
      }
    }
    $Stats=@($SequenceStats | Where-Object { $_.SequenceName } |
      Select-Object SequenceName,NbOfObjects,StartTime,EndTime,OK,BREAK,STOP,END,CANCEL,ERROR)
    $Live=@{}
    foreach ($k in @($LiveStatus.Keys)) { $Live[[string]$k]=[string]$LiveStatus[$k] }

    $LiveServerData.Objects=@($Snap)
    $LiveServerData.Stats=$Stats
    $LiveServerData.LiveStatus=$Live
    $LiveServerData.Updated=Get-Date -Format "o"
  }
  catch {}
})

# HTTP listener: runs in its own runspace, only reads the snapshot
$Script:LiveServerPS=[PowerShell]::Create()
[void]$LiveServerPS.AddScript({
  param($Data, $Port)
  $Listener=New-Object System.Net.HttpListener
  $Listener.Prefixes.Add("http://localhost:$Port/")
  $Listener.Start()
  $Data.Listener=$Listener
  while ($Listener.IsListening) {
    try { $Ctx=$Listener.GetContext() } catch { break }  # Stop() unblocks GetContext
    try {
      $Code=200
      switch ($Ctx.Request.Url.AbsolutePath) {
        "/objects"    { $Body=@{ Updated=$Data.Updated; Objects=$Data.Objects } | ConvertTo-Json -Depth 4 }
        "/stats"      { $Body=@{ Updated=$Data.Updated; Stats=$Data.Stats } | ConvertTo-Json -Depth 4 }
        "/livestatus" { $Body=$Data.LiveStatus | ConvertTo-Json -Depth 3 }
        "/running"    { $Body=ConvertTo-Json -InputObject @($Data.Objects | Where-Object InProgress) -Depth 4 }
        default       { $Code=404; $Body='{"error":"not found"}' }
      }
      $Bytes=[Text.Encoding]::UTF8.GetBytes([string]$Body)
      $Ctx.Response.StatusCode=$Code
      $Ctx.Response.ContentType="application/json; charset=utf-8"
      $Ctx.Response.OutputStream.Write($Bytes, 0, $Bytes.Length)
    }
    catch {}
    finally { $Ctx.Response.Close() }
  }
}).AddArgument($LiveServerData).AddArgument($LiveServerPort)

$Script:LiveServerHandle=$LiveServerPS.BeginInvoke()
$Script:LiveServerTimer.Start()

# Clean shutdown when Hydra closes
$Form.Add_Closed({
  $LiveServerTimer.Stop()
  if ($LiveServerData.Listener) { $LiveServerData.Listener.Stop() }
  $LiveServerPS.Dispose()
})
