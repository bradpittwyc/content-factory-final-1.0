param([string]$InitialPath = "")

Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Application]::EnableVisualStyles()

# 创建极小不可见置顶窗口作为宿主，保证对话框绝对浮在最上层
$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$form.Size = New-Object System.Drawing.Size(1, 1)
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.ShowInTaskbar = $false
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.Show()
$form.BringToFront()
$form.Activate()

# 使用标准的 OpenFileDialog 窗口
$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = "Open"
$dialog.ValidateNames = $false
$dialog.CheckFileExists = $false
$dialog.CheckPathExists = $true
$dialog.FileName = "进入目标文件夹后点击右下角Open即可"

if ($InitialPath -and (Test-Path $InitialPath)) {
    $dialog.InitialDirectory = $InitialPath
} elseif ($args.Count -gt 0 -and $args[0] -and (Test-Path $args[0])) {
    $dialog.InitialDirectory = $args[0]
} else {
    $dialog.InitialDirectory = [Environment]::GetFolderPath("Desktop")
}

$res = $dialog.ShowDialog($form)

if ($res -eq [System.Windows.Forms.DialogResult]::OK) {
    $selectedPath = $dialog.FileName
    if ([System.IO.Directory]::Exists($selectedPath)) {
        $finalFolder = $selectedPath
    } else {
        $finalFolder = [System.IO.Path]::GetDirectoryName($selectedPath)
    }
    if ([string]::IsNullOrWhiteSpace($finalFolder)) {
        $finalFolder = $selectedPath
    }
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::Write($finalFolder)
}

$form.Dispose()
