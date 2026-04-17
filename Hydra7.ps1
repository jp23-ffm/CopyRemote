#######################################################################
#                                                                     #
#  Hydra 7 (Honey Badger)                                             #
#                                                                     #
#                                                                     #
# Version 7.5.6  (22.08.2023)                                         #
#                                                                     #
#  - New: PanelSize option for variables                              #
#  - New: New option DisplaySeparator for combobox & multiCheckbox    #
#  - New: New variable type Cancel                                    #
#  - Fix: Escaped commas better interpreted in objects creation       #
#                                                                     #
#                                                               J.P.  #
#######################################################################



Param(  # Optional script and start parameters 

  [Parameter(Mandatory=$False,Position=0)] $SequencesListParam,
  [parameter(Mandatory=$False)] $Profile='',
  [parameter(Mandatory=$False)] [Switch] $SkipGroupCheck=$False,
  [parameter(Mandatory=$False)] $SplashScreenPath=$Null,
  [parameter(Mandatory=$False)] $IconPath=$Null,
  [parameter(Mandatory=$False)] $Title="Hydra",
  [parameter(Mandatory=$False)] [ValidateSet($True,$False)] $AutoRun=$False,
  [parameter(Mandatory=$False)] $AutoRunBundle="",
  [parameter(Mandatory=$False)] $AutoRunObjects="",
  [parameter(Mandatory=$False)] $AutoRunSequence="",
  [parameter(Mandatory=$False)] $AutoRunVariables="",
  [parameter(Mandatory=$False)] [ValidateSet('CSV','HTML','XLSX')] $AutoRunExport="",
  [parameter(Mandatory=$False)] $AutoRunExportPath="",
  [parameter(Mandatory=$False)] [ValidateSet($True,$False)] $AutoRunExportTimeStamp=$False,
  [parameter(Mandatory=$False)] $Settings="",
  [parameter(Mandatory=$False)] [ValidateSet($True,$False)] $PathsCheck=$True

)


function Add-GridColumn($Grid, $nbCol) {

  $CurrentNbOfCols=@($Grid.Content.Columns | Where-Object Header -like "Param*").Count

  if ($CurrentNbOfCols -lt $nbCol) {

    (($CurrentNbOfCols+1)..$nbCol) | ForEach-Object {
      $ColNumber=$_ -1
      $DataGridTextColumn=New-Object System.Windows.Controls.DataGridTextColumn
      $DataGridTextColumn.Header="Param $($ColNumber+1)"
      [System.Windows.Data.Binding]$Bindings=New-Object System.Windows.Data.Binding
      $Bindings.Path="AddParams[$ColNumber]"
      $Bindings.UpdateSourceTrigger="PropertyChanged"
      $Bindings.NotifyOnTargetUpdated=$True
      $Bindings.Mode="TwoWay"
      $DataGridTextColumn.Binding=$Bindings
      $DataGridTextColumn.MinWidth="50"
      $DataGridTextColumn.Width="100"
      $DataGridTextColumn.DisplayIndex=$ColNumber+2
      $DataGridObjectsCellFonts=$Form.FindResource("DataGridObjectsCellFonts")
      $DataGridTextColumn.CellStyle=$DataGridObjectsCellFonts
      $Grid.Content.Columns.Add($DataGridTextColumn)
    }
    $Script:TabObjectAdditionalParams[$Grid.Content.Tag]=$nbCol

  }

}


function Add-ItemsAdditionalParams($GridID, $ItemsToAdd) {

  $DataGridItemSource[$GridID] | ForEach-Object {

    $ItemAddParam=$_.AddParams
    for ($i=$ItemAddParam.Count; $i -lt $ItemsToAdd; $i++) {
      $ItemAddParam+=""
    }
    $_.AddParams=$ItemAddParam

  }

}


function Cancel-Sequence($SelectionOnly=$True) {

  # Cancel the selected or all objects running

  if ($SelectionOnly -eq $True) {  # Determine the objects to cancel
    filter myFilter { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
    $ObjectsToCancel=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter | Select-Object -ExpandProperty Item  # Get the selected States, removing the last line (placeholder) if it is selected
  }
  else {
    filter myFilter1 { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
    filter myFilter2 { if ($_.InProgress -eq $True) { $_ } }
    $ObjectsToCancel=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource) | myFilter1 | myFilter2
  }

  foreach ($Obj in $ObjectsToCancel) {  # Set the parameters to Cancel values
    $Obj.InProgress=$False
    $Obj.IsEnabled=$True
    $Obj.TaskResults="CANCEL"
    $Obj.TaskResultsExport="CANCEL"
    $Obj.State="CANCEL at step $($Obj.Step)"
    $Obj.IsChecked=$False
    $Obj.SharedVariable=$Null
    $Obj.Color=$Colors.Get_Item("CANCELLED")
    if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);CANCEL;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
    }
    $Obj.Step=0
    $Obj.StepToString="0"
    $Script:ObjectsCounting[$Obj.Tab]++
    if ([string]::IsNullOrEmpty($Obj.Historic)) {  # First Step
      $Obj.Historic+=$Obj.Objects
    }
    $Obj.Historic+="Cancelled on $(Get-Date -Format "HH:mm:ss")"
    $Obj.TaskHistory+="Cancelled on $(Get-Date -Format "HH:mm:ss")"
    $Script:SequenceLog[$Obj.SequenceID]+=$(Get-Date -Format "dd.MM.yyyy") + " ; " + ($Obj.Historic -join " ;")
    $Script:SequenceStats[$Obj.SequenceID].Cancel++
    $Script:SequenceStats[$Obj.SequenceID].NbOfObjects++
    if ((Get-Date) -gt $SequenceStats[$Obj.SequenceID].EndTime) { $Script:SequenceStats[$Obj.SequenceID].EndTime=Get-Date }
    Get-IfPreLoad $Obj
  }

  foreach ($Obj in $ObjectsToCancel) { 
    if ($Obj.TimeRemaining -ne "") {
      $Schedule=$SequenceSettings[$Obj.SequenceID].Schedule
      if ($Schedule -ne $Null) {
        if ($Schedule.ToShortDateString() -eq (Get-Date).ToShortDateString()) {  # The scheduler will start later than today
          $Obj.State=$Schedule.ToLongTimeString()
        }
        else {
          $Obj.State=$Schedule.ToShortTimeString() + " (" + $Schedule.ToShortDateString() + ")"
        }
      }
      else {
        $Obj.State="Pending"
      }
    }
  }

  Set-State

}


function Check-AllObjects($Action) {

  # Check or uncheck all objects of the current grid
  
  filter myFilter1 { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
  filter myFilter2 { if (($_.Step -eq 0) -and ($_.InProgress -eq $False)) { $_ } }
  $AllObjects=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource) | myFilter1 | myFilter2  # Get all objects not currently running and not hidden
  foreach ($Obj in $AllObjects) {
    $Obj.IsChecked=$Action
  }

  Set-State

}


function Check-Bundle {

  # Check if some bundles are defined or not to show or hide the column

  filter myFilter { if ($_.Bundle -eq $True) { $_ } }  
  $ObjectsInBundle=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter

  if (@($ObjectsInBundle).Count -gt 0) {  # Bundles are set
    $ObjectsTabControl.SelectedItem.Content.Columns[4].Visibility="Visible"
  }
  else {
    $ObjectsTabControl.SelectedItem.Content.Columns[4].Visibility="Collapsed"
  }

}


function Check-Objects($Action) {

  # Check or uncheck the selected objects of the current grid

  filter myFilter1 { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
  filter myFilter2 { if ($_.Step -eq 0) { $_ } }
  $ObjectsToCheck=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter1 | Select-Object -ExpandProperty Item | myFilter2  # Get all selected objects not currently running
  foreach ($Object in $ObjectsToCheck) {
    $Object.IsChecked=$Action
  }

  Set-State

}


function Check-TempPaths($ToTest, $Question=$False) {

  if ($PathsCheck -eq $False) { return }  # Disable the check of the temp Paths to avoid load issues and freeze on the Settings window on some systems

  $PathsChecked=@()

  $Totest.GetEnumerator() | ForEach-Object {

    $File=$_.Value
    $Description=$_.Name

    if ([System.IO.File]::Exists($File)) {  # The file exists
      try {
        $FileStream=[System.IO.File]::Open($File,'Open','Write')
        $FileStream.Close()
        $FileStream.Dispose()
        $RW=$True
      } 
      Catch {
        $RW=$False
      }
      $PathsChecked+=[pscustomobject]@{
        File=$File
        Desc=$Description
        RW=$RW
      }
    }
    else {
      try {
        New-Item $File -ItemType File -Force -ErrorAction Stop | Remove-Item -Force -ErrorAction Stop | Out-Null
        $RW=$True
      }
      catch {
        $RW=$False
      }

      $PathsChecked+=[pscustomobject]@{
        File=$File
        Desc=$Description
        RW=$RW
      }

    }

  }

  if ($Question -eq $True) {
    $Msg="Do you want to set them again ?"
    $Buttons=2
  }
  else {
    $Msg="Please set the paths in the Settings."
    $Buttons=1
  }

  if ($PathsChecked | Where-Object { $_.RW -eq $false }) {
    $PathsPb=($PathsChecked | Where-Object { $_.RW -eq $false } | Select-Object @{ l="Res" ; exp={"$($_.Desc) : $($_.File)" } } | Select-Object -ExpandProperty Res) -join "`r`n"
    $Answer=MessageBox "Paths" "Following paths are not accessible or not writable:`r`n`r`n$PathsPb`r`n`r`n$msg" 2 $Buttons
  }
  else {
    return $False
  }
  
  if ($Question -eq $True) {
    return $Answer
  }
  else {
    return $False
  }

}


function Clear-Grid {  

  # Clear the Grid

  if ($CellEditing -eq $True) {  # A cell is in edit mode
    return
  }

  filter myFilter { if ($_.Step -ne 0 ) { $_ } }
  $ObjectsRunning=@($DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter).Count  # Count the objects running
  if ($ObjectsRunning -gt 0) {  # Some objects are in progress
    MessageBox "Clear Grid" "Unable to clear the grid: some objects are still running" 3 1
    return
  }

  $ReallyClear=(MessageBox "WARNING" "Do you really want to clear the grid ?`r`nThis will delete all objects." 4 2)
  if ($ReallyClear -ne "yes") {
    return
  }

  $DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag].Clear()

  Check-Bundle  # Check the Bundles in use
  Set-State

  if ($UseClassicMenu -eq "False") {  # Actualize the Bundle menu
    RibbonSetBundle
  }
  else {
    ClassicMenuSetBundle
  }

}


function Convert-GroupToTabs {

  # Convert Groups in Tabs

  $GridDefaultView=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)
  filter myFilter { if ($_.PSObject.Properties.Item("Name")) { $_ } }
  $Groups=$GridDefaultView.Groups | myFilter  # Get the groups
  $GroupCount=@($Groups).Count
  
  if ($GroupCount -eq 0) {
    MessageBox "Split to Tabs" "No group defined." 1 1
    return
  }
  if ($GroupCount -gt 5) {
    $CreateTabs=MessageBox "Split to Tabs" "This operation would create $GroupCount Tabs.`r`n`r`nAre you sure to continue ?" 2 2
    if ($CreateTabs -eq "No") {
      return
    }
  }

  $SequenceFullPath=$HydraBinPath  # Fake the $SequenceFullPath to avoid any error
  $NameOrFull=Read-ComboBoxDialog "Split Groups" "How do you want to create the objects:" "Create the Objects with their Task Results,Create the Objects with their Name only"
  if ($NameOrFull -eq "") { return }  # Action cancelled

  for ($i=0; $i -lt $GroupCount; $i++) {  # Loop in the groups
    & $CreateANewTab $True  # Create a new tab
    $TabTag=$TabLastIndex
    $Groups[$i].Items | ForEach-Object {  # Create all objects
      if ($NameOrFull -like "*Name only") {
        Set-ObjectSettings $($_.Objects) -GridItemTag $TabTag
      }
      else {
        Set-ObjectSettings $_.Objects -GridItemTag $TabTag -TaskResult $_.TaskResults -TaskResultExport $_.TaskResultsExport -State $_.State -SequenceName $_.SequenceName -Step $_.Step -Checked $True -Color $_.Color -CellFontFormated $_.CellFontFormated -CellFontFamily $_.CellFontFamily -CellFontColor $_.CellFontColor -CellFontSize $_.CellFontSize -CellFontStyle $_.CellFontStyle -CellFontWeight $_.CellFontWeight -Hidden $_.Hidden -AddParams $_.AddParams # Create the objects in the grid
      }
    }
   & $TabItemLoaded
   $ObjectsTabControl.SelectedItem.Header=$Groups[$i].Name  # Renamw the tab
  }

}


function CopyToTab($TabTag, $Move=$False, $NewTab=$False, $FullParams=$False) {  

  # Copy or move objects to another tab

  if ($Move -eq $False) {  # Copy: all objects can be used
    filter myFilter { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
    $SelectedObjects=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter | Select-Object -ExpandProperty Item  # Get the selected objects, removing the last line (placeholder) if it is selected
  }
  else {  # Move: only non running objects can be moved
    filter myFilter1 { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
    filter myFilter2 { if ($_.Step -eq 0) { $_ } }
    $SelectedObjects=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter1 | Select-Object -ExpandProperty Item | myFilter2  # Get the selected non-running objects, removing the last line (placeholder) if it is selected
  }

  $TabToRemoveFrom=$ObjectsTabControl.SelectedItem.Tag

  if ($NewTab -eq $True) {  # Create a tab if necessary
    & $CreateANewTab -Focus $True -AddParams $TabObjectAdditionalParams[$TabToRemoveFrom]
    $TabTag=$TabLastIndex
  }
  else {
    if ($TabObjectAdditionalParams[$TabToRemoveFrom] -gt $TabObjectAdditionalParams[$TabTag]) {
      $Script:TabObjectAdditionalParams[$TabTag]=$TabObjectAdditionalParams[$TabToRemoveFrom]
    }
  }

  foreach ($Obj in $SelectedObjects) {  # Create a copy of the objects in the other tab
    if ($FullParams) {
      Set-ObjectSettings $Obj.Objects -GridItemTag $TabTag -TaskResult $Obj.TaskResults -TaskResultExport $Obj.TaskResultsExport -State $Obj.State -SequenceName $Obj.SequenceName -Step $Obj.Step -Checked $True -Color $Obj.Color -CellFontFormated $Obj.CellFontFormated -CellFontFamily $Obj.CellFontFamily -CellFontColor $Obj.CellFontColor -CellFontSize $Obj.CellFontSize -CellFontStyle $Obj.CellFontStyle -CellFontWeight $Obj.CellFontWeight -Hidden $Obj.Hidden -AddParams $Obj.AddParams # Create the objects in the grid
    }
    else {
      Set-ObjectSettings $($Obj.Objects) -GridItemTag $TabTag
    }
    if ($Move -eq $True) {  # Delete the selected objects in case of a move
      $DataGridItemSource[$TabToRemoveFrom].Remove($Obj) | Out-Null
    }
  }

  if ($NewTab -eq $False) {
    Add-GridColumn $($ObjectsTabControl.Items | Where-Object Tag -eq $TabTag) $TabObjectAdditionalParams[$TabTag]
  }

  Set-State

}


$CreateANewTab={  # Create a Tab with its grid associated

  param ($Focus=$True, $OnLoad=$True, $AddParams=0)

  # Create a new Tab, with a DataGrid and Columns parameters

  $Script:TabLastIndex++

  $DataGrid=New-Object System.Windows.Controls.DataGrid
  $DataGrid.GridLinesVisibility="Horizontal"
  $DataGrid.HorizontalGridLinesBrush="DarkGray"

  $DataGridCheckBoxColumn=New-Object System.Windows.Controls.DataGridTemplateColumn
  $DataGridCheckBoxColumn.Header=""
  $DataGridCheckBoxColumn.CanUserResize=$False
  $DataGridStateTemplate=$Form.FindResource("DataGridCheckBoxTemplate")
  $DataGridCheckBoxColumn.CellTemplate=$DataGridStateTemplate
  $DataGridCheckBoxCellFonts=$Form.FindResource("DataGridCellFocus")
  $DataGridCheckBoxColumn.CellStyle=$DataGridCheckBoxCellFonts
  $DataGrid.Columns.Add($DataGridCheckBoxColumn)

  $DataGridTextColumn=New-Object System.Windows.Controls.DataGridTextColumn
  $DataGridTextColumn.Header="Objects"
  [System.Windows.Data.Binding]$Bindings=New-Object System.Windows.Data.Binding
  $Bindings.Path="Objects"
  $Bindings.UpdateSourceTrigger="PropertyChanged"
  $Bindings.NotifyOnTargetUpdated=$True
  $Bindings.Mode="TwoWay"
  $DataGridTextColumn.Binding=$Bindings
  $DataGridTextColumn.MinWidth="120"
  $DataGridTextColumn.Width="120"
  $DataGridObjectsCellFonts=$Form.FindResource("DataGridObjectsCellFonts")
  $DataGridTextColumn.CellStyle=$DataGridObjectsCellFonts
  $DataGrid.Columns.Add($DataGridTextColumn)

  $DataGridTextColumn=New-Object System.Windows.Controls.DataGridTextColumn
  $DataGridTextColumn.Header="Task Results"
  [System.Windows.Data.Binding]$Bindings=New-Object System.Windows.Data.Binding
  $Bindings.Path="TaskResults"
  $Bindings.UpdateSourceTrigger="PropertyChanged"
  $Bindings.NotifyOnTargetUpdated=$True
  $Bindings.Mode="TwoWay"
  $DataGridTextColumn.Binding=$Bindings
  $DataGridTextColumn.MinWidth="400"
  $DataGridTextColumn.Width="*"
  $DataGridResultsCellFonts=$Form.FindResource("DataGridResultsCellFonts")
  $DataGridTextColumn.CellStyle=$DataGridResultsCellFonts
  $DataGridCellElementStyle=$Form.FindResource("DataGridCellElementStyle")
  $DataGridTextColumn.ElementStyle=$DataGridCellElementStyle
  $DataGrid.Columns.Add($DataGridTextColumn)

  $DataGridTemplateColumn=New-Object System.Windows.Controls.DataGridTemplateColumn
  $DataGridTemplateColumn.Header="State"
  $DataGridStateTemplate=$Form.FindResource("DataGridStateTemplate")
  $DataGridTemplateColumn.CellTemplate=$DataGridStateTemplate
  $DataGridTemplateColumn.SortMemberPath="State"
  $DataGridTemplateColumn.MinWidth="120"
  $DataGridTemplateColumn.Width="120"
  $DataGridResultsCellFonts=$Form.FindResource("DataGridCellFocus")
  $DataGridTemplateColumn.CellStyle=$DataGridResultsCellFonts
  $DataGrid.Columns.Add($DataGridTemplateColumn)

  $DataGridTemplateColumn=New-Object System.Windows.Controls.DataGridTemplateColumn
  $DataGridTemplateColumn.Header="Bundle"
  $DataGridBundleTemplate=$Form.FindResource("DataGridBundleTemplate")
  $DataGridTemplateColumn.CellTemplate=$DataGridBundleTemplate
  $DataGridTemplateColumn.MinWidth="120"
  $DataGridTemplateColumn.Width="120"
  $DataGridBundleCellFonts=$Form.FindResource("DataGridCellFocus")
  $DataGridTemplateColumn.CellStyle=$DataGridBundleCellFonts
  $DataGrid.Columns.Add($DataGridTemplateColumn)
  
  $DataGridTextColumn=New-Object System.Windows.Controls.DataGridTextColumn
  $DataGridTextColumn.Header="Color"
  [System.Windows.Data.Binding]$Bindings=New-Object System.Windows.Data.Binding
  $Bindings.Path="Color"
  $Bindings.UpdateSourceTrigger="PropertyChanged"
  $Bindings.NotifyOnTargetUpdated=$True
  $Bindings.Mode="TwoWay"
  $DataGridTextColumn.Binding=$Bindings
  $DataGridTextColumn.MinWidth="0"
  $DataGridTextColumn.MaxWidth="0"
  $DataGridTextColumn.Width="0"
  $DataGridBundleCellFonts=$Form.FindResource("DataGridCellFocus")
  $DataGridTextColumn.CellStyle=$DataGridBundleCellFonts
  $DataGrid.Columns.Add($DataGridTextColumn)
  
  $DataGridTextColumn=New-Object System.Windows.Controls.DataGridTextColumn
  $DataGridTextColumn.Header="Sequence Name"
  [System.Windows.Data.Binding]$Bindings=New-Object System.Windows.Data.Binding
  $Bindings.Path="SequenceName"
  $Bindings.UpdateSourceTrigger="PropertyChanged"
  $Bindings.NotifyOnTargetUpdated=$True
  $Bindings.Mode="TwoWay"
  $DataGridTextColumn.Binding=$Bindings
  $DataGridTextColumn.MinWidth="150"
  $DataGridBundleCellFonts=$Form.FindResource("DataGridCellFocus")
  $DataGridTextColumn.CellStyle=$DataGridBundleCellFonts
  $DataGrid.Columns.Add($DataGridTextColumn)

  $DataGrid.CanUserAddRows=$true
  $DataGrid.SelectionMode="Extended"
  $DataGrid.SelectionUnit="CellOrRowHeader"
  $DataGrid.AutoGenerateColumns=$False
  $DataGrid.Columns[2].IsReadOnly=$True  # Task Results can't be manually modified
  $DataGrid.Columns[3].IsReadOnly=$True  # State can't be manually modified
  $DataGrid.Columns[4].Visibility="Collapsed" 
  $DataGrid.Columns[4].IsReadOnly=$True  # Bundle can't be manually modified
  $DataGrid.Columns[5].Visibility="Collapsed"  # Color
  if ($ShowSequenceName -eq $True) {  # Sequence Name
   $DataGrid.Columns[6].Visibility="Visible"
  }
  else {
    $DataGrid.Columns[6].Visibility="Collapsed"
  }
  $DataGrid.Columns[6].IsReadOnly=$True  # Sequence Name can't be manually modified
  
  $DataGrid.HorizontalScrollBarVisibility="Disabled"
  
  $DataGridRowStyle=$Form.FindResource("DataGridRowStyle")
  $DataGrid.RowStyle=$DataGridRowStyle
  
  $Script:GridFilter+=""  # Reset the filter for this grid
  $Script:TabObjectAdditionalParams+=0

  $Script:ObjectsCounting+=0

  $DataGrid.Tag=$TabLastIndex
  $DataGrid.MinRowHeight=20
  $DataGrid.ColumnHeaderHeight=24
    
  $DataGridGroupStyle=New-Object System.Windows.Controls.GroupStyle
  $DataGridGroupStyle.ContainerStyle=$Form.FindResource("GroupHeaderStyle")
  $DataGrid.GroupStyle.Add($DataGridGroupStyle)
  $DataGrid.SetValue([System.Windows.Controls.VirtualizingPanel]::IsVirtualizingWhenGroupingProperty, $True)  # Some tweaks to speed up the rendering when Group Styles are used
  $DataGrid.SetValue([System.Windows.Controls.VirtualizingPanel]::IsVirtualizingProperty, $True)
  $DataGrid.SetValue([System.Windows.Controls.VirtualizingPanel]::VirtualizationModeProperty, [System.Windows.Controls.VirtualizationMode]::Recycling)
  $DataGrid.SetValue([System.Windows.Controls.ScrollViewer]::IsDeferredScrollingEnabledProperty, $False)
  $DataGrid.EnableRowVirtualization=$True
  $DataGrid.EnableColumnVirtualization=$True
  
  $Script:DataGridItemSource+=,(New-Object System.Collections.ObjectModel.ObservableCollection[Object])
  $Script:DataGridItemSource[$TabLastIndex].Clear()
  $DataGrid.ItemsSource=$DataGridItemSource[$TabLastIndex]

  $ContextMenu=New-Object System.Windows.Controls.ContextMenu
  $DataGrid.ContextMenu=$ContextMenu
  
  # Datagrid Events 
  $DataGrid.Add_AddingNewItem( $DataGridAddingNewItem )
  $DataGrid.Add_CellEditEnding( $DataGridCellEditEnding )
  $DataGrid.Add_ContextMenuOpening( $DataGridContextMenuOpening )
  $DataGrid.Add_CurrentCellChanged( $DataGridCurrentCellChanged )
  $DataGrid.Add_PreviewKeyDown( $DataGridKeyDown )
  $DataGrid.Add_PreparingCellForEdit( $DataGridPreparingCellForEdit )
  $DataGrid.Add_Sorting( $DataGridSorting )
  $DataGrid.Add_PreviewMouseDoubleClick( $DataGridPreviewMouseDoubleClick )
  $DataGrid.FocusVisualStyle=$Null
  $DataGrid.Background=$ColorPanels

  $TabItem=New-Object System.Windows.Controls.TabItem
  $TabItem.Header="Tab $TabLastIndex"
  $TabItem.Tag=$TabLastIndex
  $TabItem.Style=$Form.FindResource("TabStyle$Tabstyle")
  $TabItem.FocusVisualStyle=$Null
  $ContextTabMenu=New-Object System.Windows.Controls.ContextMenu
  $ContextTabMenu.Add_Loaded( $ContextTabMenuLoaded )
  $TabItem.ContextMenu=$ContextTabMenu
  $TabItem.AddChild($DataGrid)

  # Tab Events
  $TabItem.Add_Loaded( $TabItemLoaded )
  $TabItem.Add_PreviewMouseMove( $TabItemPreviewMouseMove )
  $TabItem.Add_MouseUp( $TabItemPreviewMouseUp )

  $ObjectsTabControl.Items.Insert($($ObjectsTabControl.Items.Count)-1, $TabItem)
  if ($Focus) {
    $ObjectsTabControl.SelectedItem=$TabItem
  }

  # Set the column headers
  Set-ColumnTemplate 1
  Set-ColumnTemplate 2
  Set-ColumnTemplate 3
  Set-ColumnTemplate 4
  Set-ColumnTemplate 6

  Set-ObjectSettings "DummyPlaceHolder" -GridItemTag $TabLastIndex  # Create a dummy placeholder that will be removed: necessary to get an empty line in the grid

  if ($AutoRun -eq $True) {

    if (!([string]::IsNullOrEmpty($AutoRunExportPath))) {  # Check if an auto export will be necessary
      $AutoRunExportPathFolder=Split-Path $AutoRunExportPath -Parent
      if (!(Test-Path $AutoRunExportPathFolder)) {
        New-Item -Path $AutoRunExportPathFolder -ItemType Directory
      }
    }
    if ($AutoRunSequence -ne "") {
      if ((Test-Path $AutoRunObjects) -eq $True) {  # The AutoRunObjects is a file
        LoadFromAFile $AutoRunObjects
      }
      else {
        Get-ObjectsManually $AutoRunObjects
      }
      try {
        $AutoSeqName=[io.path]::GetFileNameWithoutExtension($AutoRunSequence)
      } 
      catch {
        $AutoSeqName=""
      }
      Load-Sequence "AutoRun $AutoSeqName" $AutoRunSequence      
    }
    else {
      Import-Bundle $AutoRunBundle
      Check-AllObjects $True 
      Start-Sequence
    }
  }

  $ObjectsTabControl.SelectedItem.AllowDrop=$True
  $ObjectsTabControl.SelectedItem.Add_Drop( $GridFileDropped )

  if ($AddParams -ne 0) {
    $Script:TabObjectAdditionalParams[$TabLastIndex]=$AddParams
  }

  if ($TabObjectAdditionalParams[$TabLastIndex] -ne 0) {
    Add-GridColumn $ObjectsTabControl.SelectedItem $TabObjectAdditionalParams[$TabLastIndex]
    Add-ItemsAdditionalParams $TabLastIndex $TabObjectAdditionalParams[$TabLastIndex]
  }

}


$CreateRunspace = {

  param ($Object, $RunspaceScriptBlock)

  if ($Object.Transcript -eq $True) {  # A transcript has to be created: the task is modified to inject the Start-Transcript command
    $Transcript=(Join-Path $TranscriptsPath "$($Object.SequenceName)_$($Object.Objects)_$($Object.UniqueID)_$(Get-Date -Format "yyyyMMdd_HHmmss").transcript") -replace " ", "-"
    $ParamNotFound=$True  # Add the Transcript command after the 1st occurrence of Param
    $RunspaceScriptBlock=(($RunspaceScriptBlock.ToString()) -split "`n") | ForEach-Object { if (($_ -like "*param*") -and  $ParamNotFound) { $_ + "`r`n Start-Transcript $Transcript | out-null `r`n" ; $ParamNotFound=$False } else { $_ } }
    $Object.Transcript=$False
  }

  if ($SequenceSettings[$Object.SequenceId].Parameter.ObjectAsParam -eq $True) {
    if ($ObjectsNormalized -eq 1) { $ObjectName=$Object.Objects.Trim() } else { $ObjectName=$Object.Objects }
    $ObjectArg=New-Object -TypeName PSObject
    $ObjectArg | Add-Member -MemberType NoteProperty -Name Name -Value $ObjectName
    $ObjectArg | Add-Member -MemberType NoteProperty -Name SharedVariable -Value $Object.SharedVariable
    $ObjectArg | Add-Member -MemberType NoteProperty -Name LiveStatus -Value $LiveStatus
    $ObjectArg | Add-Member -MemberType NoteProperty -Name AddParams -Value $Object.AddParams
    $ObjectArg | Add-Member -MemberType NoteProperty -Name TaskHistory -Value $Object.TaskHistory

    # Create a Runspace for the Object with the code $RunspaceScriptBlock and its shared variable and Live Status, if they exist
    $Powershell=[PowerShell]::Create().AddScript($RunspaceScriptBlock).AddArgument($ObjectArg)
  }
  else {
   
    if ($SequenceSettings[$Object.SequenceId].Parameter.ObjectAdditionalParams -eq 0) {
      $ObjectArg=$Object.Objects
    }
    else {
      $ObjectArg=, $Object.Objects + $Object.AddParams
    }

    # Create a Runspace for the Object with the code $RunspaceScriptBlock and its shared variable and Live Status, if they exist
    if ($ObjectsNormalized -eq 1) {
      $Powershell=[PowerShell]::Create().AddScript($RunspaceScriptBlock).AddArgument($ObjectArg.Trim()).AddArgument($Object.SharedVariable).AddArgument($LiveStatus)
    }
    else {
      $Powershell=[PowerShell]::Create().AddScript($RunspaceScriptBlock).AddArgument($ObjectArg).AddArgument($Object.SharedVariable).AddArgument($LiveStatus)
    }
  }

  $Powershell.RunspacePool=$SequenceSettings[$Object.SequenceID].RunspacePool

  $Object.Runspace=New-Object -TypeName PSObject -Property @{
    Runspace=$PowerShell.BeginInvoke()
    PowerShell=$PowerShell
  }

}


function Create-AutoSavePoint {

  # Create an AutoSave point

  $TabsNotNull=$False
  foreach ($Tab in $ObjectsTabControl.Items) {  # Check if some of the tabs are empty
    if ($Tab.Name -eq "TabPlus") { continue }
    if (@($Tab.Content.ItemsSource).Count -ne 0) {  # Only the placeholder
      $TabsNotNull=$True
      break
    }
  }

  if ($TabsNotNull -eq $False) {  # All tabs are empty, no AutoSave point
    return
  }

  try {
    Get-ChildItem $AutoSaveFolder -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue  # Clean the last autosave
  }
  catch {}

  $AutoSaveVersion=Split-Path $AutoSaveFolder -Leaf

  $ToAdd=$AutoSaveVersion
  $TabPos=0
  foreach ($Tab in $ObjectsTabControl.Items) {  #  Loop in the tabs
    if ($Tab.Name -eq "TabPlus") { continue }
    if (@($Tab.Content.ItemsSource).Count -eq 0) { continue }  # The tab is empty and will be ignored
    $ToAdd=$ToAdd + ";" + $($Tab.Header -replace ";", ",")
    $TabPos++
    $TabExportName="AutoSave" + "{0:D2}" -f $TabPos
    [System.Management.Automation.PSSerializer]::Serialize($($Tab.Content.ItemsSource | Select-Object Objects, TaskResults, TaskResultsExport, State, SequenceName, Step, IsChecked, Color, CellFontFormated, CellFontFamily, CellFontColor, CellFontSize, CellFontStyle, CellFontWeight, Hidden, AddParams)) | Out-File $(Join-Path $AutoSaveFolder $TabExportName) -ErrorAction SilentlyContinue
  }

  Set-Content -Path "$AutoSaveFolder.autosave" -Value $ToAdd -Force  # Create the index  

}


function Create-CheckBoxInSequence($CheckBoxLabel, $StepLabel, $StepID, $Checked=$True, $Color="Black", $FontStyle="Normal", $Mandatory=$False, $SequencePath="") {  

  # Create a checkbox and its label in the Sequence Panel
    
  $CheckBox=New-Object System.Windows.Controls.CheckBox
  $CheckBox.Content=$CheckBoxLabel
  $CheckBox.Margin="7,12,0,0"
  $CheckBox.Foreground=$ColorPanelsForeground
  $CheckBox.IsChecked=$Checked
  $CheckBox.Tag="CB$StepId"
  $CheckBox.Background="Yellow"
  $CheckBox.IsHitTestVisible=!$Mandatory
  $CheckBox.FocusVisualStyle=$Null
  $SequenceStepsStackPanel.Children.Add($CheckBox)
  $Label=New-Object System.Windows.Controls.Label
  $Label.Content=$StepLabel.Replace("_", "__")
  $Label.Margin="5,0,0,0"
  $Label.Foreground=$Color
  $Label.FontStyle=$FontStyle
  $Label.Tag=$SequencePath
  $SequenceStepsStackPanel.Children.Add($Label)
  
}


function Create-LabelInSequence($SequenceLabel, $Color="Black", $FontStyle="Normal", $FontSize=10, $MarginUp=0, $PanelSize) {  

  # Create a label in the Sequence Panel
  
  if ($PanelSize -ne $Null) {
    if ((($PanelSize -as [int]) -is [int]) -eq $False) {
      $PanelSize=$Null
    }
    elseif ([int]$PanelSize -eq 0) { 
      return 
    }
    elseif ([int]$PanelSize -lt 200) {
      $PanelSize=200
    }
  }

  $Label=New-Object System.Windows.Controls.Label
  $Label.Content=$SequenceLabel.Replace("_", "__")
  $Label.Margin="5,$MarginUp,0,0"
  if ($Color -eq "Black") { $Color=$ColorPanelsForeground }
  $Label.Foreground=$Color
  $Label.FontStyle=$FontStyle
  $Label.FontSize=$FontSize
  if ($PanelSize -ne $Null) {
    $Label.HorizontalContentAlignment="Left"
    $Label.HorizontalAlignment="Left"
    $Label.Width=$PanelSize
    $Label.Content=($SequenceLabel.Replace("_", "__")).Replace("`r`n","")
  }
  $SequenceStepsStackPanel.Children.Add($Label)

}


function Display-Log {

  $DisplayLog=Read-OpenFileDialog "Hydra Log" (Split-Path $LogFilePath) "Hydra Log (Hydra.log)|Hydra.log|All Logs(*.log)|*.log|All files (*.*)|*.*"
    if ($DisplayLog -eq "") {  # No Sequences List selected
    return
  }

  if (!([string]::IsNullOrEmpty($NotepadPath))) {
    if (Test-Path $NotepadPath -PathType Leaf) {
      Start-Process $NotepadPath $DisplayLog
      return
    }
  }
  
  Start-Process "$env:WINDIR\system32\notepad.exe" $DisplayLog

}


function Display-Stats {

  $DisplayStats=Read-OpenFileDialog "Hydra Stats" (Split-Path $LogFilePath) "Hydra Statistics (*.log.stats)|*.log.stats|All files (*.*)|*.*"
    if ($DisplayStats -eq "") {  # No Sequences List selected
    return
  }

  Import-Csv $DisplayStats -Delimiter ";" | Out-GridView -Title "Hydra Statistics"

}


function Duplicate-Sequence($SeqFolder, $SeqLeafTag, $SeqLeafHeaderTag) {

  if ($SequencesTreeView.SelectedItem.Parent.Header.Tag -notlike "*Manually Loaded*") {

    if (@(Get-Content $SequencesListPath | Select-String -SimpleMatch $SeqLeafTag | Select-String -SimpleMatch $SeqLeafHeaderTag).Count -eq 0) {  # Matching not found for this sequence in the sequence list
      MessageBox "Duplicate Sequence" "Unable to find matches for $SeqLeafHeaderTag and $SeqLeafTag in the Sequences List" 2 1
      return
    }

    if (@(Get-Content $SequencesListPath | Select-String -SimpleMatch $SeqLeafTag | Select-String -SimpleMatch $SeqLeafHeaderTag).Count -gt 1) {  # Too many matches found for this sequence in the sequence list
      MessageBox "Duplicate Sequence" "Entries for '$SeqLeafHeaderTag' and '$SeqLeafTag' in the Sequences List are not unique." 2 1
      return
    }

  }
  
  $DuplicateName=Read-InputBoxDialog "Duplicate Sequence" "Enter the name of the folder duplicate:" "$(Split-Path $SeqFolder -Leaf)-Copy"
  if ($DuplicateName -eq "") {
    return
  }

  if ($DuplicateName -eq $(Split-Path $SeqFolder -Leaf).Trim()) {
    MessageBox "Duplicate Sequence" "The name of the new folder must be different." 2 1
    return
  }

  $DuplicateSeqName=Read-InputBoxDialog "Duplicate Sequence" "Enter the new name in the sequence tree:" "$SeqLeafHeaderTag-Copy"
  if ($DuplicateSeqName -eq "") {
    return
  }

  $DuplicateFolder=$(Join-Path $(Split-Path $SeqFolder) $DuplicateName)
  try {
    Copy-Item $SeqFolder $DuplicateFolder -Recurse -Force -ErrorAction Stop
  }
  catch {
    MessageBox "Duplicate Sequence" "Unable to copy $SeqFolder to $DuplicateFolder." 2 1
    return
  }

  if ($SequencesTreeView.SelectedItem.Parent.Header.Tag -like "*Manually Loaded*") {  # Generate an entry in Manually Loaded
    Get-SequenceFileManual $(Join-Path $DuplicateFolder $(Split-Path $SeqLeafTag -Leaf)) $DuplicateSeqName
  }
  else {  # Generate an entry in the tree and the sequences list

    $LineToDuplicate=(Get-Content $SequencesListPath | Select-String -SimpleMatch $SeqLeafTag | select-string -SimpleMatch $SeqLeafHeaderTag).LineNumber
    $LineNr=1
    $NewContent=@()
    foreach($line in Get-Content $SequencesListPath) {
      $NewContent+=$line
      if ($LineNr -eq $LineToDuplicate) {
        $LineSplit=$line -split(";")
        $LineSplit[0]=$DuplicateSeqName
        $LineSplit[1]=Join-Path $DuplicateFolder $(Split-Path $SeqLeafTag -Leaf)
        $NewContent+=$LineSplit -join(";")
      }
      $LineNr++
    }

    try {
      Set-Content -Value $($NewContent -join("`r`n")) -Path $SequencesListPath -Force -ErrorAction Stop
    }
    catch {
      MessageBox "Duplicate Sequence" "Unable to copy the new content in $SequencesListPath." 2 1
      return
    }

  }

  SequenceTreeViewInitialLoad

}


function Edit-File($file) {

  if (!([string]::IsNullOrEmpty($NotepadPath))) {
    if (Test-Path $NotepadPath -PathType Leaf) {
      Start-Process $NotepadPath $file
      return
    }
  }
  
  Start-Process "$env:WINDIR\system32\notepad.exe" $file

}


function Edit-TaskResults($TR) {

  try {
    $NewTempFile=New-TemporaryFile -ErrorAction Stop
    Set-Content -Value $TR -Path $NewTempFile.FullName -ErrorAction Stop
  }
  catch {
    return
  }
  
  if (!([string]::IsNullOrEmpty($NotepadPath))) {
    if (Test-Path $NotepadPath -PathType Leaf) {
      Start-Process $NotepadPath $NewTempFile
      return
    }
  }
  
  Start-Process "$env:WINDIR\system32\notepad.exe" $NewTempFile

}


function Export-Bundle($Bundle) {

  # Export a Bundle

  $SaveFileDialog=New-Object System.Windows.Forms.SaveFileDialog
  $SaveFileDialog.InitialDirectory=$LastDirBundles
  $SaveFileDialog.Filter="Hydra Bundle (*.bundle)|*.bundle|All files|*.*" 
  $SaveFileDialog.ShowDialog() |  Out-Null
  if ($SaveFileDialog.FileName -eq "") { return }
  
  $Script:LastDirBundles=Split-Path $SaveFileDialog.FileName

  $ObjectsOfBundle=@()
  foreach ($dgis in $DataGridItemSource) {  # Get the name of all Bundles in use
    filter myFilter { if (($_.Bundle -eq $True) -and ($_.BundleName -eq $Bundle)) { $_ } }
    $ObjectsOfBundle+=$dgis | myFilter 
  }

  $SequenceID=$ObjectsOfBundle[0].SequenceID
  filter myFilter { if ($_.Index -eq $SequenceID) { $_ } }
  $SequenceOfBundle=$SequenceSettings[1..$LastSequenceIndex] | myFilter
  $ToExport=New-Object PSObject
  $ToExport | Add-Member -MemberType NoteProperty -Name BundleName -Value $Bundle
  $ToExport | Add-Member -MemberType NoteProperty -Name BundleVersion -Value 2
  $ToExport | Add-Member -MemberType NoteProperty -Name Sequence -Value $SequenceOfBundle
  $ToExport | Add-Member -MemberType NoteProperty -Name Objects -Value ($ObjectsOfBundle | Select-Object Objects, AddParams)
  
  [System.Management.Automation.PSSerializer]::Serialize($ToExport) | Out-File $($SaveFileDialog.FileName)

}


function Export-CreateCSV($Object=$True, $TaskResult=$True, $State=$True, $SequenceName=$False, $Header=$True, $Hidden=$False, $OnlySelection=$False, $OpenNotepad=$True, $AddTimeStamp=$True, $PathToSave=$CSVTempPath, $UseDelimiter=$CSVDelimiter) {

  # Export the grid in CSV format

  $DV=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)
  if ($DV.Groups -ne $Null) {  # Groups have been found: move to the Export function with Groups
    Export-CreateCSV_WithGroup -Object $Object -TaskResult $TaskResult -State $State -SequenceName $SequenceName -Header $Header -Hidden $Hidden -OnlySelection $OnlySelection -UseDelimiter $UseDelimiter
    return
  }

  # Generate a CSV based on the parameters

  $OFS="`r`n"
  $param=@()
  if ($Object -eq $True) { 
    $param+="Objects"
    if ($TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag] -gt 0 ) {
      for($i=0; $i -lt $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]; $i++) {
        $param+=@{ l="Param$($i+1)" ; exp=[scriptblock]::create("(`$`_.AddParams)[$i]") } 
      }
    }
  }
  if ($TaskResult -eq $True) { $param+=@{l="Task Results"; e={ $_.TaskResultsExport }} }
  if ($State -eq $True) { $param+="State" }
  if ($SequenceName -eq $True) { $param+=@{l="Sequence Name"; e={$_.SequenceName}} }
  if ($OnlySelection -eq $True) {
    $Selected=$ObjectsTabControl.SelectedItem.Content.SelectedCells | Select-Object -ExpandProperty Item
    filter myFilter { if (($_ -in $Selected) -and ($_.ToString() -ne "{NewItemPlaceholder}")) { $_ } }
    $ItemsToSelect=$DV | myFilter
  }
  else {
    filter myFilter { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
    $ItemsToSelect=$DV | myFilter
  }

  $SeqUsed=foreach ($dgis in $ObjectsTabControl.SelectedItem.Content.ItemsSource) { if (![string]::IsNullOrEmpty($dgis)) { $dgis.SequenceID } }
  $SeqUsed=@($SeqUsed | Where-Object { $_ -ne "0" } | Select-Object -Unique)
  if ($SeqUsed.count -eq 0) {  # No sequence started
    $nbOfHeaders=0
  }
  else {
    $HeadersUsed=@(($SequenceSettings[$SeqUsed]).Parameter.Customheader | Select-Object -Unique)
    if ($HeadersUsed) {
      $nbOfHeaders=$HeadersUsed.Count
    }
    else {
      $nbOfHeaders=0
    }
    $nbOfCustomHeaders=@(($SequenceSettings[$SeqUsed]).Parameter.Customheader | Where-Object { ![string]::IsNullOrEmpty($_) } | Select-Object -Unique).Count
  }
  $UseCustomHeader=$False
  if ($nbOfHeaders -gt 1) {  # Different types of Headers detected
    MessageBox "Export" "Several sequences with different Headers detected:`r`nThe custom Headers will be ignored." 2 1
  }
  if ($nbOfHeaders -eq 1 -and $nbOfCustomHeaders -eq 1) {  # One custom header only
    $UseCustomHeader=$True
  }

  if ($UseCustomHeader -eq $True) {
    $CSV=($ItemsToSelect | Select-Object $param) | ConvertTo-CSV -NoTypeInformation -Delimiter $UseDelimiter | Select-Object -skip 1 | ForEach-Object { $_ -replace ('"'+$UseDelimiter+'"'), $UseDelimiter } | ForEach-Object { $_ -replace "^`"",''} | ForEach-Object { $_ -replace "`"$",''}
    $CSV="Objects,$($HeadersUsed[0])`r`n" + @($CSV -join "`r`n")
  }
  else {
    $CSV=($ItemsToSelect | Select-Object $param) | ConvertTo-CSV -NoTypeInformation -Delimiter $UseDelimiter | ForEach-Object { $_ -replace ('"'+$UseDelimiter+'"'), $UseDelimiter } | ForEach-Object { $_ -replace "^`"",''} | ForEach-Object { $_ -replace "`"$",''}
  }

  if ($AddTimeStamp -eq $True) {  
    $Now=(Get-Date).ToString("yyyyMMddHHmmss") 
    $NewCSVName=(New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).BaseName + "_" + $Now + (New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).Extension
    $NewCSVPath=Join-Path -Path (Split-Path $PathToSave -Parent) -ChildPath $NewCSVName
  }
  else {
    $NewCSVPath=$PathToSave
  }
  try {
    $CSV | Out-File $NewCSVPath -ErrorAction Stop
  }
  catch {
    MessageBox "Export" "Unable to create the Export file $NewCSVPath" 2 1
    return
  }

  if ($OpenNotepad -eq $True) { Start-Process 'C:\windows\system32\notepad.exe' -ArgumentList $NewCSVPath }
  
}


function Export-CreateCSV_WithGroup($Object=$True, $TaskResult=$True, $State=$False, $SequenceName=$False, $Header=$True, $Hidden=$False, $OnlySelection=$False, $UseDelimiter=$CSVDelimiter) {

  # Export the grid in CSV format, with groups defined

  $DV=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)
  $OFS="`r`n"

  $CSV=""
  foreach ($Group in $DV.Groups) {  # Loop in all groups and generate a CSV based on the parameters
    if ($Group.ToString() -eq "{NewItemPlaceholder}") { continue }
    $param=@()
    if ($Object -eq $True) { 
      $param+="Objects"
      if ($TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag] -gt 0 ) {
        for($i=0; $i -lt $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]; $i++) {
          $param+=@{ l="Param$($i+1)" ; exp=[scriptblock]::create("(`$`_.AddParams)[$i]") } 
        }
      }
    }
    if ($TaskResult -eq $True) { $param+=@{l="Task Results"; e={$_.TaskResultsExport}} }
    if ($State -eq $True) { $param+="State" }
    if ($SequenceName -eq $True) { $param+=@{l="Sequence Name"; e={$_.SequenceName}} }
    if ($OnlySelection -eq $True) {
      $Selected=$ObjectsTabControl.SelectedItem.Content.SelectedCells | Select-Object -ExpandProperty Item
      filter myFilter { if ($_ -in $Selected) { $_ } }
      $GroupItemsToSelect=$($Group.Items) | myFilter
    }
    else {
      $GroupItemsToSelect=$($Group.Items)
    }
    $CSV+="$($Group.Name)`r`n"
    $CSV+=($GroupItemsToSelect | Select-Object $param) | ConvertTo-CSV -NoTypeInformation -Delimiter $UseDelimiter | ForEach-Object { $_ -replace ('"'+$UseDelimiter+'"'), $UseDelimiter } | ForEach-Object { $_ -replace "^`"",''} | ForEach-Object { $_ -replace "`"$",''}
    $CSV+="`r`n`r`n"
  }

  $Now=(Get-Date).ToString("yyyyMMddHHmmss")
  $NewCSVName=(New-Object System.IO.FileInfo(Split-Path $CSVTempPath -Leaf)).BaseName + "_" + $Now + (New-Object System.IO.FileInfo(Split-Path $CSVTempPath -Leaf)).Extension
  $NewCSVPath=Join-Path -Path (Split-Path $CSVTempPath -Parent) -ChildPath $NewCSVName
  $CSV | Out-File $NewCSVPath
  Start-Process 'C:\windows\system32\notepad.exe' -ArgumentList $NewCSVPath

}


function Export-CreateHTML($Object=$True, $TaskResult=$True, $State=$False, $SequenceName=$False, $Header=$True, $Hidden=$False, $Color=$True, $OnlySelection=$False, $WithStyle=$True) {

  # Create an HTML files based on the All or Selected objects, the columns to display as well as color and style

  $HTMLBody=""

  if ($Hidden -eq $False) {
    $DV=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)
  }
  else {
    $DV=$ObjectsTabControl.SelectedItem.Content.ItemsSource
  }

  $param=@()  # Create a param object where its properties will be used for the HTML export
  if ($Color -eq $True) {  # Fake the color to reuse it later with string replacements
    $param+=@{l="Color"; 
              e={
                  if (($($_.Color).Length -eq 9) -and ($($_.Color).SubString(0,3) -eq "#FF")) {
                    "%%%$($($_.Color) -replace "#FF", "#")%%%"
                  }
                  else {
                    "%%%$($_.Color)%%%"
                  }
                }
             }
  }
  if ($Object -eq $True) { 
    $param+="Objects"
    if ($TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag] -gt 0 ) {
      for($i=0; $i -lt $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]; $i++) {
        $param+=@{ l="Param$($i+1)" ; exp=[scriptblock]::create("(`$`_.AddParams)[$i]") } 
      }
    }
  }
  if ($TaskResult -eq $True) { $param+=@{l="Task Results"; e={$_.TaskResultsExport}} }
  if ($State -eq $True) { $param+="State" }
  if ($SequenceName -eq $True) { $param+=@{l="Sequence Name"; e={$_.SequenceName}} }
  if ($OnlySelection -eq $True) {  # Use only selected or all objects
    $Selected=$ObjectsTabControl.SelectedItem.Content.SelectedCells | Select-Object -ExpandProperty Item
    filter myFilter { if (($_ -in $Selected) -and ($_.ToString() -ne "{NewItemPlaceholder}")) { $_ } }
    $ItemsToSelect=$DV | myFilter
  }
  else {
    filter myFilter { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
    $ItemsToSelect=$DV | myFilter
  }

  $HTMLBody=($ItemsToSelect | Select-Object $param | ConvertTo-Html -Fragment) -replace "`n", "%%NEWLINE%%"

  if ($Color -eq $True) {  # String manipulation to get the color at the correct place in the HTML code
    $HTMLBody=$HTMLBody -replace "><td>%%%", " bgcolor="
    $HTMLBody=$HTMLBody -replace "%%%</td>", ">"
    $HTMLBody=$HTMLBody -replace "<th>Color</th>", ""
  }

  if ($WithStyle -eq $True) {  # Style to use for a visual rendering
    $HTMLStyle="<style>" 
    $HTMLStyle+=$HTMLcss
    $HTMLStyle+="</style>" 
  }
  else {
    if ($ExportCellsAsText) {  # Convert the cells in pure text
      $HTMLStyle="<style> td { mso-number-format:\@ }? </style>"
    }
    else {
      $HTMLStyle=""
    }
  }

  if ($Header -eq $False) {  # The Header shouldn't be displayed
    $HTMLBody=$HTMLBody -replace "<tr><th>.*?</th></tr>", ""  # Suppress the Automatic Header
  }

  return $HTMLStyle, ($HTMLBody | Out-String)

}


function Export-CreateHTML_WithGroup($Object=$True, $TaskResult=$True, $State=$False, $SequenceName=$False, $Header=$True, $Hidden=$False, $Color=$True, $OnlySelection=$False, $WithStyle=$True, $UseCustomHeader=$True) {

  # Create an HTML files based on the All or Selected objects, the columns to display as well as color and style

  $HTMLBody=""

  if ($Hidden -eq $False) {
    $DV=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)
  }
  else {
    $DV=$ObjectsTabControl.SelectedItem.Content.ItemsSource
  }

  # Loop in each group found and generate the HTML part for all of them

  foreach ($Group in $DV.Groups) {
    if ($Group.ToString() -eq "{NewItemPlaceholder}") { continue }
    $param=@()  # Create a param object where its properties will be used for the HTML export
    if ($Color -eq $True) {  # Fake the color to reuse it later with string replacements
      $param+=@{l="Color"; 
                e={
                  if (($($_.Color).Length -eq 9) -and ($($_.Color).SubString(0,3) -eq "#FF")) {
                    "%%%$($($_.Color) -replace "#FF", "#")%%%"
                  }
                  else {
                    "%%%$($_.Color)%%%"
                  }
                }
             }
    }
    if ($Object -eq $True) { 
      $param+="Objects"
      if ($TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag] -gt 0 ) {
        for($i=0; $i -lt $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]; $i++) {
          $param+=@{ l="Param$($i+1)" ; exp=[scriptblock]::create("(`$`_.AddParams)[$i]") } 
        }
      }
    }

    if ($TaskResult -eq $True) {
      filter myFilter { if ($_.Name -eq $Group.Name) { $_ } }
      if (($UseCustomHeader -eq $True) -and (($SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1).Parameter.CustomHeader -ne "")) {
        try {
          $CustomHeaderString=($SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1).Parameter.CustomHeader
          $CustomHeaderDelimiter=($SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1).Parameter.CustomHeaderDelimiter
          $CustomHeader=$CustomHeaderString -split ","
          for ($i=0; $i -lt @($CustomHeader).Count; $i++) {
            $SCTaskResults=[scriptblock]::Create('($_.TaskResultsExport -split("' + $CustomHeaderDelimiter +'"))'+"[$i]")
            $param+= @{l=$CustomHeader[$i]; e=$SCTaskResults } 
          }
        }
        catch {
          $param+=@{l="Task Results"; e={$_.TaskResultsExport}}
        }
      }
      else {  # No custom headers
        if ($TaskResult -eq $True) { $param+=@{l="Task Results"; e={$_.TaskResultsExport}} }
      }
    }

    if ($State -eq $True) { $param+="State" }
    if ($SequenceName -eq $True) { $param+=@{l="Sequence Name"; e={$_.SequenceName}} }
    if ($OnlySelection -eq $True) {  # Use only selected or all objects
      $Selected=$ObjectsTabControl.SelectedItem.Content.SelectedCells | Select-Object -ExpandProperty Item
      filter myFilter { if ($_ -in $Selected) { $_ } }
      $GroupItemsToSelect=$($Group.Items) | myFilter
    }
    else {
      $GroupItemsToSelect=$($Group.Items)
    }
    $HTMLBody+="<H4><I>$($Group.Name)</I></H4>" + ($(($GroupItemsToSelect | Select-Object $param | ConvertTo-Html -Fragment) -replace "`n", "%%NEWLINE%%") | Out-String)
  }

  if ($Color -eq $True) {  # String manipulation to get the color at the correct place in the HTML code
    $HTMLBody=$HTMLBody -replace "><td>%%%", " bgcolor="
    $HTMLBody=$HTMLBody -replace "%%%</td>", ">"
    $HTMLBody=$HTMLBody -replace "<th>Color</th>", ""
  }

  if ($WithStyle -eq $True) {  # Style to use for a visual rendering
    $HTMLStyle=@"
<style>
$HTMLcss
</style>
"@
  }
  else {
    if ($ExportCellsAsText) {  # Convert the cells in pure text
      $HTMLStyle="<style> td { mso-number-format:\@ }? </style>"
    }
    else {
      $HTMLStyle=""
    }
  }

  if ($Header -eq $False) {  # The Header shouldn't be displayed
    $HTMLBody=$HTMLBody -replace "<tr><th>.*?</th></tr>", ""  # Suppress the Automatic Header
  }

  return $HTMLStyle, ($HTMLBody | Out-String)

}


function Export-Snapshot($AllTabs=$False) {

  # Make a snaphost of tabs in a file 

  if ([string]::IsNullOrEmpty($SnapshotsPath)) {
    MessageBox "Snapshot" "The Snapshot folder is not set.`r`nPlease set it in the Settings." 3 1
    return
  }

  if (!(Test-Path $SnapshotsPath)) {
    MessageBox "Snapshot" "The Snapshot folder is not reachable or not correctly set.`r`nPlease set it in the Settings" 3 1
    return
  }

  if ($AllTabs -eq $True) {  # Export all tabs
    foreach ($Tab in $ObjectsTabControl.Items) {  # Check if some of the tabs are empty
      if ($Tab.Name -eq "TabPlus") { continue }
      if (@($Tab.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
        MessageBox "Snapshot" "A Snapshot cannot be created because at least one Tab is empty ($($Tab.Header))." 3 1
        return
      }
    }
  }
  else {  # Check if the current tab is empty
    if (@($ObjectsTabControl.SelectedItem.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
      MessageBox "Snapshot" "A Snapshot cannot be created because this Tab is empty." 3 1
      return
    }
  }

  $SnapshotName=Read-InputBoxDialog "Snapshot" "Enter the name of the Snapshot:" ""
  if ($SnapshotName -eq "") { return }
  $SnapshotFullPath=Join-Path $SnapshotsPath $($SnapshotName + ".snapshot")
  if (Test-Path $SnapshotFullPath) {  # Check if a snapshot with this name is already present
    MessageBox "Snapshot" "A Snapshot ""$SnapshotName"" is already existing." 3 1 
    return
  }
  else {  # Create a new snapshot
    try {
      New-Item -Path $SnapshotFullPath -ItemType File -Force -ErrorAction Stop
    }
    catch {
      MessageBox "Snapshot" "Unable to create $SnapshotFullPath" 3 1 
      return
    }
    Add-Content -Path $SnapshotFullPath -Value "# Hydra Snapshots"
  }

  $SnapshotSubFolder=$(Join-Path $SnapshotsPath $SnapshotName)
  if (!(Test-Path $SnapshotSubFolder)) {  # No subfolder for the snapshot yet
    try {
      New-Item -Path $SnapshotSubFolder -ItemType Directory -Force -ErrorAction Stop
    }
    catch {
      MessageBox "Snapshot" "Unable to create $SnapshotSubFolder" 3 1 
      return
    }
  }
  
  $Now=Get-Date -Format "yyyyMMddHHmmss"
  $ToAdd=$Now.ToString()
  $TabPos=0
  
  if ($AllTabs -eq $True) {  # Export all tabs
    foreach ($Tab in $ObjectsTabControl.Items) {  #  Loop in the tabs
      if ($Tab.Name -eq "TabPlus") { continue }
      $ToAdd=$ToAdd + ";" + $(($Tab.Header -replace ";", ",") -replace '\[.*\]', '')
      $TabPos++
      $TabExportName=$Now.ToString() + "{0:D2}" -f $TabPos
      [System.Management.Automation.PSSerializer]::Serialize($($Tab.Content.ItemsSource | Select-Object Objects, TaskResults, TaskResultsExport, State, SequenceName, Step, IsChecked, Color, CellFontFormated, CellFontFamily, CellFontColor, CellFontSize, CellFontStyle, CellFontWeight, Hidden, AddParams)) | Out-File $(Join-Path $SnapshotSubFolder $TabExportName)
    }
  }
  else {  # Export current tab only
    $ToAdd=$ToAdd + ";" + $(($ObjectsTabControl.SelectedItem.Header -replace ";", ",") -replace '\[.*\]', '')
    $TabExportName=$Now.ToString() + "01"
    [System.Management.Automation.PSSerializer]::Serialize($($ObjectsTabControl.SelectedItem.Content.ItemsSource | Select-Object Objects, TaskResults, TaskResultsExport, State, SequenceName, Step, IsChecked, Color, CellFontFormated, CellFontFamily, CellFontColor, CellFontSize, CellFontStyle, CellFontWeight, Hidden, AddParams)) | Out-File $(Join-Path $SnapshotSubFolder $TabExportName)
  }
  Add-Content -Path $SnapshotFullPath -Value $ToAdd  # Create the index

}


function Export-SnapshotUpdate($SnapshotToUpdate, $AllTabs=$False) {

  # Update a snaphost of tabs in a file 

  if ($AllTabs -eq $True) {  # Export all tabs
    foreach ($Tab in $ObjectsTabControl.Items) {  # Check if some of the tabs are empty
      if ($Tab.Name -eq "TabPlus") { continue }
      if (@($Tab.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
        MessageBox "Snapshot" "A Snapshot cannot be created because at least one Tab is empty ($($Tab.Header))." 3 1 
        return
      }
    }
  }
  else {  # Check if the current tab is empty
    if (@($ObjectsTabControl.SelectedItem.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
      MessageBox "Snapshot" "A Snapshot cannot be created because this Tab is empty." 3 1  
      return
    }
  }

  $Now=Get-Date -Format "yyyyMMddHHmmss"
  $ToAdd=$Now.ToString()
  $TabPos=0
  $SnapshotSubFolder=$(Join-Path $SnapshotsPath $([io.path]::GetFileNameWithoutExtension($SnapshotToUpdate)))

  if ($AllTabs -eq $True) {  # Export all tabs
    foreach ($Tab in $ObjectsTabControl.Items) {  #  Loop in the tabs
      if ($Tab.Name -eq "TabPlus") { continue }
      $ToAdd=$ToAdd + ";" + $(($Tab.Header -replace ";", ",") -replace '\[.*\]', '')
      $TabPos++
      $TabExportName=$Now.ToString() + "{0:D2}" -f $TabPos
      [System.Management.Automation.PSSerializer]::Serialize($($Tab.Content.ItemsSource | Select-Object Objects, TaskResults, TaskResultsExport, State, SequenceName, Step, IsChecked, Color, CellFontFormated, CellFontFamily, CellFontColor, CellFontSize, CellFontStyle, CellFontWeight, Hidden, AddParams)) | Out-File $(Join-Path $SnapshotSubFolder $TabExportName)
    }
  }
  else {  # Export current tab only
    $ToAdd=$ToAdd + ";" + $(($ObjectsTabControl.SelectedItem.Header -replace ";", ",") -replace '\[.*\]', '')
    $TabExportName=$Now.ToString() + "01"
    [System.Management.Automation.PSSerializer]::Serialize($($ObjectsTabControl.SelectedItem.Content.ItemsSource | Select-Object Objects, TaskResults, TaskResultsExport, State, SequenceName, Step, IsChecked, Color, CellFontFormated, CellFontFamily, CellFontColor, CellFontSize, CellFontStyle, CellFontWeight, Hidden, AddParams)) | Out-File $(Join-Path $SnapshotSubFolder $TabExportName)
  }
  
  try {
    Add-Content -Path $SnapshotToUpdate -Value $ToAdd -ErrorAction Stop # Create the index
  }
  catch {
    MessageBox "Snapshot" "Unable to create a new snapshot in $($SnapshotToUpdate)" 3 1 
    return
  }

}


function Export-Tab($All=$False) {

  # Export the cuurent or all Tabs in a file

  if ($All -eq $True) {  # Export all tabs
    foreach ($Tab in $ObjectsTabControl.Items) {
      if ($Tab.Name -eq "TabPlus") { continue }
      if (@($Tab.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
        MessageBox "Tab Export" "The Tabs cannot be saved because at least one is empty ($($Tab.Header))" 3 1 
        return
      }
    }
    $SaveFileDialog=New-Object System.Windows.Forms.SaveFileDialog
    $SaveFileDialog.InitialDirectory=$LastDirTabs
    $SaveFileDialog.Filter="Hydra Tabs (*.tabs)|*.tabs|All files|*.*" 
    $SaveFileDialog.ShowDialog() |  Out-Null
    if ($SaveFileDialog.FileName -eq "") { return }
    $Script:LastDirTabs=Split-Path $SaveFileDialog.FileName
    $TabXML=@()

    foreach ($Tab in $ObjectsTabControl.Items) {
      if ($Tab.Name -eq "TabPlus") { continue } 
      $TabText=$Tab.Header -replace '\[[^\)]+\]'  # Remove [...] in case of a snapshot name
      if ($Tab.Background.GetType().Name -eq "SolidColorBrush") { 
        $TabColor=$Tab.Background.ToString()
      }
      else {
        $TabColor="Default"
      }
      $Objects=$($Tab.Content.ItemsSource | Select-Object Objects, AddParams)
      $TabXML+=[PSCustomObject]@{Header="Hydra Tabs" ; TabColor=$Tabcolor ; TabText=$TabText ; Objects=$Objects} 

    }

    Set-Content -Path $SaveFileDialog.FileName -Value $([System.Management.Automation.PSSerializer]::Serialize($TabXML))

  }
  else {  # Only the current tab
    if (@($ObjectsTabControl.SelectedItem.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
      MessageBox "Tab Export" "The Tab cannot be saved because it is empty." 3 1
      return
    }
    $SaveFileDialog=New-Object System.Windows.Forms.SaveFileDialog
    $SaveFileDialog.InitialDirectory=$LastDirTabs
    $SaveFileDialog.Filter="Hydra Tabs (*.tabs)|*.tabs|All files|*.*" 
    $SaveFileDialog.ShowDialog() |  Out-Null
    if ($SaveFileDialog.FileName -eq "") { return }
    $Script:LastDirTabs=Split-Path $SaveFileDialog.FileName

    $TabText=$ObjectsTabControl.SelectedItem.Header -replace '\[[^\)]+\]'
    if ($ObjectsTabControl.SelectedItem.Background.GetType().Name -eq "SolidColorBrush") { 
      $TabColor=$ObjectsTabControl.SelectedItem.Background.ToString()
    }
    else {
      $TabColor="Default"
    }

    $Objects=$($ObjectsTabControl.SelectedItem.Content.ItemsSource | Select-Object Objects, AddParams)
    $TabXML=[PSCustomObject]@{Header="Hydra Tabs" ; TabColor=$Tabcolor ; TabText=$TabText ; Objects=$Objects} 
    Set-Content -Path $SaveFileDialog.FileName -Value $([System.Management.Automation.PSSerializer]::Serialize($TabXML))
  }

}


function Export-ToChart { 

  if ($RB_ExportChartRef1.IsChecked -eq $True) { $Title="Hydra Export - By State" ; $Reference="State" }
  if ($RB_ExportChartRef2.IsChecked -eq $True) { $Title="Hydra Export - By Task Results" ; $Reference="TaskResults" }
  if ($RB_ExportChartRef3.IsChecked -eq $True) { $Title="Hydra Export - By Color" ; $Reference="Color" }

  if ($cb_ExportChartType.SelectedItem.Content -eq "Columns") {
    $Type="Column"
  }
  else {
    if ($CB_ExportPie3.IsChecked -eq $True) {
      $Type="Doughnut"
    }
    else {
      $Type="Pie"
    }
  }

  $ShowValues=$true
  $UseHydraColors=$CB_ExportColors.IsChecked -eq $True

  filter Myfilter { if ( $_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
  $view=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource) | Myfilter
  $ViewCount=@($view).count
  $Params=@()
  
  if ($UseHydraColors -eq $True) {
    $view | Select-Object Objects, Color, TaskResults, State | Group-Object $Reference | ForEach-Object { 
      $GroupName=$_.Name
      $_.Group | Group-Object Color | ForEach-Object {
        $o=[pscustomobject]@{
          Header=$GroupName
          Value=$_.Count
          Percent="{0:N2}" -f ($_.Count *100 / $viewcount)
          Color=$_.Name
        }
        $Params+=$o
      }
    }
  }
  else {
    $view | Select-Object Objects, Color, TaskResults, State | Group-Object $Reference | ForEach-Object { 
      $GroupName=$_.Name
      $o=[pscustomobject]@{
        Header=$GroupName
        Value=$_.Count
        Percent="{0:N2}" -f ($_.Count *100 / $viewcount)
      }
      $Params+=$o
    }
  }
 
  Add-Type -AssemblyName System.Windows.Forms.DataVisualization 
  $chart=New-Object System.Windows.Forms.DataVisualization.Charting.Chart 
  $chart.Width=[int]($CB_ExportChartWidth.Text)*1
  $chart.Height=[int]($CB_ExportChartHeight.Text)*1
  $chart.Top=0 
  $chart.Left=0
  $chart.BackColor="#DDDDDD"
    
  $chartarea=New-Object System.Windows.Forms.DataVisualization.Charting.ChartArea 
  $chartarea.BackColor="#DDDDDD"
  $chartarea.BackSecondaryColor="#DDDDDD" 
  $chartarea.BackGradientStyle="DiagonalRight" 
  $chartArea.Area3DStyle.Enable3D=$CB_ExportChart3D.IsChecked -eq $True
  $chartArea.Area3DStyle.Inclination=45
  $chartarea.AxisX.MajorGrid.Enabled=$False
  $chartarea.AxisY.MajorGrid.Enabled=$False
  $chart.ChartAreas.Add($chartarea) 
   
  $legend=New-Object System.Windows.Forms.DataVisualization.Charting.Legend
  $legend.Alignment="Center"
  $legend.Title="Total of items: $ViewCount"
  if ($CB_ExportChartLegend.IsChecked -eq $True) { $chart.Legends.Add($legend) }
      
  $chart.Titles.Add($Title) | Out-Null 
  $chart.Titles[0].Font=New-Object System.Drawing.Font("Arial", 18) 
  $chart.Titles[0].Alignment="TopCenter"
    
  [void]$Chart.Series.Add(" ")
  $Params | ForEach-Object {
  $datapoint=New-Object System.Windows.Forms.DataVisualization.Charting.DataPoint(0, $_.Value)
    $datapoint.AxisLabel="$($_.Header): $($_.Value)" + " (" + $($_.Percent) + "%)"
    if ($UseHydraColors -eq $True) { $datapoint.Color=$_.Color }
    if ($cb_ExportChartPieExplode.SelectedItem.Content -eq "All Values") { $datapoint["Exploded"]=$true }
    $datapoint.ToolTip="$($_.Header): $($_.Value)" + " (" + $($_.Percent) + "%)"
    $Chart.Series[0].Points.Add($datapoint)
  }

  $chart.Series[0].ChartType=[System.Windows.Forms.DataVisualization.Charting.SeriesChartType]::$Type 
  if ($Type -eq "Column") {
    $chart.Series[0].IsValueShownAsLabel=$CB_ExportChart1.IsChecked -eq $True
  }
  else {
    $chart.Series[0].IsValueShownAsLabel=$CB_ExportChart1.IsChecked -eq $False
  }
  $chart.Series[0]["DrawingStyle"]=$cb_ExportChartBarType.SelectedItem.Content
  if ($CB_ExportPie1.IsChecked -eq $True) { $chart.Series[0]["PieLabelStyle"]="Outside" }
  if ($CB_ExportPie2.IsChecked -eq $true) { $chart.Series[0]["PieDrawingStyle"]="Concave" } else { $chart.Series[0]["PieDrawingStyle"]="SoftEdge" } 
  $chart.Series[0]["PieLineColor"]="Black" 
  $chart.Series[0]["VisibleAllPies"]=$true
  $chart.Series[0]["DoughnutRadius"]="50"
  if ($cb_ExportChartPieExplode.SelectedItem.Content -eq "The Max Value") { ($Chart.Series[0].Points.FindMaxByValue())["Exploded"]=$True }
    
  $chart.Anchor=[System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right -bor [System.Windows.Forms.AnchorStyles]::Top 
  $formChart=New-Object Windows.Forms.Form 
  $formChart.Width=[int]($CB_ExportChartWidth.Text)*1
  $formChart.Height=[int]($CB_ExportChartHeight.Text)*1 + 40
  $formChart.StartPosition=[System.Windows.Forms.FormStartPosition]::CenterScreen
  $formChart.BackColor="#DDDDDD"
  $formChart.Controls.Add($chart) 
  $formChart.ShowDialog() | Out-Null  

} 


function Export-ToExcel($NameWithDate=$True, $PathToSave=$XLSXTempPath) {

  # Export and display the grid information in Excel

  $HTMLExport=Export-ToHTML $False $False $False # Use the Exporet-ToHTML function to generate a temporary raw HTML file: create it without any style ($false) and don't open it ($false) 
  if ($HTMLExport -eq $False) {  # The HTML export has been cancelled
    return
  }

  $Cc=[threading.thread]::CurrentThread.CurrentCulture  # Save the current regional settings
  [threading.thread]::CurrentThread.CurrentCulture='en-US'  # Set the Culture to en-US to avoid some bugs
  try {
    $Excel=New-Object -ComObject Excel.Application  # Open Excel and display the temporary HTML created file
  }
  catch {
    if ($AutoRun -eq $True) {
      MessageBox "Export" "AutoRunExport Error: Unable to open Excel"
    }
    else {
      MessageBox "Export" "Unable to open Excel"
    }
    return
  }
  $NewXLSXPath=""
  $Excel.Visible=($AutoRun -eq $False)
  $WorkBook=$Excel.Workbooks.Open($HTMLTempPath)
  $Excel.Application.ErrorCheckingOptions.BackgroundChecking=($ExportCellsAsText -eq $False)
  $Excel.Windows.Item(1).Displaygridlines=$True
  $Excel.Worksheets.Item(1).Name=$ObjectsTabControl.SelectedItem.Header
  $Excel.Application.DisplayAlerts=$False
  $Excel.Worksheets.Item(1).Columns.Replace("%%NEWLINE%%","`r`n")
  $Excel.Application.DisplayAlerts=$True

  if ($NameWithDate -eq $True) {  
    $Now=(Get-Date).ToString("yyyyMMddHHmmss")
    $NewXLSXName=(New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).BaseName + "_" + $Now + (New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).Extension
    try {
      $NewXLSXPath=Join-Path -path (Split-Path $PathToSave -Parent) -ChildPath $NewXLSXName -ErrorAction Stop
    }
    catch {}
  }
  else {
    $NewXLSXPath=$PathToSave
  }
 
  try {
    $Workbook.SaveAs($NewXLSXPath, 51)  # Save the newly created file
  }
  catch {
    if ($AutoRun -eq $True) {
      MessageBox "Export" "AutoRunExport Error: Unable to create the Export file $NewXLSXPath"
    }
    else {
      MessageBox "Export" "Unable to create the Export file $NewXLSXPath"
    }
  }
  [threading.thread]::CurrentThread.CurrentCulture=$Cc  # Set the regional settings back
  if ($AutoRun -eq $True) { $Excel.Quit() ; [System.Runtime.Interopservices.Marshal]::ReleaseComObject($Excel) }

  try {
    Remove-Item $HTMLTempPath -Force -ErrorAction SilentlyContinue
  }
  catch {}

}


function Export-ToExcelAll($NameWithDate=$True, $PathToSave=$XLSXTempPath) {

  # Export and display all Tabs to Excel

  if ($NameWithDate -eq $True) {  
    $Now=(Get-Date).ToString("yyyyMMddHHmmss")
    $NewXLSXName=(New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).BaseName + "_" + $Now + (New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).Extension
    try {
      $NewXLSXPath=Join-Path -path (Split-Path $PathToSave -Parent) -ChildPath $NewXLSXName -ErrorAction Stop
    }
    catch {}
  }
  else {
    $NewXLSXPath=$PathToSave
  }


  $Cc=[threading.thread]::CurrentThread.CurrentCulture  # Save the current regional settings
  [threading.thread]::CurrentThread.CurrentCulture='en-US'  # Set the Culture to en-US to avoid some bugs

  $Excel=New-Object -ComObject Excel.Application
  $Excel.DisplayAlerts=$False  # Don't prompt the user 
  $ExcelDest=$Excel.Workbooks.Add()
  $ExcelDest.SaveAs($NewXLSXPath, 51)
  $sh1_wb1=$ExcelDest.Sheets.Item(1)  # First sheet in destination workbook
  $i=0

  foreach ($Tab in $ObjectsTabControl.Items) { 
    if ($Tab.Name -eq "TabPlus") { continue }
    $Tab.IsSelected=$True
    $HTMLExport=Export-ToHTML $False $False $False
    if ($HTMLExport -eq $False) {
      $ExportExcelAllForm.Close()
      $Excel.Quit()
      Remove-Variable Excel
      return
    }
    $i++
    $ExcelSource=$Excel.Workbooks.Open($HTMLTempPath, $Null, $True)  # Open the HTML source in readonly 
    $SheetToCopy=$ExcelSource.Sheets.Item(1)  # Source sheet to copy
    $Excel.Application.DisplayAlerts=$False 
    $SheetToCopy.Columns.Replace("%%NEWLINE%%","`r`n")
    $Excel.Application.DisplayAlerts=$True
    $SheetToCopy.Copy($sh1_wb1)  # Copy source sheet to destination workbook 
    $ExcelDest.Worksheets.Item($i).Name=$Tab.Header
    $ExcelSource.Close($False)  # Close source workbook without saving 
  }

  # Delete the last blank worksheet
  $SheetToDelete=$ExcelDest.Sheets.Item($ExcelDest.Worksheets.Count)
  $SheetToDelete.Delete()
  
  if ($Excel.Version -lt 15) {  # Version of Excel lower or equal to 14: suppress the 2 other blank worksheets
    $SheetToDelete=$ExcelDest.Sheets.Item($ExcelDest.Worksheets.Count)
    $SheetToDelete.Delete()
    $SheetToDelete=$ExcelDest.Sheets.Item($ExcelDest.Worksheets.Count)
    $SheetToDelete.Delete()
  }

  $Excel.Application.DisplayAlerts=$False
  $ExcelDest.Sheets.Item(1).Activate()
  $ExportExcelAllForm.Close()
  $ExcelDest.SaveAs($NewXLSXPath, 51)  # Save the newly created file
  [threading.thread]::CurrentThread.CurrentCulture=$Cc  # Set the regional settings back
  $Excel.Visible=$True
  $Excel.Application.DisplayAlerts=$True

  try {
    Remove-Item $HTMLTempPath -Force -ErrorAction SilentlyContinue
  }
  catch {}

}


function Export-ToHTML($UseStyle=$True, $Open=$True, $NameWithDate=$True, $PathToSave=$HTMLTempPath) {

  # Main function to export in HTML

  if ($AutoRun -eq $True) {  # Force values if AutoRun
    $CB_Export_Name=New-Object psobject ; $CB_Export_Name | Add-Member -MemberType NoteProperty -Name IsChecked -Value $True
    $CB_Export_Result=New-Object psobject ; $CB_Export_Result | Add-Member -MemberType NoteProperty -Name IsChecked -Value $True
    $CB_Export_State=New-Object psobject ; $CB_Export_State | Add-Member -MemberType NoteProperty -Name IsChecked -Value $True
    $CB_Export_SeqName=New-Object psobject ; $CB_Export_SeqName | Add-Member -MemberType NoteProperty -Name IsChecked -Value $False
    $CB_Export_Header=New-Object psobject ; $CB_Export_Header | Add-Member -MemberType NoteProperty -Name IsChecked -Value $True
    $CB_Export_Filtered=New-Object psobject ; $CB_Export_Filtered | Add-Member -MemberType NoteProperty -Name IsChecked -Value $False
    $CB_Export_Color=New-Object psobject ; $CB_Export_Color | Add-Member -MemberType NoteProperty -Name IsChecked -Value $True
    $CB_Export_Selection=New-Object psobject ; $CB_Export_Selection | Add-Member -MemberType NoteProperty -Name IsChecked -Value $False
  }

  $DV=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)
  $UseCustomHeader=$False
  $CustomHeaderAdded=$False
  $SelectedOnly=$CB_Export_Selection.IsChecked -eq $True

  if (($CB_Export_Result.IsChecked -eq $True) -and ($CB_Export_Header.IsChecked -eq $True)) {  # No Result or header to print: the custom headers can be skipped
    filter myFilter { if (($_.ToString() -ne "{NewItemPlaceholder}") -and ($_.SequenceName -ne "")) { $_ } }
    $SequencesInGrid=$DV | myFilter | Select-Object -ExpandProperty SequenceName -Unique  # Search all the unique Sequence Names
    $SequencesWithHeader=@()
    filter myFilter { if ($_.Name -eq $Seq) { $_ } }
    foreach ($Seq in $SequencesInGrid) {  # Search for sequences with a custom header
      $SequenceInfo=$SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1
      if ($SequenceInfo.Parameter.CustomHeader -ne "") {
        $SequencesWithHeader+=$SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1
      }
    }

    if (@($SequencesWithHeader).Count -gt 0) {  # Some sequences have a custom header
      if (($SelectedOnly -eq $True) -and ($MessageDuplicate -eq $False)) {
        $ResetSelectOnly=(MessageBox "WARNING" "Some Sequences have custom headers that are not compatible with the 'Show Selected Only' option. If you continue with the export, the selection will be cleared.`r`n`r`nDo you want to continue with this export ?" 4 2)
        $Script:MessageDuplicate=$True
        if ($ResetSelectOnly -ne "yes") {
          return $False
        }
      }

      if ($DV.Groups -ne $Null) {
        if (($DV.GroupDescriptions[0].PropertyName -ne "SequenceName") -or ($DV.GroupDescriptions.Count -ne 1)) {
          $ResetGroups=(MessageBox "WARNING" "Some Sequences have custom headers that are not compatible with grouping options.`r`nIf you continue with the export, your current grouping options will be reset.`r`n`r`nDo you want to continue with this export ?" 4 2)
          if ($ResetGroups -eq "yes") {
            $DV.GroupDescriptions.Clear()
            $DV.GroupDescriptions.Add((new-object System.Windows.Data.PropertyGroupDescription "SequenceName"))
            $CustomHeaderAdded=$True
          }
          else {
            return $False
          }
        }
      }
      else {  # No Group defined
        $DV.GroupDescriptions.Add((new-object System.Windows.Data.PropertyGroupDescription "SequenceName"))
        $CustomHeaderAdded=$True
      }
      $UseCustomHeader=$True
      $SelectedOnly=$False
    }
  }

  if ($DV.Groups -ne $Null) {  # Some groups were found
    $HTML=Export-CreateHTML_WithGroup -Object ($CB_Export_Name.IsChecked -eq $True) -TaskResult ($CB_Export_Result.IsChecked -eq $True) -State ($CB_Export_State.IsChecked -eq $True) `
                                      -SequenceName ($CB_Export_SeqName.IsChecked -eq $True) -Header ($CB_Export_Header.IsChecked -eq $True) -Hidden ($CB_Export_Filtered.IsChecked -eq $True) -Color ($CB_Export_Color.IsChecked -eq $True) `
                                      -OnlySelection $SelectedOnly -WithStyle $UseStyle -UseCustomHeader $UseCustomHeader
    if ($CustomHeaderAdded -eq $True) {
      $DV.GroupDescriptions.Clear()
      Set-ColumnTemplate 1
      Set-ColumnTemplate 2
      Set-ColumnTemplate 3
      Set-ColumnTemplate 4
      Set-ColumnTemplate 6
    }

  }
  else {  # No group found
    $HTML=Export-CreateHTML -Object ($CB_Export_Name.IsChecked -eq $True) -TaskResult ($CB_Export_Result.IsChecked -eq $True) -State ($CB_Export_State.IsChecked -eq $True) `
                                      -SequenceName ($CB_Export_SeqName.IsChecked -eq $True) -Header ($CB_Export_Header.IsChecked -eq $True) -Hidden ($CB_Export_Filtered.IsChecked -eq $True) -Color ($CB_Export_Color.IsChecked -eq $True) `
                                      -OnlySelection ($CB_Export_Selection.IsChecked -eq $True) -WithStyle $UseStyle
  }

  if ($NameWithDate -eq $True) {  
    $Now=(Get-Date).ToString("yyyyMMddHHmmss") 
    $NewHTMLName=(New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).BaseName + "_" + $Now + (New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).Extension
    $NewHTMLPath=Join-Path -path (Split-Path $PathToSave -Parent) -ChildPath $NewHTMLName
  }
  else {
    $NewHTMLPath=$PathToSave
  }

  if (($Open -eq $True) -or ($AutoRun -eq $True)) {  # Automatically open the browser if needed
    try {
      ConvertTo-HTML -head $HTML[0] -body "<H2>Sequence Results</H2> $($HTML[1] -replace "%%NEWLINE%%", "<BR>")" | Out-String | Out-File $NewHTMLPath -ErrorAction Stop # Build a HTML with the values returned by the Export HTML functions
    }
    catch {
      if ($AutoRun -eq $True) {
        MessageBox "Export" "AutoRunExport Error: Unable to create the Export file $NewHTMLPath"
      }
      else {
        MessageBox "Export" "Unable to create the Export file $NewHTMLPath"
      }
      return $False
    }
    if ($Open -eq $True) { Invoke-Expression $NewHTMLPath }
  }
  else {
    ConvertTo-HTML -head $HTML[0] -body "<H2>Sequence Results</H2> $($HTML[1])" | Out-String | Out-File $NewHTMLPath  # Build a HTML with the values returned by the Export HTML functions
  }

  return $True

}


function Export-ToHTML_All($UseStyle=$True, $Open=$True, $NameWithDate=$True, $PathToSave=$HTMLTempPath) {

  # Export all tabs to a single HTML file with tabs

  # Define the HTML templates, modified after or during the HTML creation
  $HTMLTemplate=@'
<!DOCTYPE html>
<html>
<head>
<style>
'@

  $HTMLTemplate+=$HTMLcss

  $HTMLTemplate+=@'
div.tab { overflow: hidden; padding: 8px }

div.tab button { background-color: inherit; float: left; border: 1px solid #aaa; outline: none; cursor: pointer;  padding: 8px 16px; font-size: 14px }

div.tab button:hover { background-color: #ddd }

div.tab button.active { background-color: #ccc }

.tabcontent { display: none; padding: 6px 12px; border-top: none }

</style>
</head>
<body>

<div class="tab">
###DIVCLASSTAB###
</div>

###DIVIDPART###

<script>
function openTab(evt, TabName) {
    var i, tabcontent, tablinks;
    tabcontent = document.getElementsByClassName("tabcontent");
    for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
    }
    tablinks = document.getElementsByClassName("tablinks");
    for (i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }
    document.getElementById(TabName).style.display = "block";
    evt.currentTarget.className += " active";
}

document.getElementById("defaultOpen").click();
</script>
     
</body>
</html> 
'@

  $DivIdClassTemplate=@'
  <button class="tablinks" onclick="openTab(event, '###XXX###')" id="defaultOpen">###XXX###</button>

'@

  $DivIdPartTemplate=@'

<div id="###XXX###" class="tabcontent">
<H2>Sequence Results</H2> ###HTML###
</div>

'@

  $DivClassPart=""
  $DivIdPart=""
  $FirstTab=$True
  $CurrentTab=$ObjectsTabControl.SelectedItem

  $UseGlobalCustomHeader=$False
  $CustomHeaderAdded=$False
  $HeaderDefined=$False

  if (($CB_Export_Result.IsChecked -eq $True) -and ($CB_Export_Header.IsChecked -eq $True)) {  # No Result or header to print: the custom headers can be skipped
    foreach ($Tab in $ObjectsTabControl.Items) {
      if ($Tab.Name -eq "TabPlus") { continue }
      $DV=[System.Windows.Data.CollectionViewSource]::GetDefaultView($Tab.Content.ItemsSource)
      filter myFilter { if (($_.ToString() -ne "{NewItemPlaceholder}") -and ($_.SequenceName -ne "")) { $_ } }
      $SequencesInGrid=$DV | myFilter | Select-Object -ExpandProperty SequenceName -Unique  # Search all the unique Sequence Names
      $SequencesWithHeader=@()
      filter myFilter { if ($_.Name -eq $Seq) { $_ } }
      foreach ($Seq in $SequencesInGrid) {  # Search for sequences with a custom header
        $SequenceInfo=$SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1
        if ($SequenceInfo.Parameter.CustomHeader -ne "") {
          $SequencesWithHeader+=$SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1
          $UseGlobalCustomHeader=$True
        }
      }
      if ((@($SequencesWithHeader).Count -gt 0) -and ($DV.Groups -ne $Null)) {
        if (($DV.GroupDescriptions[0].PropertyName -ne "SequenceName") -or ($DV.GroupDescriptions.Count -ne 1)) {
          $HeaderDefined=$True
        }
      } 
    }

    if ($HeaderDefined -eq $True) {
      $ResetGroups=(MessageBox "WARNING" "Some Sequences have custom headers that are not compatible with grouping options.`r`nIf you continue with the export, your current grouping options will be reset.`r`n`r`nDo you want to continue with this export ?" 4 2)
      if ($ResetGroups -ne "yes") {
        return
      }
    }

  }

  $SelectedOnly=$CB_Export_Selection.IsChecked -eq $True
  if (($SelectedOnly -eq $True) -and ($UseGlobalCustomHeader -eq $True)) {
    $ResetSelectOnly=(MessageBox "WARNING" "Some Sequences have custom headers that are not compatible with the 'Show Selected Only' option.`r`nIf you continue with the export, the selections will be cleared on some tabs.`r`n`r`nDo you want to continue with this export ?" 4 2)
    if ($ResetSelectOnly -ne "yes") {
      return
    }
  }

  foreach ($Tab in $ObjectsTabControl.Items) {  # Loop in all the Tabs
    if ($Tab.Name -eq "TabPlus") { continue }
    $Tab.IsSelected=$True  # Select the current tab, and export it

    $UseCustomHeader=$False
    $CustomHeaderAdded=$False
    $SequencesWithHeader=@()

    $DV=[System.Windows.Data.CollectionViewSource]::GetDefaultView($Tab.Content.ItemsSource)
    if ($UseGlobalCustomHeader -eq $True) {
      filter myFilter { if ($_.ToString() -ne "{NewItemPlaceholder}" ) { $_ } }
      $SequencesInGrid=$DV | myFilter | Select-Object -ExpandProperty SequenceName -Unique  # Search all the unique Sequence Names
      filter myFilter { if ($_.Name -eq $Seq) { $_ } }
      foreach ($Seq in $SequencesInGrid) {  # Search for sequences with a custom header
        $SequenceInfo=$SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1
        if ($SequenceInfo -ne $Null) {
          if ($SequenceInfo.Parameter.CustomHeader -ne "") {
            $SequencesWithHeader+=$SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter | Select-Object -Last 1
          }
        }
      }
      if (@($SequencesWithHeader).Count -gt 0) {  # Some sequences have a custom header
        if ($DV.Groups -ne $Null) {
          if (($DV.GroupDescriptions[0].PropertyName -ne "SequenceName") -or ($DV.GroupDescriptions.Count -ne 1)) {
            $DV.GroupDescriptions.Clear()
            $DV.GroupDescriptions.Add((new-object System.Windows.Data.PropertyGroupDescription "SequenceName"))
            $CustomHeaderAdded=$True
          }
        }
        else {  # No Group defined
          $DV.GroupDescriptions.Add((new-object System.Windows.Data.PropertyGroupDescription "SequenceName"))
          $CustomHeaderAdded=$True
        }
        $UseCustomHeader=$True
        $SelectedOnly=$False
      }
    }

    if ($DV.Groups -ne $Null) {  # Some groups were found
      $HTML=Export-CreateHTML_WithGroup -Object ($CB_Export_Name.IsChecked -eq $True) -TaskResult ($CB_Export_Result.IsChecked -eq $True) -State ($CB_Export_State.IsChecked -eq $True) `
                                        -SequenceName ($CB_Export_SeqName.IsChecked -eq $True) -Header ($CB_Export_Header.IsChecked -eq $True) -Hidden ($CB_Export_Filtered.IsChecked -eq $True) -Color ($CB_Export_Color.IsChecked -eq $True) `
                                        -OnlySelection $SelectedOnly -WithStyle $UseStyle -UseCustomHeader $UseCustomHeader
      if ($CustomHeaderAdded -eq $True) {
        $DV.GroupDescriptions.Clear()
        Set-ColumnTemplate 1
        Set-ColumnTemplate 2
        Set-ColumnTemplate 3
        Set-ColumnTemplate 4
        Set-ColumnTemplate 6
      }
    }
    else {  # No group found
      $HTML=Export-CreateHTML -Object ($CB_Export_Name.IsChecked -eq $True) -TaskResult ($CB_Export_Result.IsChecked -eq $True) -State ($CB_Export_State.IsChecked -eq $True) `
                              -SequenceName ($CB_Export_SeqName.IsChecked -eq $True) -Header ($CB_Export_Header.IsChecked -eq $True) -Hidden ($CB_Export_Filtered.IsChecked -eq $True) -Color ($CB_Export_Color.IsChecked -eq $True) `
                              -OnlySelection ($CB_Export_Selection.IsChecked -eq $True) -WithStyle $UseStyle  
    }

    # Adapt the HTML code
    $DivClassPartTemp=$DivIdClassTemplate -replace "###XXX###", $Tab.Header
    if ($FirstTab -eq $True) { $FirstTab=$False } else { $DivClassPartTemp=$DivClassPartTemp -replace 'id="defaultOpen"', "" }
    $DivClassPart+=$DivClassPartTemp

    $DivIdPartTemp=$DivIdPartTemplate -replace "###XXX###", $Tab.Header
    $DivIdPartTemp=$DivIdPartTemp -replace "###HTML###", $($HTML[1] -replace "%%NEWLINE%%", "<BR>")
    $DivIdPart+=$DivIdPartTemp
  }

  $HTMLTemplate=$HTMLTemplate -replace "###DIVCLASSTAB###", $DivClassPart
  $HTMLTemplate=$HTMLTemplate -replace "###DIVIDPART###", $DivIdPart

  if ($NameWithDate -eq $True) {
    $Now=(Get-Date).ToString("yyyyMMddHHmmss")  
    $NewHTMLName=(New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).BaseName + "_" + $Now + (New-Object System.IO.FileInfo(Split-Path $PathToSave -Leaf)).Extension
    $NewHTMLPath=Join-Path -path (Split-Path $PathToSave -Parent) -ChildPath $NewHTMLName
  }
  else {
    $NewHTMLPath=$PathToSave
  }

  $HTMLTemplate | Out-File $NewHTMLPath
  $ObjectsTabControl.SelectedItem=$CurrentTab
  if ($Open -eq $True) {  # Automatically open the browser if needed
    Invoke-Expression $NewHTMLPath
  }

}


function Get-ADPicker {

  # Get AD objects from the AD Picker

  if ($tbADPickerMaxEntries.Text -match "^[\d\.]+$") {  # A correct number has been entered
    if (([int]($tbADPickerMaxEntries.Text) -gt 50000) -or ([int]($tbADPickerMaxEntries.Text) -le 0)) {
      MessageBox "AD Picker" "Please enter a correct value for the Maximum Entries between 1 and 50000" 3 1
      return
    }
    else {
      $MaxSearch=[int]$($tbADPickerMaxEntries.Text)
    }
  }
  else {  # $tbADPickerMaxEntries is not numeric
    MessageBox "AD Picker" "Please enter a numeric value as Maximum Entries" 3 1
    return
  } 

  $Prop=$cbProperties.SelectedValue -replace " ", ""
  $PropFilter=""
  $nbofProp=0

  foreach ($Pattern in $($tbADPickerPattern.Text).Split(",")) {  # Create the pattern(s)
    $PropFilter+="($Prop=$Pattern)"
    $nbofProp++
  }
  if ($nbofProp -gt 1) {
    $PropFilter="(|$PropFilter)"
  }

  # Set all option for the AD Searcher
  $SearchRoot="LDAP://$($tvADPicker.SelectedItem.Tag)"  
  if ($rbComputers.IsChecked) { $ADFilter="(&(objectCategory=Computer)$PropFilter)" }
  if ($rbUsers.IsChecked) { $ADFilter="(&(objectCategory=User)$PropFilter)" }
  if ($rbGroups.IsChecked) { $ADFilter="(&(objectCategory=Group)$PropFilter)" }

  $ADSearcher=[adsisearcher]"$ADFilter"
  $ADSearcher.SearchRoot=$SearchRoot
  $ADSearcher.SizeLimit=$MaxSearch
  $ADSearcher.PageSize=$MaxSearch
  $ADSearcher.PropertiesToLoad.Add($Prop)
  $ListOfObjectsFound=@()
  $ADSearcher.FindAll() | Select-Object -first $MaxSearch | ForEach-Object { $ListOfObjectsFound+=$_.Properties[$Prop][0] }

  if (@($ListOfObjectsFound).Count -eq 0) {
    MessageBox "AD Picker" "Unable to find any object matching your criteria" 3 1
    return
  }

  $ADPickerForm.Close()
  foreach ($Obj in $ListOfObjectsFound) {  # Loop to get all objects
    try {
      Set-ObjectSettings $Obj.ToString()  # Create the objects in the grid
    }
    catch {}
  }

  Set-State

}


function Get-ADObjects {

  # Get AD objects from a Query

  if (!(Get-Module ActiveDirectory)) {  # Load the AD module if not already loaded
    try {
      Import-Module ActiveDirectory -ErrorAction Stop
    }
    catch {
      MessageBox "AD Query" "Cannot load the ActiveDirectory module." 3 1 
      return
    }
  }
  
  # Run the Query defined in the "Query AD" window

  try {
    $ADObjList=Invoke-Expression -Command $tb_ADQuery.Text -ErrorAction Stop | Where-Object { $_ -like $tb_ADQueryPattern.Text }
  }
  catch {
    MessageBox "AD Query" "The query you've entered is not correct." 3 1 
    return
  }

  if ($ADObjList -eq $Null) {
    MessageBox "AD Query" "Nothing found matching your query." 3 1
    return
  }

  $ADQueryForm.Close()

  foreach ($Obj in $ADObjList) {  # Loop to get all objects
    try {
      Set-ObjectSettings $Obj.ToString()  # Create the objects in the grid
    }
    catch {}
  }

  Set-State

}


function Get-FileButton($NameFilter="All files|*.*", $InitialPath="") {

  # Help function for the OpenFile Dialog window

  $OpenFileDialog=New-Object System.Windows.Forms.OpenFileDialog
  if ($InitialPath -ne "") {
    $OpenFileDialog.InitialDirectory=$InitialPath
  }
  $OpenFileDialog.Filter="$NameFilter"
  $OpenFileDialog.ShowHelp=$True
  $OpenFileDialog.ShowDialog() | Out-Null
  return $OpenFileDialog.FileName

}


function Get-IfPreLoad($Obj) {

  # PreLoad part

  if ($SequenceSettings[$Obj.SequenceID].PreLoadInProgress -eq $False) {  # The sequence was not a PreLoad
    return
  }

  if ($Obj.InProgress -eq $False) {  # A PreLoad has ended in STOP, BREAK or ERROR
    $ObjInSequence=@()
    foreach ($dgis in $DataGridItemSource) {  # Get all other objects of this Sequence
      filter myFilter { if ($_.SequenceID -eq $Obj.SequenceID) { $_ } }
      $ObjInSequence+=$dgis | myFilter
    }
    $Obj.TaskResults+= " (PreLoad issue)"
    $Obj.TaskResultsExport+= " (PreLoad issue)"
    $Obj.State=$Obj.State -replace "at step", "at PreLoad"
    $TaskRes=$Obj.TaskResults+ " (PreLoad issue)"
    foreach ($OtherObject in $ObjInSequence) {  # Set all other objects in STOP (PreLoad issue)
      $OtherObject.InProgress=$False
      $OtherObject.IsEnabled=$True
      $OtherObject.TaskResults=$Obj.TaskResults
      $OtherObject.TaskResultsExport=$Obj.TaskResults
      if ($OtherObject.UniqueID -ne $Obj.UniqueID) { 
        $OtherObject.Historic+="  PreLoad $($Obj.Step +1) - " + $Obj.TaskResults
        $OtherObject.TaskHistory+="PreLoad $($Obj.Step +1) - " + $Obj.TaskResults
      }
      if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
        Write-DebugLog "$($Obj.Objects);STOP;PreLoad issue at Step $($Obj.Step +1);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
      }
      $OtherObject.Step=0
      $OtherObject.StepToString="0"
      $OtherObject.State=$Obj.State 
      $OtherObject.IsChecked=$False
      $OtherObject.SharedVariable=$Null
      $OtherObject.Color=$Obj.Color
      $Script:ObjectsCounting[$OtherObject.Tab]++
      $Script:SequenceLog[$Obj.SequenceID]+=$(Get-Date -Format "dd.MM.yyyy") + " ; " + ($OtherObject.Historic -join " ;")
      $Script:SequenceStats[$Obj.SequenceID].Stop++
      $Script:SequenceStats[$Obj.SequenceID].NbOfObjects++
      if ((Get-Date) -gt $SequenceStats[$Obj.SequenceID].EndTime) { $Script:SequenceStats[$Obj.SequenceID].EndTime=Get-Date }
    }
    return
  }

  if ($($SequenceSettings[$Obj.SequenceID].Task[$Obj.Step+1].Type -ne "PreLoad")) {  # The task was the Last PreLoad 
    $Script:SequenceSettings[$Obj.SequenceID].PreLoadInProgress=$False
    $Script:SequenceSettings[$Obj.SequenceID].FirstStep=$($Obj.Step)+1
    if ($Obj.SharedVariable -ne $Null) {  # The PreLoad steps have generated a shared variable
      $GlobalSharedVariable=$Obj.SharedVariable
      $ObjInSequence=@()
      foreach ($dgis in $DataGridItemSource) {  # Get all other objects of this Sequence
        filter myFilter { if ($_.SequenceID -eq $Obj.SequenceID) { $_ } }
        $ObjInSequence+=$dgis | myFilter
      }
      foreach ($OtherObject in $ObjInSequence) {  # Dispatch the shared variable to all other objects
        $OtherObject.SharedVariable=$GlobalSharedVariable
      }
    }
  }

}


function Get-IPRange {
  
  # Create a list of IP's

  if ( (!([bool]($tb_IPStart.Text -as [ipaddress]))) -or (!([bool]($tb_IPEnd.Text -as [ipaddress]))) ) {  # One of the values entered is not a correct IP
    MessageBox "IP Range" "Unable to validate the IP." 3 1
    return
  }
  
  # IP operations
  $IP1=([System.Net.IPAddress]$($tb_IPStart.Text)).GetAddressBytes()
  [Array]::Reverse($IP1)
  $IP1=([System.Net.IPAddress]($IP1 -join '.')).Address

  $IP2=([System.Net.IPAddress]$($tb_IPEnd.Text)).GetAddressBytes()
  [Array]::Reverse($IP2)
  $IP2=([System.Net.IPAddress]($IP2 -join '.')).Address

  # Create the IP range
  $IPObjectList=@()
  for ($x=$IP1; $x -le $IP2; $x++) {
    $IP=([System.Net.IPAddress]$x).GetAddressBytes()
    [Array]::Reverse($IP)
    $IPObjectList+=($IP -join '.')
  }

  if (@($IPObjectList).Count -eq 0) {
    MessageBox "IP Range" "Unable to create a range with these values." 3 1
    return
  }

  if (@($IPObjectList).Count -gt 1024) {
    MessageBox "IP Range" "Unable to create a range with more than 1024 values." 2 1
    return
  }

  $IPQueryForm.Close()

  foreach ($Obj in $IPObjectList) {  # Add the objects created to the grid
    try {
      Set-ObjectSettings $Obj
    }
    catch {}
  }

  Set-State

}


function Get-DemoSequenceList {

  if ($MenuSequences4.Header -eq "Reload the Original Sequence List") {
    Get-NewSequenceList $SequencesListPath
    $RibbonSequences4.Label="Load the Demos Sequence List"
    $MenuSequences4.Header="Load the Demos Sequence List"
    $MenuImage=New-Object System.Windows.Controls.Image
    $MenuImage.Source=[Convert]::FromBase64String($Icon381Base64)
    $MenuImage.Height=16
    $MenuImage.Width=16
    $RibbonSequences4.LargeImageSource=Set-Icon $Icon054Base64
    if ($ribHome.Items.Items | Where-Object Label -eq "Reload the Original Sequence List") {
      $rib=$ribHome.Items.Items | Where-Object Label -eq "Reload the Original Sequence List"
      $rib.Label="Load the Demos Sequence List"
      $rib.LargeImageSource=Set-Icon $Icon054Base64
    }
    return 
  }
  
  $DemoSequenceList=Join-Path $HydraBinPath "Bin\_Examples\Hydra_Sequences_Demo.lst"

  if (Test-Path $DemoSequenceList) {  # The Demo Sequence List has been found
    $CurrentSequencesListPath=$SequencesListPath
    Get-NewSequenceList $DemoSequenceList
    $RibbonSequences4.Label="Reload the Original Sequence List"
    $MenuSequences4.Header="Reload the Original Sequence List"
    $Script:SequencesListPath=$CurrentSequencesListPath
    $MenuImage=New-Object System.Windows.Controls.Image
    $MenuImage.Source=[Convert]::FromBase64String($Icon382Base64)
    $MenuImage.Height=16
    $MenuImage.Width=16
    $MenuSequences4.Icon=$MenuImage
    $RibbonSequences4.LargeImageSource=Set-Icon $Icon055Base64
    if ($ribHome.Items.Items | Where-Object Label -eq "Load the Demos Sequence List") {
      $rib=$ribHome.Items.Items | Where-Object Label -eq "Load the Demos Sequence List"
      $rib.Label="Reload the Original Sequence List"
      $rib.LargeImageSource=Set-Icon $Icon055Base64
    }
  }
  else {
    MessageBox "Demo Sequence List" "The Demo Sequence List could not be found:`r`n`r`n$DemoSequenceList" 2 1
  }

}


function Get-ItemsMaxAddParams($GridID) {

  $MaxAddParams=$TabObjectAdditionalParams[$GridId]

  filter myFilter { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }

  $ObjectsTabControl.SelectedItem.Content.Items | myFilter | ForEach-Object { 
    if (@($_.AddParams).Count -gt $MaxAddParams) { $MaxAddParams=@($_.AddParams).Count }
  }

  return $MaxAddParams

}


function Get-NewSequenceList($SeqListFile="") {

  # Loads a Sequence manually and creates an entry in the Sequence Tree

  if ($SeqListFile -eq "") {
    # Select the file to process
    $SeqListFile=Get-FileButton "Hydra Sequence List (*.lst)|*.lst|All files|*.*" $LastDirSequences
    if (($SeqListFile -eq $Null) -or ($SeqListFile -eq "")) { return }
  }

  # Save the manually loaded sequences
  Remove-Variable Recent* -Scope Script
  $ManuallyLoaded=$SequencesTreeView.Items | Where-Object { $_.Header.Tag -like "*Manually Loaded*" } | Select-Object -ExpandProperty Items | Select-Object Header, Tag
  $RegRecent=Get-ItemProperty $HydraRegPath -ErrorAction SilentlyContinue | ForEach-Object { $_.PSObject.Properties } | Where-Object { $_.Name -like "Recent*" } | Select-Object -ExpandProperty Name
  $RegRecent | ForEach-Object { Remove-ItemProperty -Path $HydraRegPath -Name $_ }
  $i=0
  foreach ($ML in $ManuallyLoaded) {
    $i++
    $RegName="Recent{0:D2}" -f $i
    $RegData="$($ML.Header.Tag)|$($ML.Tag)"
    Set-ItemProperty -Path $HydraRegPath -Name $RegName -Value $RegData -Force
    Set-Variable -Name $RegName -Value $RegData -Force
  }

  $Script:LastDirSequences=Split-Path $SeqListFile  # Save the last directory for registry user's settings on close
  $Script:SequencesListPath=@()
  $Script:SequencesListPath+=$SeqListFile
  $Script:SequenceList=Import-Csv -Delimiter ";" -Path $SequencesListPath[0] -Header SeqName, SeqPath, Icon  # Create the variable SequenceList with names and paths
  SequenceTreeViewLoad $SequenceList

  SequencesTreeViewManuallyLoadedSaved
  $SequencesTreeView.Items[0].IsSelected=$True

}


function Get-ObjectsManually($ObjectList=$Null) {

  # Enter or paste a list of objects separated by separators

  if ($ObjectList -eq $Null) {
    $ObjectList=Read-InputBoxDialog "Objects" "Enter the list of Objects separated by a , ; or |" ""
    if ($ObjectList -eq "") { return }
  }

  $Separator=";",",","|"  # Use Separators to split the objects and remove useless spaces
  [System.Collections.ArrayList]$ObjectList=@($ObjectList.Split([string[]]$Separator, [System.StringSplitOptions]::None).Trim())

  for ($i=$ObjectList.Count-1; $i -ge 0; $i--) {  # Remove empty objects to avoid empty rows
    if ($ObjectList[$i] -eq "") { $ObjectList.RemoveAt($i) }
  }  

  foreach ($Obj in $ObjectList) {  # Loop to get all objects
    try {
      Set-ObjectSettings $Obj.ToString()  # Create the objects in the grid
    }
    catch {}
  }

  Set-State

}


function Get-ObjectReturnedState($Obj, $TimedOut=$False) {

  # A Runspace has finished: get its returned object. The returned objects is a collections of values: State, Comment [,Color] [,Shared Variable] 

  $ErrorState=$False
  $JobResultColor=$Null
  $JobResultSharedVariable=$Null
  $JobResultTaskResultExport=$Null
  $JobResultGotoStep=$Null
  $TooMuchObj=$False
  $NextStep=0

  if($TimedOut -eq $False) {

    try {
      $TaskResultExport=$Null
      $xReceive=$Obj.Runspace.PowerShell.EndInvoke($Obj.Runspace.Runspace)  # Use the EndInvoke methode to get the state of the Runspace
      $Obj.Runspace.PowerShell.Dispose()  # Dispose the Runspace
      # Check if the returned object is a $HydraReturn one: 
      if ( (($xReceive | Get-Member  -ErrorAction Stop | Select-Object -ExpandProperty Name) -contains 'State') -and (($xReceive | Get-Member -ErrorAction Stop | Select-Object -ExpandProperty Name) -contains 'TaskResult') ) { # Extended $HydraReturn object returned
        $JobResultState=$xReceive.State
        $JobResultComment=$xReceive.TaskResult
        if (($xReceive | Get-Member | Select-Object -ExpandProperty Name) -contains 'Color') { $JobResultColor=$xReceive.Color }
        if (($xReceive | Get-Member | Select-Object -ExpandProperty Name) -contains 'SharedVariable') { $JobResultSharedVariable=$xReceive.SharedVariable }
        if (($xReceive | Get-Member | Select-Object -ExpandProperty Name) -contains 'TaskResultExport') { $JobResultTaskResultExport=$xReceive.TaskResultExport }
        if (($xReceive | Get-Member | Select-Object -ExpandProperty Name) -contains 'GotoStep') { $JobResultGotoStep=$xReceive.GotoStep }
      }
      else {  # Legacy format
        $JobResultState=$xReceive[0]  # The 1st mandatory returned object is the State ("OK", "STOP", "BREAK")
        $JobResultComment=$xReceive[1]  # The 2nd mandatory returned object is the Comment (Task Result) to set
        if ($xReceive.Count -ge 3) { $JobResultColor=$xReceive[2] }
        if ($xReceive.Count -ge 4) { $JobResultSharedVariable=$xReceive[3] }
        if ($xReceive.Count -gt 4) { $TooMuchObj=$True }
      }
    }
    catch {
      $JobResultState="ERROR"
      $ErrorState=$True
      $JobResultComment="Error in Task (Not enough or wrong objects returned: enable Debug for details)"
      if ($DebugMode -eq 1) { 
        Write-Host "`n $($Obj.Objects): Not enough or wrong objects returned" 
        Write-DebugReceiveOutput $xReceive
      }
    }

  }
  else {  # Timed out

    $ContinueAfterTimeOut=$False
    if ($SequenceSettings[$Obj.SequenceID].Parameter.TimeOut -gt 0) { $ContinueAfterTimeOut=$SequenceSettings[$Obj.SequenceID].Parameter.ContinueAfterTimeout -eq $true }
    if ($SequenceSettings[$Obj.SequenceID].Task[$Obj.Step].TimeOut -gt 0) { $ContinueAfterTimeOut=$SequenceSettings[$Obj.SequenceID].Task[$Obj.Step].ContinueAfterTimeout -eq $true }

    if ($ContinueAfterTimeOut -eq $true -or $SequenceSettings[$Obj.SequenceID].PostTaskInProgress -eq 2) {
      $JobResultState="OK"
    }
    else {
      $JobResultState="STOP"
    }
    $JobResultComment="Task timed out"
    $JobResultColor=$Colors.Get_Item($JobResultState)
    $JobResultSharedVariable=$Obj.SharedVariable
    $Obj.TasksTimedOut+=$Obj.Step

  }

  if ($TooMuchObj -eq $True) {  # More than 4 values were found in the object returned by the Runspace
    $JobResultState="ERROR"
    $ErrorState=$True
    $JobResultComment="Error in Task (Too much objects returned: enable Debug for details)"
    if ($DebugMode -eq 1) {
      Write-Host "`n $($Obj.Objects): $($xReceive.Count) Objects returned (too much)"
      Write-DebugReceiveOutput $xReceive
    }
  }
  elseif ($JobResultState -NotIn @("OK", "GOTO", "END", "BREAK", "STOP", "ERROR")) {  # The STATE keyword received is unknown
    $JobResultState="ERROR"
    $ErrorState=$True
    $JobResultComment="Error in Task (Wrong keyword returned: enable Debug for details)"
    if ($DebugMode -eq 1) { 
      Write-Host "`n $($Obj.Objects): Wrong keyword returned: $JobResultState)"
      Write-DebugReceiveOutput $xReceive
    }
  }
  elseif ($JobResultState -eq "GOTO") {
    if ($JobResultGotoStep -eq $Null) {
      $JobResultState="ERROR"
      $ErrorState=$True
      $JobResultComment="Error in Task (GOTO keyword without GotoStep defined: enable Debug for details)"
      if ($DebugMode -eq 1) { 
        Write-Host "`n $($Obj.Objects): GOTO keyword without GotoStep defined)"
        Write-DebugReceiveOutput $xReceive
      }
    }
    else {  # A GOTO and an Id were defined: search for the Task ID
      for ($i=1; $i -le $SequenceSettings[$Obj.SequenceID].Task.Count-1; $i++) {          
        if ($SequenceSettings[$Obj.SequenceID].Task[$i].Id -eq $JobResultGotoStep) {
          $NextStep=$i
        }
      }
      if ($NextStep -eq 0) {
        $JobResultState="ERROR"
        $ErrorState=$True
        $JobResultComment="Error in Task (GOTO keyword with unknown GotoStep Id $JobResultGotoStep`: enable Debug for details)"
        if ($DebugMode -eq 1) { 
          Write-Host "`n $($Obj.Objects): GOTO keyword with unknown GotoStep Id $JobResultGotoStep)"
          Write-DebugReceiveOutput $xReceive
        }
      }
      elseif ($NextStep -in $Obj.StepsToSkip) {  # Verify if the Next task is unchecked
        $JobResultState="STOP"
        $JobResultComment="Unable to go the Step $NextStep ($($SequenceSettings[$Obj.SequenceID].Task[$NextStep].Comment)), because it is unchecked"
      }
    }
  }

  if ($ErrorState) {  # An error has been found: set the parameters to the Cancel values
    $Obj.InProgress=$False
    $Obj.IsEnabled=$True
    $Obj.TaskResults=$JobResultComment -f $Obj.LastTaskResults
    $Obj.TaskResultsExport=$(if ($JobResultTaskResultExport -ne $null) { $JobResultTaskResultExport } else { $Obj.TaskResults })
    $Obj.State="ERROR at step $($Obj.Step)"
    $Obj.IsChecked=$False
    $Obj.SharedVariable=$Null
    $Obj.Color=$Colors.Get_Item("CANCELLED")
    $Obj.Historic+="  Step $($Obj.Step) - " + $JobResultState + " - " + $JobResultComment
    $Obj.Historic+="End on $(Get-Date -Format "HH:mm:ss")"
    $Obj.TaskHistory+=$JobResultComment
    if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);ERROR;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
    }
    $Obj.Step=0
    $Obj.StepToString="0"
    $Script:ObjectsCounting[$Obj.Tab]++
    Get-IfPreLoad $Obj
    $Script:SequenceLog[$Obj.SequenceID]+=$(Get-Date -Format "dd.MM.yyyy") + " ; " + ($Obj.Historic -join " ;")
    $Script:SequenceStats[$Obj.SequenceID].Cancel++
    $Script:SequenceStats[$Obj.SequenceID].NbOfObjects++
    if ((Get-Date) -gt $SequenceStats[$Obj.SequenceID].EndTime) { $Script:SequenceStats[$Obj.SequenceID].EndTime=Get-Date }
    return
  }

  $BackgroundColor=$Colors.Get_Item($JobResultState)
  $Obj.ColorTemp=$Null

  if ($JobResultColor -ne $Null) {  # A color has been defined
    # Set the cell format to default
    $Obj.CellFontFormated=$True
    $Obj.CellFontFamily=$FontDefaultFamily
    $Obj.CellFontSize=$FontDefaultSize
    $Obj.CellFontStyle=$FontDefaultStyle
    $Obj.CellFontWeight=$FontDefaultWeight
    $Obj.CellFontColor=$FontDefaultColor
    $CellFormatReturned=$JobResultColor.Split("|")
    if ($CellFormatReturned[0] -eq "Default") { $CellFormatReturned[0]=$BackgroundColor }
    if (!(Test-Color $CellFormatReturned[0])) {  # The cell background is not valid
      if ($DebugMode -eq 1) {
        Write-Host "`nWrong color value: $($CellFormatReturned[0]) is not a valid HTML color or in format #FFxxxxxx. Reset to default"
      }
    }
    else {  # The cell background set was valid: check the next parameters, if any
      $BackgroundColor=$CellFormatReturned[0]
      $Obj.ColorTemp=$BackgroundColor
      $CellFormatReturnedSplit=$CellFormatReturned.Split("|")
      for ($i=1; $i -lt @($CellFormatReturnedSplit).Count; $i++) {
        if (Test-Color $CellFormatReturnedSplit[$i]) { $Obj.CellFontColor=$CellFormatReturnedSplit[$i] }
        elseif ($CellFormatReturnedSplit[$i] -in $FontWeightValues) { $Obj.CellFontWeight=$CellFormatReturnedSplit[$i] }
        elseif ($CellFormatReturnedSplit[$i] -in $FontStyleValues) { $Obj.CellFontStyle=$CellFormatReturnedSplit[$i] }
        elseif ($CellFormatReturnedSplit[$i] -in $FontFamilyValues) { $Obj.CellFontFamily=$CellFormatReturnedSplit[$i] }
        elseif ([float]::TryParse($CellFormatReturnedSplit[$i], [ref]"")) { $Obj.CellFontSize=$CellFormatReturnedSplit[$i] }
        else {  # Nothing known detected
          if ($DebugMode -eq 1) {
            Write-Host "`nUnknown value: $($CellFormatReturnedSplit[$i]) is not a valid color or font parameter"
          }
        }
      }
    }
  }

  if (($JobResultState -eq "STOP") -or ($JobResultState -eq "BREAK") -or ($JobResultState -eq "END")) {  # The sequence has to be stopped
    $Obj.InProgress=$False
    $Obj.IsEnabled=$True
    $Obj.TaskResults=$JobResultComment -f $Obj.LastTaskResults
    $Obj.TaskResultsExport=$(if ($JobResultTaskResultExport -ne $null) { $JobResultTaskResultExport } else { $Obj.TaskResults })
    $JobResultStateToDisplay=$JobResultState
    if ($JobResultState -eq "STOP" -and $Obj.TasksTimedOut) {
      $JobResultStateToDisplay="TIMEOUT"
    }
    $Obj.State="$JobResultStateToDisplay at step $($Obj.Step)"
    $Obj.IsChecked=$False
    $Obj.SharedVariable=$Null
    $Obj.Color=$BackgroundColor
    $Script:ObjectsCounting[$Obj.Tab]++
    $Obj.Historic+="  Step $($Obj.Step) - " + $JobResultStateToDisplay + " - " + $JobResultComment
    $Obj.Historic+="End on $(Get-Date -Format "HH:mm:ss")"
    $Obj.TaskHistory+=$JobResultComment
    if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);$JobResultStateToDisplay;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
    }
    Get-IfPreLoad $Obj
    $Obj.Step=0
    $Obj.StepToString="0"
    $Script:SequenceLog[$Obj.SequenceID]+=$(Get-Date -Format "dd.MM.yyyy") + " ; " + ($Obj.Historic -join " ;")
    $Script:SequenceStats[$Obj.SequenceID].$JobResultState++
    $Script:SequenceStats[$Obj.SequenceID].NbOfObjects++
    if ((Get-Date) -gt $SequenceStats[$Obj.SequenceID].EndTime) { $Script:SequenceStats[$Obj.SequenceID].EndTime=Get-Date }
    return
  }
  
  if ($JobResultSharedVariable -ne $Null) {  # A Shared variable has been set
    $Obj.SharedVariable=$JobResultSharedVariable  # Set the Shared variable usable for the next steps
  }

  # OK or GOTO Status

  if ($JobResultState -eq "GOTO") {
    if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);$JobResultState;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
    }
    if ($NextStep -ne 0) {
      $Obj.NextStep=$NextStep
    }
  }

  $Obj.Historic+="  Step $($Obj.Step) - " + $JobResultState + " - " + $JobResultComment
  $Obj.TaskHistory+=$JobResultComment

  if (($Obj.Step -eq $Obj.nbTotalSteps) -and ($JobResultState -ne "GOTO")) {  # Last step: set the color
    $Obj.TaskResults=$JobResultComment -f $Obj.LastTaskResults
    $Obj.TaskResultsExport=$(if ($JobResultTaskResultExport -ne $null) { $JobResultTaskResultExport } else { $Obj.TaskResults })
    $Obj.Color=$BackgroundColor
    $Obj.IsChecked=$False
    $Obj.SharedVariable=$Null
    $Obj.State="OK"
    if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);$JobResultState;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog  # End of Sequence
    }
    $Obj.Historic+="End on $(Get-Date -Format "HH:mm:ss")"
    $Script:SequenceLog[$Obj.SequenceID]+=$(Get-Date -Format "dd.MM.yyyy") + " ; " + ($Obj.Historic -join " ;")
    $Script:SequenceStats[$Obj.SequenceID].OK++
    $Script:SequenceStats[$Obj.SequenceID].NbOfObjects++
    if ((Get-Date) -gt $SequenceStats[$Obj.SequenceID].EndTime) { $Script:SequenceStats[$Obj.SequenceID].EndTime=Get-Date }
    $Script:ObjectsCounting[$Obj.Tab]++
  }
  elseif ($JobResultState -ne "GOTO") {
    if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);$JobResultState;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
    }
  }
  
  $Obj.LastTaskResults=$JobResultComment -f $Obj.LastTaskResults
  Get-IfPreLoad $Obj

}


function Get-RegistrySettings {

  # Read all the variables set in HKCU:\SOFTWARE\Hydra\7 and override the default ones

  if ($AutoRun -eq $True) {  # Don't import the registry value of UseAutoSave to keep it false when AutoRun is in use
    $RegHydra=Get-ItemProperty $HydraRegPath -ErrorAction SilentlyContinue | Select-Object * -ExcludeProperty PS*, HydraVersion | ForEach-Object { $_.PSObject.Properties } | Where-Object Name -ne "UseAutoSave" | Select-Object Name, Value
  }
  else {
    $RegHydra=Get-ItemProperty $HydraRegPath -ErrorAction SilentlyContinue | Select-Object * -ExcludeProperty PS*, HydraVersion | ForEach-Object { $_.PSObject.Properties } | Select-Object Name, Value
  }

  Remove-Variable Recent* -Scope Global
  if ($RegHydra -ne $Null) {
    foreach ($RegEntry in $RegHydra) { 
      if ($RegEntry.Name -like ("Color_*")) {  # Color variable found: set the HEX value
        $Colors.Set_Item(($RegEntry.Name -split("_"))[1], $RegEntry.Value)
      }
      else {  # Set the value found to the corresponding name
        Set-Variable -Name $RegEntry.Name -Value $RegEntry.Value -Scope Script -Force
      }
    }
  }

  if (Test-Path "$HydraRegPath\Favorites") {
    $Script:Favorites=@(Get-ItemProperty "$HydraRegPath\Favorites" -ErrorAction SilentlyContinue | Select-Object * -ExcludeProperty PS* | ForEach-Object { $_.PSObject.Properties } | Where-Object Name -like "Favorite*" | Select-Object -ExpandProperty Value | Select-Object -Unique)
  }

  # Overwrite with command line Settings

  $Settings.GetEnumerator() | ForEach-Object {
    Set-Variable -Name $_.Key -Value $_.Value -Scope Script -Force
  }

  try {
    $Script:RibbonHomeHashTemp=Invoke-Expression $RibbonHomeHash -ErrorAction Stop
  }
  catch {
    New-Variable -Name RibbonHomeHash -Value '[ordered]@{"Load"="RibbonLoad1","RibbonLoad2","RibbonLoad3";"Sequences"="RibbonSequences1";"Objects"="RibbonObjects1","RibbonObjects2","RibbonObjects4";"Export"="RibbonExport2";"Cancel"="RibbonObjects7"}' -Scope Script -Force
  }

  Check-TempPaths @{'CSV Temp Path'=$CSVTempPath;'HTML Temp Path'=$HTMLTempPath;'XLSX Temp Path'=$XLSXTempPath} | Out-Null

  if ([string]::IsNullOrEmpty($FontDefaultFamily)) { $Script:FontDefaultFamily="Segoe UI" }

  if ($CSVDelimiter -ne '`t') {
    try {
      $CSVDelimiterCheck=[char]$CSVDelimiter
    }
    catch {
      $Script:CSVDelimiter=","
    }
  }

}


function Get-SequenceFileManual($SeqFilePath=$Null, $NameToUse=$Null) {

  # Loads a Sequence manually and creates an entry in the Sequence Tree

  if ($SeqFilePath -eq $Null) {
    # Select the file to process
    $SeqFilePath=Get-FileButton "Hydra Sequence (*.sequence.xml)|*.sequence.xml|All files|*.*" $LastDirSequences
    if (($SeqFilePath -eq $Null) -or ($SeqFilePath -eq "")) { return }
  }

  $xmldata=New-Object System.Xml.XmlDocument  # Creates a new XML object
  try {  # Search for a "sequence" and a "task" tag in the file selected
    $xmldata.Load((Get-ChildItem -Path $SeqFilePath).FullName)
    if (Get-Member -inputobject $xmldata -name "sequence" -Membertype Properties) {
      if ((Get-Member -inputobject $xmldata -name "task" -Membertype Properties) -eq $False) {  # Format of the xml file not correct
        MessageBox "Sequence" "The format of this file is unknown and not compatible to a Hydra Sequence." 3 1
        return
      }
    }
    else {  # Format of the xml file not correct
      MessageBox "Sequence" "The format of this file is unknown and not compatible to a Hydra Sequence." 3 1
      return
    }
  }
  catch [System.Xml.XmlException] {
    MessageBox "Sequence" "The format of this file is unknown and not compatible to a Hydra Sequence." 3 1
    return
  }

  $Script:LastDirSequences=Split-Path $SeqFilePath  # Set the variable $LastDirSequences to the folder of the sequence choosen. This will be reused as default folder for the next manual load

  $ManuallyLoadedSeq=$SequencesTreeView.Items | Where-Object { $_.Header.Tag -like "*Manually Loaded*" }  # Check if the Sequences Tree already has a parent node "Manually Loaded"

  if ($ManuallyLoadedSeq -eq $Null) {  # The parent node "Manually Loaded" doesn't exist and is created
    $TreeViewParentItem=New-Object System.Windows.Controls.TreeViewItem
    $Header=New-Object System.Windows.Controls.HeaderedItemsControl
    $Header.Focusable=$False
    $StackPanel=New-Object System.Windows.Controls.StackPanel
    $StackPanel.Orientation="Horizontal"
    $Image=New-Object System.Windows.Controls.Image
    $Image.SetValue([System.Windows.Controls.Image]::WidthProperty, 16.0)
    $Image.SetValue([System.Windows.Controls.Image]::HeightProperty, 16.0)
    $Image.SetValue([System.Windows.Controls.Image]::MarginProperty, $(New-Object System.Windows.Thickness(0,1,2,1)))
    $Image.SetValue([System.Windows.Controls.Image]::SourceProperty, $(Set-Icon $Icon343Base64)) 
    $StackPanel.AddChild($Image)
    $Text=New-Object System.Windows.Controls.TextBlock
    $Text.Text="Manually Loaded"
    $Text.Margin="5,0"
    $StackPanel.AddChild($Text)
    $Header.AddChild($StackPanel)
    $Header.Tag="Manually Loaded"
    $TreeViewParentItem.Header=$Header
    $TreeViewParentItem.IsExpanded=($SequenceListExpanded -eq 1)
    $SequencesTreeView.Items.Add($TreeViewParentItem)  # Add the new parent node "Manually Loaded" at the bottom of the Sequence tree
    $NewSeqObjProperties=@{'SeqName'= "----- Manually Loaded -----"; 'SeqPath'=""}
    $NewSeqObj=New-Object -TypeName PSObject -Prop $NewSeqObjProperties
    $Script:SequenceList+=$NewSeqObj  # The properties of this new parent node are added in the $SequenceList array
  }

  $TreeViewParentItem=$SequencesTreeView.Items | Where-Object { $_.Header.Tag -like "*Manually Loaded*" }  # Connects to "Manually Loaded"
  $TreeViewChildItem=New-Object System.Windows.Controls.TreeViewItem
  $TreeViewChildItem.Margin="-10,0,0,0"
  $xmldata=New-Object System.Xml.XmlDocument  # Creates a new XML object
  if ($NameToUse -eq $Null) {
    $SeqName=(Split-Path $SeqFilePath -Leaf) -replace ".Sequence.xml", ""
  }
  else {
    $SeqName=$NameToUse
  }
  try {  # Search for a paramater "sequencename" in the .sequence.xml file selected
    $xmldata.Load((Get-ChildItem -Path $SeqFilePath).FullName)
    if (($xmldata.sequence | Select-Object parameter).parameter -ne $Null) {
      ($xmldata.sequence | Select-Object parameter).parameter | ForEach-Object { if ($_.Name -eq "sequencename") { $SeqName="$($_.Value)" } }
    }
  }
  catch [System.Xml.XmlException] {  # if it's not found, the name of the Sequence will be the name of the file
  }
  
  $Header=New-Object System.Windows.Controls.HeaderedItemsControl
  $Header.Focusable=$False
  $StackPanel=New-Object System.Windows.Controls.StackPanel
  $StackPanel.Orientation="Horizontal"
  $Image=New-Object System.Windows.Controls.Image
  $Image.SetValue([System.Windows.Controls.Image]::WidthProperty, 16.0)
  $Image.SetValue([System.Windows.Controls.Image]::HeightProperty, 16.0)
  $Image.SetValue([System.Windows.Controls.Image]::MarginProperty, $(New-Object System.Windows.Thickness(0,1,2,1)))
  $Image.SetValue([System.Windows.Controls.Image]::SourceProperty, $(Set-Icon $Icon345Base64)) 
  $StackPanel.AddChild($Image)
  $Text=New-Object System.Windows.Controls.TextBlock
  $Text.Text=$SeqName
  $Text.Margin="4,0,10,0"
  $StackPanel.AddChild($Text)
  $Header.Tag=$SeqName
  $Header.AddChild($StackPanel)
  $TreeViewChildItem.Header=$Header
  $TreeViewChildItem.Tag=$SeqFilePath
  $TreeViewChildItem.ToolTip=$SeqFilePath
  $TreeViewParentItem.Items.Add($TreeViewChildItem)  # Add the new node $TreeViewChildItem in the "Manually Loaded" section
  $NewSeqObjProperties=@{'SeqName'=$SeqName; 'SeqPath'=$SeqFilePath}
  $NewSeqObj=New-Object -TypeName PSObject -Prop $NewSeqObjProperties
  $Script:SequenceList+=$NewSeqObj  # The properties of this new node are added in the $SequenceList array

  Set-FavoritesFont
  $TreeViewChildItem.IsSelected=$True
  $TreeViewChildItem.BringIntoView()
  $TreeViewChildItem.Focus()
  Save-RecentList

}


$Get_SequencesState={

  # Main function started at every timer tick

  $InProgress=@()

  filter myFilter { if ($_.InProgress -eq $True) { $_ } }
  foreach ($dgis in $DataGridItemSource) {  # Loop in every items sources and recalculate the remaining objects
    $InProgress+=$dgis | myFilter 
  }

  $AllObjectsCounting=0
  $ObjectsCounting[1..$ObjectsCounting.Count] | Foreach { $AllObjectsCounting+=$_ }
  $pbStatusBar.Maximum=$AllObjectsCounting + $InProgress.Count
  $pbStatusBar.Value=$AllObjectsCounting

  $TabsInProgress=$InProgress | Select-Object -ExpandProperty Tab -Unique  # Determine the Tab ID's of the sequences in progress

  foreach ($Tab in $ObjectsTabControl.Items) {  # Loop in the Tabs to mark the running ones
    if ($Tab.Name -eq "TabPlus") { continue }  # Skip the Plus tab
    $Tab.Header=$($Tab.Header).Replace(" (>)", "")
    if ($Tab.Content.Tag -in $TabsInProgress) {
       $Tab.Header=$Tab.Header+=" (>)"
    }
  }

  Set-State

  if (@($InProgress).Count -eq 0) {  # All objects processed: stop the timer and make clean-up
    $pbStatusBar.Maximum=1
    $pbStatusBar.Value=0
    $Script:Timer.Enabled=$False
    Write-Log
    [gc]::Collect()  # Garbage Collection clean-up to free memory
    [gc]::WaitForPendingFinalizers()
    [gc]::Collect()
    if (($UseAutoSave -eq 1) -and ($AutoRun -eq $False)) {
      $Script:TimerAutoSave.Enabled=$False
      $Script:TimerAutoSave.Stop()
      Create-AutoSavePoint
      $Script:SequenceAutoSave=$False
    }
    
    if ($AutoRun -eq $True) {  # Close Hydra when AutoRun is activated   
      switch ($AutoRunExport) {
        "CSV" { Export-CreateCSV -Object $True -TaskResult $True -State $True -SequenceName $False -Header $True -Hidden $False -OnlySelection $False -OpenNotepad $False -AddTimeStamp $AutoRunExportTimeStamp -PathToSave $AutoRunExportPath}
        "HTML" { Export-ToHTML -UseStyle $True -Open $False -NameWithDate $AutoRunExportTimeStamp -PathToSave $AutoRunExportPath }
        "XLSX" { $Script:ExportCellsAsText=$True ; Export-ToExcel -NameWithDate $AutoRunExportTimeStamp -PathToSave $AutoRunExportPath }
      }
      $Form.Close()
    }

    return
  }
  
  $SequencesInProgress=$InProgress | Select-Object SequenceID -Unique  # Determine the Sequence ID's of the sequences in progress

  try {
    filter myFilter1 { if ($_.PSobject.Properties.Value -eq "Schedule") { $_ } }
    filter myFilter2 { if ($_.Schedule -ne $Null) { $_ } }
    $SequencesScheduled=($SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter1 | myFilter2).Index  # Determine potential sequences with timer
  }
  catch {
    $SequencesScheduled=@()
  }

  foreach ($SeqSched in $SequencesScheduled) {  # Loop in the sequences with a timer set
    $TimeDiff=New-TimeSpan -Start $(Get-Date) -End $SequenceSettings[$SeqSched].Schedule
    filter myFilter { if ($_.SequenceID -eq $SeqSched) { $_ } }
    $ObjectsPending=($InProgress | myFilter) 
    if ($TimeDiff.TotalSeconds -lt 0) {  # Timer expired
      $SequenceSettings[$SeqSched].Schedule=$Null
      $SequenceSettings[$SeqSched].SchedulerExpired=$True
      foreach ($Obj in $ObjectsPending) {
        $Obj.TimeRemaining=""
      }
    }
    else {
      foreach ($Obj in $ObjectsPending) {  # Check if the timers have reached their end
        if ($TimeDiff.Hours -ge 1) {  # More than one hour remaining
          $ObjTimeRemaining="{00:hh}:{00:mm}:{00:ss}" -f $TimeDiff
        }
        else {
          $ObjTimeRemaining="{00:mm}:{00:ss}" -f $TimeDiff
        }
        if ($TimeDiff.Days -eq 1) {  # One day remaining
          $ObjTimeRemaining="1 day, " + $ObjTimeRemaining
        }
        if ($TimeDiff.Days -gt 1) {  # More than one day remaining
          $ObjTimeRemaining="$($TimeDiff.Days) days, " + $ObjTimeRemaining
        }
        $Obj.TimeRemaining=$ObjTimeRemaining
      }
    }
  }

  filter myFilter { if (($_.Step -gt 0) -and ($_.SequenceID -notin $SequencesScheduled)) { $_ } }  
  $InProgressStarted=$InProgress | myFilter
  filter myFilter { if (($_.Step -eq 0) -and ($_.SequenceID -notin $SequencesScheduled)) { $_ } }  
  $InProgressNotStarted=$InProgress | myFilter

  Get_SequencesState_Running $InProgressStarted

  foreach ($SeqId in $SequencesInProgress.SequenceID) {  # Loop in all running sequences

    filter myFilter { if ($_.InProgress -eq $True -and $_.SequenceID -eq $SeqId) { $_ } }
    $ObjectsStillToProceed=@($InProgress | myFilter).Count
    if ($ObjectsStillToProceed -eq 0) {  # No objects in Progress anymore for the Sequence
      $TimeElapsed=New-TimeSpan -Start $($SequenceStats[$SeqId].StartTime) -End $($SequenceStats[$SeqId].EndTime)
      $TimeElapsedMMss="{0:D2}:{1:D2}" -f $($TimeElapsed.Hours*60 + $TimeElapsed.Minutes), $($TimeElapsed.Seconds)
      $StatResults="$($SequenceStats[$SeqId].SequenceName), $($SequenceStats[$SeqId].NbOfObjects) Objects, $TimeElapsedMMss"
      $tbStatusBar2.Text="Last run: $StatResults"
      $Now=Get-Date -Format "HH:mm:ss"
      $tbStatusBar2.Tag+="$now`: $StatResults"
      $SequenceSettings[$SeqId].RunspacePool.Close()
      $SequenceSettings[$SeqId].RunspacePool.Dispose()
    }

    if ($SequenceSettings[$SeqId].Parameter.EndMessage -ne "" -and $AutoRun -eq $False) {  # Check if EndMessage set
      filter myFilter { if ($_.InProgress -eq $True -and $_.SequenceID -eq $SeqId) { $_ } }
      $ObjectsStillToProceed=@($InProgress | myFilter).Count
      if ($ObjectsStillToProceed -eq 0) { # This sequence has finished
        MessageBox "Sequence End Message" $($SequenceSettings[$SeqId].Parameter.EndMessage) 1 1
      }
    }

  }

  foreach ($SeqId in $SequencesInProgress.SequenceID) { 

    if ($SequenceSettings[$SeqId].PreLoadInProgress -eq $True) {  # PreLoad in progress, don't start new object
      continue
    }

    if ($SequenceSettings[$SeqId].Task[$SequenceSettings[$SeqId].FirstStep].Type -eq "PreLoad") {  # A first objects for a PreLoad is identified
      $Script:SequenceSettings[$SeqId].PreLoadInProgress=$True
      $PreLoadMaster=$True
    }

    # Find the next objects to start
    filter myFilter { if ($_.SequenceID -eq $SeqId) { $_ } }
    $InProgressStartedinSeq=$InProgressStarted | myFilter
    filter myFilter { if ($_.Paused -eq $True) { $_ } }
    $ObjectsPaused=$InProgressStartedinSeq | myFilter

    if ($SequenceSettings[$SeqId].PostTaskInProgress -gt 0) {
      $Obj=($InProgressStartedinSeq | Select-Object -First 1)
      if ( ((@($ObjectsPaused).Count -eq @($InProgressStartedinSeq).Count) -and (@($ObjectsPaused).Count -gt 0)) -or ($Obj.Paused -eq $False -and $SequenceSettings[$SeqId].PostTaskInProgress -eq 2) ) {
        $Obj.Paused=$False
        $SequenceSettings[$SeqId].PostTaskInProgress=2
        $NewSharedVariable=@{} # Generate the new SharedVariable as a hash
        foreach ($o in $InProgressStartedinSeq) { $NewSharedVariable.Add($o.Objects, $o.SharedVariable) }  # Fill the hash with the SharedVariable of all objects of the sequence
        $Obj.SharedVariable=$NewSharedVariable  # Assign the new SharedVariable
        Start-SequenceStep $Obj
      }
    }
   
    filter myFilter { if ($_.SequenceID -eq $SeqId) { $_ } }
    $ObjectsToStart=($InProgressNotStarted | myFilter) | Select-Object -First $($SequenceSettings[$SeqId].Parameter.Maxthreads - @($InProgressStartedinSeq).Count + @($ObjectsPaused).Count)

    $nbPreLoad=@($SequenceSettings[$SeqId].Task | where Type -eq "PreLoad").Count

    foreach ($obj in $ObjectsToStart) {
      if ($SequenceSettings[$SeqId].PreLoadInProgress -eq $True) {  # The step is a PreLoad
        if ($PreLoadMaster -eq $True) {
          $PreLoadMaster=$False
        }
        else {  # The object is not the PreLoad Master: skip the step
          $Obj.TaskResults="PreLoad in Progress"
          $Obj.TaskResultsExport=$Obj.TaskResults
          if (!($Obj.TaskHistory)) {
            $nowStart=Get-Date -Format "HH:mm:ss"
            $Obj.TaskHistory+="Start on $nowStart"
          }
          1..$nbPreLoad | foreach {
            $Obj.TaskHistory+="PreLoad $_"
          }
          continue
        }
      }
      
      $FirstStep=$SequenceSettings[$SeqId].FirstStep
      if ($SequenceSettings[$Obj.SequenceID].Task[$FirstStep].MaxOccurrences -ne 0) {  # A maximum occurrences value has been set
        filter myFilter1 { if ($_.SequenceID -eq ($SequenceSettings[$Obj.SequenceID]).Index) { $_ } }
        filter myFilter2 { if ($_.Step -eq $FirstStep) { $_ } }
        $nb=@($DataGridItemSource[$Obj.Tab] | myFilter1 | myFilter2).Count
        if ($nb -ge $SequenceSettings[$Obj.SequenceID].Task[$FirstStep].MaxOccurrences) {
          $Obj.TaskResults="Maximum occurrences ($($SequenceSettings[$Obj.SequenceID].Task[$FirstStep].MaxOccurrences)) reached for the Step $FirstStep. Waiting..."
          $Obj.TaskResultsExport=$Obj.TaskResults
          continue
        }
      }

      $Obj.Step=$SequenceSettings[$SeqId].FirstStep  # Start from the first step selected
      $Obj.StepToString=($Obj.Step).ToString()
      Start-SequenceStep $Obj  # Start the sequence

    }

  }

  Set-State

}


function Get_SequencesState_Running($ObjectsInProgress) {

  # Get the state of objects

  foreach ($Obj in $ObjectsInProgress) {  # Loop in the objects in progress

    $TimedOut=$False
    $TimeOut=0

    if ($Obj.Step -in $Obj.StepsToSkip) {  # The step has to be skipped
      Get-IfPreLoad $Obj
      if ($Obj.Step -eq $Obj.nbTotalSteps) {  # Last step reached
        $Obj.InProgress=$False
        $Obj.IsEnabled=$True
        $Obj.Step=0
        $Obj.StepToString="0"
        $Obj.State="OK"  # Change running state to OK
        if ($Obj.TasksTimedOut) {
          $Obj.State="OK [ ! $($Obj.TasksTimedOut -join ",") ]"
        }
        if ($Obj.ColorTemp -ne $Null) { $Obj.Color=$Obj.ColorTemp } else { $Obj.Color=$Colors.Get_Item("OK") }
        $Obj.SharedVariable=$Null
        $Obj.IsChecked=$False
        $Obj.TaskResults=$Obj.LastTaskResults  # Display the last Task Results
        $Obj.TaskResultsExport=$Obj.TaskResults
        $Script:ObjectsCounting[$Obj.Tab]++
      }
      else {
        if ($SequenceSettings[$Obj.SequenceID].Task[$Obj.Step+1].MaxOccurrences -ne 0) {  # A maximum occurrences value has been set
          filter myFilter1 { if ($_.SequenceID -eq ($SequenceSettings[$Obj.SequenceID]).Index) { $_ } }
          filter myFilter2 { if ($_.Step -eq $Obj.Step+1) { $_ } }
          $nb=@($DataGridItemSource[$Obj.Tab] | myFilter1 | myFilter2).Count
          if ($nb -ge $SequenceSettings[$Obj.SequenceID].Task[$Obj.Step+1].MaxOccurrences) {
            $Obj.TaskResults="Maximum occurrences ($($SequenceSettings[$Obj.SequenceID].Task[$Obj.Step+1].MaxOccurrences)) reached for the Step $($Obj.Step+1). Waiting..."
            $Obj.TaskResultsExport=$Obj.TaskResults
            $Obj.Paused=$True
            continue
          }
        }

        $Obj.Paused=$False
        $Obj.Step++
        $Obj.StepToString=$Obj.Step.ToString()
        $Script:LiveStatus[$Obj.Objects]=$Null
        Start-SequenceStep $Obj
      }
      continue
    }

    if ($SequenceSettings[$Obj.SequenceID].Parameter.TimeOut -gt 0) { $TimeOut=$SequenceSettings[$Obj.SequenceID].Parameter.TimeOut }
    if ($SequenceSettings[$Obj.SequenceID].Task[$Obj.Step].TimeOut -gt 0) { $TimeOut=$SequenceSettings[$Obj.SequenceID].Task[$Obj.Step].TimeOut }
    
    if ($TimeOut -gt 0 -and (New-TimeSpan $Obj.TaskStartedAt $(Get-Date)).TotalSeconds -gt $TimeOut) {  # Timed out
      $Obj.Runspace.PowerShell.Dispose()
      $TimedOut=$True
    }
    else {
      try {
        if ($Obj.Runspace.Runspace.IsCompleted -eq $False) {  # The Runspace of the Object is not finishes: skip
          if ($SequenceSettings[$Obj.SequenceID].Parameter.UseLiveStatus -eq $True) {
            if ($LiveStatus[$Obj.Objects] -ne $Null) {
              $Obj.TaskResults=$LiveStatus[$Obj.Objects]
            }
          }
          continue
        }
      }
      catch {  # The state of the Runspace is lost
        $Obj.InProgress=$False
        $Obj.IsEnabled=$True
        $Obj.TaskResults="Runspace Error"
        $Obj.TaskResultsExport=$Obj.TaskResults
        $Obj.State="ERROR at step $($Obj.Step)"
        $Obj.Historic+="  Step $($Obj.Step) - " + "ERROR - Runspace Error"
        $Obj.Historic+="End on $(Get-Date -Format "HH:mm:ss")"
        $Obj.TaskHistory+="Step $($Obj.Step) - " + "ERROR - Runspace Error"
        $Obj.IsChecked=$False
        $Obj.SharedVariable=$Null
        $Obj.Color=$Colors.Get_Item("STOP")
        if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
          Write-DebugLog "$($Obj.Objects);ERROR;Step $($Obj.Step);Runspace Error" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
        }
        $Obj.Step=0
        $Obj.StepToString="0"
        $Script:SequenceLog[$Obj.SequenceID]+=$(Get-Date -Format "dd.MM.yyyy") + " ; " + ($Obj.Historic -join " ;")
        $Script:SequenceStats[$Obj.SequenceID].Error++
        $Script:SequenceStats[$Obj.SequenceID].NbOfObjects++
        if ((Get-Date) -gt $SequenceStats[$Obj.SequenceID].EndTime) { $Script:SequenceStats[$Obj.SequenceID].EndTime=Get-Date }
        $Script:ObjectsCounting[$Obj.Tab]++
        continue
      }
    }

    if ($SequenceSettings[$Obj.SequenceID].Task[$Obj.Step].Type -eq "posttask") {
      if (($Obj.Paused -eq $False) -and ($SequenceSettings[$Obj.SequenceID].PostTaskInProgress -le 1)) {
        $Obj.Paused=$True
        $Obj.TaskResults+=" (Waiting for PostTask)"
        $SequenceSettings[$Obj.SequenceID].PostTaskInProgress=1
      }
      if (($SequenceSettings[$Obj.SequenceID].PostTaskInProgress -le 1) -or ($Obj.Paused -eq $True)){       
        continue 
      }
    }

    if ($Obj.Paused -eq $False) {
      if ($SequenceSettings[$Obj.SequenceID].PostTaskInProgress -eq 2) {  # Keep the Temp color of the PostTask object
        $TempColor=$Obj.ColorTemp
      }
      Get-ObjectReturnedState -Obj $Obj -TimedOut $TimedOut  # Get the state returned by the object
      if ($SequenceSettings[$Obj.SequenceID].PostTaskInProgress -eq 2) {
        $LastCheckStep=(((1..$($SequenceSettings[$Obj.SequenceID].Task.Count-1)) | Where-Object { $_ -notin $Obj.StepsToSkip }) | Measure-Object -Maximum).Maximum  # Calculate the last PostTask
        if ($TempColor -ne $Null) {  # Operations if a custom color has been defined in previous tasks
          $Obj.ColorTemp=$TempColor
          if ($LastCheckStep -eq $Obj.Step) { $Obj.Color=$TempColor }
        } 
        else { 
          if ($LastCheckStep -eq $Obj.Step) { $Obj.Color=$Colors.Get_Item("OK") }
        }
        if ($LastCheckStep -eq $Obj.Step) {  # Last Step reach: force the end in case some further PostTasks are unchecked and shouldn't be executed
          $Obj.NextStep=0
          $Obj.Step=$Obj.nbTotalSteps
        }
      }
    }

    if ($Obj.InProgress -eq $False) {  # The object is not in progress anymore (STOP, BREAK, ERROR)
      continue
    }
    if (($Obj.Step -eq $Obj.nbTotalSteps) -and ($Obj.NextStep -eq 0) ){  # Last step reached, and no GOTO

      $Obj.InProgress=$False
      $Obj.IsEnabled=$True
      $Obj.Step=0
      $Obj.StepToString="0"

      if ($Obj.TasksTimedOut) {
        $Obj.State="OK [ ! $($Obj.TasksTimedOut -join ",") ]"
      }

      if ($SequenceSettings[$Obj.SequenceID].PostTaskInProgress -eq 2) {  # A PostTask was running: set all other objects paused in OK
        $SequenceSettings[$Obj.SequenceID].PostTaskInProgress=0
        foreach ($OtherObj in $ObjectsInProgress) {
          if ($Obj.SequenceID -ne $OtherObj.SequenceID) {  # Ignore other sequence
            continue
          }
          if ($obj -eq $OtherObj) { continue }
          $OtherObj.InProgress=$False
          $OtherObj.IsEnabled=$True
          $OtherObj.TaskResults=$OtherObj.LastTaskResults
          $OtherObj.TaskResultsExport=$OtherObj.TaskResults
          if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True -and $OtherObj.Step -ne 0) {
            Write-DebugLog "$($OtherObj.Objects);OK;Step $($OtherObj.Step);$($OtherObj.TaskResultsExport)" $SequenceSettings[$OtherObj.SequenceID].Parameter.SequenceLog
          }
          $OtherObj.Step=0
          $OtherObj.StepToString="0"
          $OtherObj.IsChecked=$False
          $OtherObj.SharedVariable=$Null
          $OtherObj.State="OK"
          if ($OtherObj.TasksTimedOut) {
            $OtherObj.State="OK [ ! $($Obj.TasksTimedOut -join ",") ]"
          }
          if ($OtherObj.ColorTemp -ne $Null) { $OtherObj.Color=$OtherObj.ColorTemp } else { $OtherObj.Color=$Colors.Get_Item("OK") }
          $OtherObj.Historic+="End on $(Get-Date -Format "HH:mm:ss")"
          $Script:SequenceLog[$Obj.SequenceID]+=$(Get-Date -Format "dd.MM.yyyy") + " ; " + ($OtherObj.Historic -join " ;")
          $Script:SequenceStats[$Obj.SequenceID].OK++
          $Script:SequenceStats[$Obj.SequenceID].NbOfObjects++
          if ((Get-Date) -gt $SequenceStats[$Obj.SequenceID].EndTime) { $Script:SequenceStats[$Obj.SequenceID].EndTime=Get-Date }
          $Script:ObjectsCounting[$OtherObj.Tab]++
        }
        return
      }

    }
    else {  # Start the next one
    
      if ($Obj.NextStep -ne 0) {  # A GOTO has been detected
        $NextStep=$Obj.NextStep
      }
      else {
        $NextStep=$Obj.Step+1
      }
      if ($SequenceSettings[$Obj.SequenceID].Task[$NextStep].MaxOccurrences -ne 0) {  # A maximum occurrences value has been set
        filter myFilter1 { if ($_.SequenceID -eq ($SequenceSettings[$Obj.SequenceID]).Index) { $_ } }
        filter myFilter2 { if ($_.Step -eq $NextStep) { $_ } }
        $nb=@($DataGridItemSource[$Obj.Tab] | myFilter1 | myFilter2).Count
        if ($nb -ge $SequenceSettings[$Obj.SequenceID].Task[$NextStep].MaxOccurrences) {
          $Obj.TaskResults="Maximum occurrences ($($SequenceSettings[$Obj.SequenceID].Task[$NextStep].MaxOccurrences)) reached for the Step $NextStep. Waiting..."
          $Obj.TaskResultsExport=$Obj.TaskResults
          $Obj.Paused=$True
          continue
        }
      }
     
      $Obj.Paused=$False
      if ($Obj.NextStep -ne 0) {  # A GOTO has been detected
        $Obj.Step=$Obj.NextStep
      }
      else {  # Just go to the next step
        $Obj.Step++
      }
      $Obj.NextStep=0
      $Obj.StepToString=$Obj.Step.ToString()
      if ($SequenceSettings[$Obj.SequenceID].Task[$Obj.Step].Type -ne "PostTask") {
        $Script:LiveStatus[$Obj.Objects]=$Null
        Start-SequenceStep $Obj
      }

    }

  }

}


function Get-Tabs($FileToImport="") {

  # Import Tab(s) from a .tabs file

  if ($FileToImport -eq "") {
    $FileToImport=Get-FileButton "Hydra Tabs (*.tabs)|*.tabs|All files (*.*)|*.*" $LastDirTabs  # Get the file to open
    if (($FileToImport -eq "") -or ($FileToImport -eq $Null)) { return }
  }
  $Script:LastDirTabs=Split-Path $FileToImport  # Save the last directory for registry user's settings on close

  [System.Windows.Input.Mouse]::OverrideCursor=[System.Windows.Input.Cursors]::Wait

  if ((Get-Content $FileToImport)[0] -like "*Header*") {  # Old Tab format

    foreach ($Line in (Get-Content $FileToImport)) {  # Parse the file

      if ($Line -like "*Hydra Tabs*") { continue }  # Skip the header
      $LineSplit=$Line -split ";"  # Read and set the different Tab attributes
      if (@($LineSplit).Count -lt 4) { continue }  # Wrong format
      $TabName=$LineSplit[0]
      $TabColor1=$LineSplit[1]
      $TabColor2=$LineSplit[2]  # Useless parameter: Compatibility to Hydra5 only
      $Objects=$LineSplit[3..$($LineSplit.Count-1)]

      . $CreateANewTab $True $False

      if ($TabColor1 -ne "Default") {
        $ObjectsTabControl.SelectedItem.Background=$TabColor1
      }
      $ObjectsTabControl.SelectedItem.Header=$TabName

      foreach ($item in $Objects) {  # Only add non-empty objects
        if ($item -ne "") { 
          Set-ObjectSettings $item
        }
      }

     . $TabItemLoaded  # Force the removing of the dummy placeholder

    }

  }
  
  else {  # New Tab format

    $AllTabs=Import-Clixml $FileToImport

    foreach ($TabToImport in $AllTabs) {

      . $CreateANewTab $True $False
      if ($TabToImport.TabColor -ne "Default") {
        $ObjectsTabControl.SelectedItem.Background=$TabToImport.TabColor
      }
      $ObjectsTabControl.SelectedItem.Header=$TabToImport.TabText

      foreach ($item in $TabToImport.Objects) {  # Only add non-empty objects
        Set-ObjectSettings $item.Objects -AddParams $item.AddParams
      }

      . $TabItemLoaded  # Force the removing of the dummy placeholder

      filter myFilter { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
      $MaxAddParams=0
      $ObjectsTabControl.SelectedItem.Content.Items | myFilter | ForEach-Object { if (@($_.AddParams).Count -gt $MaxAddParams) { $MaxAddParams=@($_.AddParams).Count } }
      if ($MaxAddParams -gt 0) { Add-GridColumn $ObjectsTabControl.SelectedItem $MaxAddParams }

    }
  }

  Set-State
  [System.Windows.Input.Mouse]::OverrideCursor=$Null

}


function Import-AutoSave($AutoSave, $AutoSaveTabs) {

  # Import an AutoSave to the grid

  if ($Timer.Enabled -eq $True) {
    MessageBox "Restore Point" "Some sequences are currently running.`r`nImpossible to replace the current tabs." 3 1
    return
  }
  
  [System.Windows.Input.Mouse]::OverrideCursor=[System.Windows.Input.Cursors]::Wait
  $Script:TabMoving=$True

  # Remove the current tabs
  for ($i=$ObjectsTabControl.Items.Count-1; $i -ge 0; $i--) {  # Loop to all tabs and remove them
    $Tab=$ObjectsTabControl.Items[$i]
    if ($Tab.Name -eq "TabPlus") { continue }  # Skip the Plus tab
    $ObjectsTabControl.Items.Remove($Tab)
  }

  $i=0
  $Version=""
  $AutoSaveVersion=($AutoSaveTabs -split ";")[0]

  foreach ($Tab in $($AutoSaveTabs -split ";")) {  # 
    if ($i -eq 0) { $i++ ; Continue }
    . $CreateANewTab $True $False

    $AutoSaveVersionTab="$TempEnv\.Hydra7AutoSave\$AutoSaveVersion\" + "AutoSave{0:D2}" -f $i
    $SnapshotToImport=[System.Management.Automation.PSSerializer]::Deserialize($(Get-Content $AutoSaveVersionTab))
    foreach ($Obj in $SnapshotToImport) {  # Loop to get all objects
      try {
        Set-ObjectSettings $Obj.Objects -TaskResult $Obj.TaskResults -TaskResultExport $Obj.TaskResultsExport -State $Obj.State -SequenceName $Obj.SequenceName -Step $Obj.Step -Checked $Obj.IsChecked -Color $Obj.Color -CellFontFormated $Obj.CellFontFormated -CellFontFamily $Obj.CellFontFamily -CellFontColor $Obj.CellFontColor -CellFontSize $Obj.CellFontSize -CellFontStyle $Obj.CellFontStyle -CellFontWeight $Obj.CellFontWeight -Hidden $Obj.Hidden -AddParams $Obj.AddParams  # Create the objects in the grid
      }
      catch {}
    } 
    $ObjectsTabControl.SelectedItem.Content.ItemsSource=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag]
    $ObjectsTabControl.SelectedItem.Header=$Tab.Replace(" (>)", "")
    $ObjectsTabControl.SelectedItem.Content.ItemsSource=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag]
    $Script:TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]=Get-ItemsMaxAddParams $ObjectsTabControl.SelectedItem.Tag
    Add-GridColumn $ObjectsTabControl.SelectedItem $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]
    $i++
    . $TabItemLoaded  # Force the removing of the dummy placeholder
  } 

  $Script:TabMoving=$False
  [System.Windows.Input.Mouse]::OverrideCursor=$Null

}


function Import-Bundle($FileToImport=$Null) {

  # Import a Bundle

  if ($FileToImport -eq $Null) {
    $FileToImport=Get-FileButton "Hydra Bundle (*.bundle)|*.bundle|All files (*.*)|*.*" $LastDirBundles
    if (($FileToImport -eq "") -or ($FileToImport -eq $Null)) { return }
  }
  $Script:LastDirBundles=Split-Path $FileToImport

  $BundleToImport=[System.Management.Automation.PSSerializer]::Deserialize($(Get-Content $FileToImport))

  $BundleVersion=[bool]($BundleToImport.PSobject.Properties.name -match "BundleVersion")
  if ($BundleVersion -eq $False) {
    MessageBox "Bundle" "This version of Hydra doesn't support this Bundle format." 3 1
    return
  }

  # Check if the Bundle name already exists

  $CurrentBundles=@()
  foreach ($dgis in $DataGridItemSource) {  # Get the name of all Bundles in use
    filter myFilter { if ($_.Bundle -eq $True) { $_ } }
    $CurrentBundles+=$dgis | myFilter | Select-Object -ExpandProperty BundleName -Unique 
  }

  if ($BundleToImport.BundleName -in $CurrentBundles) {  # Check if the name is already given to another bundle
    MessageBox "Bundle Name" "The Bundle Name '$($BundleToImport.BundleName)' is already assigned." 3 1
    return
  }

  if ([string]::IsNullOrEmpty($BundleToImport.Sequence.ImportModule)) {
    $BundleToImport.Sequence.ImportModule=$Null
  }

  $Script:AllBundle+=$BundleToImport.BundleName
  $LastUniqueID=$UniqueID

  foreach ($Obj in $BundleToImport.Objects) {  # Loop to get all objects
    try {
      Set-ObjectSettings $Obj.Objects.ToString() -AddParams $Obj.AddParams -Checked $False  # Create the objects in the grid
    }
    catch {}
  }

  # Load the sequence and assign it

  $Script:SequenceLoaded=$BundleToImport.Sequence

  filter myFilter { if ($_.UniqueID -gt $LastUniqueID) { $_ } }
  $ObjToAssign=$ObjectsTabControl.SelectedItem.Content.ItemsSource | myFilter
  
  $Script:BundleToSet=$BundleToImport.BundleName
  $ThreadTextBox.Text=$SequenceLoaded.Parameter.Maxthreads

  Set-AssignSequenceToBundle $SequenceLoaded.Schedule $ObjToAssign
  Check-Bundle

  Set-DisplaySequence $LastSequenceIndex $False
  Set-State

  if ($UseClassicMenu -eq "False") {
    RibbonSetBundle
  }
  else {
    ClassicMenuSetBundle
  }

  $Script:NewSequenceLoaded=$False
  $Script:SequenceLoaded=$Null

  filter myFilter { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
  $MaxAddParams=0
  $ObjectsTabControl.SelectedItem.Content.Items | myFilter | ForEach-Object { if (@($_.AddParams).Count -gt $MaxAddParams) { $MaxAddParams=@($_.AddParams).Count } }
  if ($MaxAddParams -gt 0) { Add-GridColumn $ObjectsTabControl.SelectedItem $MaxAddParams }

}


function Import-Snapshot($SnapshotFolder, $SnapshotVersion, $SnapshotTabs) {

  # Import a snapshot to the grid
  
  $SnapshotFolderFull=Join-Path $SnapshotsPath $SnapshotFolder
  $i=0
  foreach ($tab in $($SnapshotTabs -split ";")) {  # Check the consistency of the snapshot
    if ($i -eq 0) { $i++ ; Continue }
    $SnapshotVersionTab=(Join-Path $SnapshotFolderFull $SnapshotVersion) + "{0:D2}" -f $i
    if (!(Test-Path $SnapshotVersionTab)) {
      MessageBox "Snapshot" "Unable to read part of the Snapshot: it may be corrupt." 3 1
      return
    }
    $i++
  }

  $NewTabs=(MessageBox "Snapshot" "Do you want to load the snapshot in new Tabs ?`r`n`r`nYes: This will create new tabs`r`nNo: This will clear all the current tabs" 4 2)

  if (($NewTabs -eq "No") -and ($Timer.Enabled -eq $True)) {
    MessageBox "Snapshot" "Some sequences are currently running.`r`nImpossible to replace the current tabs." 3 1
    return
  }

  [System.Windows.Input.Mouse]::OverrideCursor=[System.Windows.Input.Cursors]::Wait
  $Script:TabMoving=$True

  if ($NewTabs -eq "No") {  # No new tabs
    for ($i=$ObjectsTabControl.Items.Count-1; $i -ge 0; $i--) {  # Loop to all tabs and remove them
      $Tab=$ObjectsTabControl.Items[$i]
      if ($Tab.Name -eq "TabPlus") { continue }  # Skip the Plus tab
      $ObjectsTabControl.Items.Remove($Tab)
    }
  }

  $i=0
  $Version=""
  foreach ($Tab in $($SnapshotTabs -split ";")) {  # 
    if ($i -eq 0) { $i++ ; $Version=([datetime]::ParseExact($Tab,"yyyyMMddHHmmss",[System.Globalization.CultureInfo]::InvariantCulture)).ToString("dd/MM/yyyy, HH:mm:ss");  Continue }
    . $CreateANewTab $True $False
    $ObjectsTabControl.SelectedItem.Header="$Tab [$version]"

    $SnapshotVersionTab=(Join-Path $SnapshotFolderFull $SnapshotVersion) + "{0:D2}" -f $i
    $SnapshotToImport=[System.Management.Automation.PSSerializer]::Deserialize($(Get-Content $SnapshotVersionTab))
    foreach ($Obj in $SnapshotToImport) {  # Loop to get all objects
      try {
        Set-ObjectSettings $Obj.Objects -TaskResult $Obj.TaskResults -TaskResultExport $Obj.TaskResultsExport -State $Obj.State -SequenceName $Obj.SequenceName -Step $Obj.Step -Checked $Obj.IsChecked -Color $Obj.Color -CellFontFormated $Obj.CellFontFormated -CellFontFamily $Obj.CellFontFamily -CellFontColor $Obj.CellFontColor -CellFontSize $Obj.CellFontSize -CellFontStyle $Obj.CellFontStyle -CellFontWeight $Obj.CellFontWeight -Hidden $Obj.Hidden -AddParams $Obj.AddParams # Create the objects in the grid
      }
      catch {}
    }
    $ObjectsTabControl.SelectedItem.Content.ItemsSource=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag]
    $Script:TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]=Get-ItemsMaxAddParams $ObjectsTabControl.SelectedItem.Tag
    Add-GridColumn $ObjectsTabControl.SelectedItem $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]
    $i++
    . $TabItemLoaded  # Force the removing of the dummy placeholder
  }
  
  $Script:TabMoving=$False

  [System.Windows.Input.Mouse]::OverrideCursor=$Null

}


function Load-Sequence($SeqName, $FileSeqPath, $NewSequenceLoad=$False) {

  # Load a Sequence file

  $SequenceStepsStackPanel.Children.Clear()
  $Script:SequenceSelectedOnError=$True

  if ($AutoRun -eq $False) {
    if ($SequencesTreeView.SelectedItem.Header -eq "Filtered") {  # The Filtered item has been clicked
      return
    }
  }

  if ($NewSequenceLoad -eq $True) {
    $Script:NewSequenceLoaded=$True
  }

  try {  # Check the access to the Sequence File
    if (!(Test-Path $FileSeqPath -PathType Leaf -ErrorAction Stop)) {  # The file passed as argument is not existing
      Create-LabelInSequence "$SeqName" "Red" "Italic" 15
      Create-LabelInSequence "  Missing: $FileSeqPath" "Red" "Italic" 10
      return
    }
  }
  catch {  # Error accessing the path
    Create-LabelInSequence "$SeqName" "Red" "Italic" 15
    Create-LabelInSequence "  Error accessing the sequence file" "Red" "Italic" 10
    return
  }

  try {  # Load the file as an XML one
    $xmldata=New-Object System.Xml.XmlDocument
    $xmldata.Load((Get-ChildItem -Path $FileSeqPath -ErrorAction Stop).FullName)
  }
  catch [System.Xml.XmlException] {  # XML errors detected
    Create-LabelInSequence "$SeqName" "Red" "Italic" 15
    Create-LabelInSequence "  Error: XML parse error in $FileSeqPath" "Red" "Italic" 10
    if ($AutoRun -eq $True) {
      MessageBox "AutoRun" "AutoRun Error: XML parse error in $FileSeqPath"
      try {
        Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -Force -ErrorAction SilentlyContinue | Out-Null
      }
      catch {}
      $Form.Close()
    }
    return
  }

  $FileSeqParentPath=Split-Path (Resolve-Path $FileSeqPath) -Parent  # Get the path of the sequence file

  try {  # Search for a "sequence" and a "task" tag in the file selected
    if (Get-Member -inputobject $xmldata -name "sequence" -Membertype Properties) {
      if ((Get-Member -inputobject $xmldata -name "task" -Membertype Properties) -eq $False) {  # Format of the xml file not correct
        Create-LabelInSequence "$FileSeqPath" "Red" "Italic" 15
        Create-LabelInSequence "  Invalid format" "Red" "Italic" 12
        if ($AutoRun -eq $True) {
          MessageBox "AutoRun" "AutoRun Error: Invalid format of $FileSeqPath"
          try {
            Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -Force -ErrorAction SilentlyContinue | Out-Null
          }
          catch {}
        }
        return
      }
    }
    else {  # Format of the xml file not correct
      Create-LabelInSequence "$FileSeqPath" "Red" "Italic" 15
      Create-LabelInSequence "  Invalid format" "Red" "Italic" 12
      if ($AutoRun -eq $True) {
        MessageBox "AutoRun" "AutoRun Error: Invalid format of $FileSeqPath"
        try {
          Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -Force -ErrorAction SilentlyContinue | Out-Null
        }
        catch {}
        $Form.Close()
      }
      return
    }
  }
  catch [System.Xml.XmlException] {
    Create-LabelInSequence "$FileSeqPath" "Red" "Italic" 15
    Create-LabelInSequence "  Invalid format" "Red" "Italic" 12
    if ($AutoRun -eq $True) {
      MessageBox "AutoRun" "AutoRun Error: Invalid format of $FileSeqPath"
      try {
        Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -Force -ErrorAction SilentlyContinue | Out-Null
      }
      catch {}
      $Form.Close()
    }
    return
  }

  if ($AutoRun -eq $False) {
    $XMLObjectsAutoStart=Load-Sequence_Objects $xmldata $SeqName $FileSeqParentPath
  }
  else {
    $XMLObjectsAutoStart=$True
  }

  $Parameters=Load-Sequence_Parameters $xmldata $SeqName
  Create-LabelInSequence $($Parameters.SequenceName) -FontSize 15

  $ImportModules=Load-Sequence_Modules $xmldata
  $Tasks=Load-Sequence_Tasks $xmldata $FileSeqParentPath $FileSeqPath
  $Documents=Load-Sequence_Document $xmldata $FileSeqParentPath
  
  if ($AutoRun -eq $False) {
    $Variables=Load-Sequence_Variables $xmldata
  }
  else {
    $Variables=@()
  }

  $ErrorFound=$Tasks[1]  # An error was returned for Preload or Task commands

  if ($HydraVersion -lt $Parameters.MinimumVersion) {
    MessageBox "Hydra Version" "This Sequence needs Hydra $($Parameters.MinimumVersion) or higher to run correctly.`r`n`r`nSome options or functionalities may be missing or work differently as expected." 2 1
  }

  if (!($ErrorFound)) {  # Set the settings to $SequenceLoaded
    $Script:SequenceSelectedOnError=$False
    $Script:SequenceLoaded=[PSObject]@{  
      Name=$SeqName
      SequencePath=$(Split-Path $FileSeqPath -Parent)
      SequenceFullPath=$FileSeqParentPath
      Index=0
      Parameter=$Parameters
      ImportModule=$ImportModules
      Task=$Tasks[0]
      PreLoadInProgress=$False
      PostTaskInProgress=0
      Variable=$Variables
      Documents=$Documents
    }

    if (($XMLObjectsAutoStart -eq $True) -or ($AutoRun -eq $True)) {  # Force a start of the sequence
      Start-Sequence
    }
  }
  else {
    $Script:SequenceLoaded=$Null
    if ($AutoRun -eq $True) {
      MessageBox "AutoRun" "AutoRun Error: Error loading $FileSeqPath"
      try {
        Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -Force -ErrorAction SilentlyContinue | Out-Null
      }
      catch {}
      $Form.Close()
    }
  }

  if ($NewSequenceLoad -eq $True) {
    Set-StartButtonState
  }
  
  if ($Parameters.ObjectAdditionalParams -ne 0) {
    Add-GridColumn $ObjectsTabControl.SelectedItem $Parameters.ObjectAdditionalParams
    if ($Parameters.ObjectAdditionalParams -gt $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]) {
      $Script:TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]=$Parameters.ObjectAdditionalParams
    }
    Add-ItemsAdditionalParams $ObjectsTabControl.SelectedItem.Tag $Parameters.ObjectAdditionalParams
  }

}


function Load-Sequence_Document($xmldata, $FileSeqParentPath) {

  # Load the Document sections from a sequence file

  $XMLSeqDoc=($xmldata.sequence | Select-Object document).document
  $Documents=@()  # Array for the documehts
  foreach ($XMLDocument in $XMLSeqDoc) {  # Loop into the "document" found
    $SequencePath=$FileSeqParentPath
    $doclabel=$null
    $docpath=$null
    $docopenwith=$null
    if ([bool]($XMLDocument.PSobject.Properties.Name -eq "label")) { $doclabel=$($XMLDocument.label) }
    if ([bool]($XMLDocument.PSobject.Properties.Name -eq "path")) { $docpath=$ExecutionContext.InvokeCommand.ExpandString($XMLDocument.path) }
    if ([bool]($XMLDocument.PSobject.Properties.Name -eq "openwith")) { $docopenwith=$($XMLDocument.openwith) }
    if ($doclabel -eq $null -or $docpath -eq $null) { continue }  # name or/and path missing
    $Documents+=[PSObject]@{  # Create a new module object with its type and name
      Label=$doclabel
      Path=$docpath
      OpenWith=$docopenwith
    }
  }

  return $Documents

}


function Load-Sequence_Modules($xmldata) {

  # Load the ImportModule sections from a sequence file

  $XMLSeqMod=($xmldata.sequence | Select-Object importmodule).importmodule
  $ImportModules=@()  # Array for the modules
  foreach ($XMLModule in $XMLSeqMod) {  # Loop into the "importmodule" found
    if (($XMLModule.type -eq "ImportPSSnapIn") -or ($XMLModule.type -eq "ImportPSModulesFromPath") -or ($XMLModule.type -eq "ImportPSModule")) {  # The module type is known
      $ImportModules+=[PSObject]@{  # Create a new module object with its type and name
        Type=$XMLModule.type
        Name=$XMLModule.name
        Version=if ([bool]($XMLModule.PSobject.Properties.Name -match "version")) { $XMLModule.Version } else { 0 }
        CopyLocally=if (([bool]($XMLModule.PSobject.Properties.Name -match "copylocally"))) { $XMLModule.CopyLocally -eq "True" } else { $False }
      }
    }
  }

  return $ImportModules

}


function Load-Sequence_Objects($xmldata, $SeqName, $FileSeqParentPath) {

  # Load the Object sections from a sequence file

  $ObjectsCreated=$False

  $XMLSeqObj=($xmldata.sequence | Select-Object object).object
  if ($XMLSeqObj -eq $null) {  # No Object section found
    return $False
  }

  if (@($XMLSeqObj).Count -ne 1) {
    MessageBox $SeqName "Only one <object> tab is allowed in a sequence.`r`n`r`nNo object wil be autocreated." 3 1
    return $false
  }

  foreach ($XMLobject in $XMLSeqObj) {  # loop in the "oject" found
    if ([bool]($XMLobject.PSobject.Properties.Name -contains "action")) {

      $NewTab=$False
      $AutoStart=$False
      if ($XMLobject.action -eq "autocreate") {  # Autocreate objects
        if ([bool]($XMLobject.PSobject.Properties.Name -contains "newtab")) { $NewTab=($XMLobject.newtab -eq "Yes") }
        if ([bool]($XMLobject.PSobject.Properties.Name -contains "autostart")) { $AutoStart=($XMLobject.autostart -eq "Yes") }
        if ([bool]($XMLobject.PSobject.Properties.Name -contains "list")) {
          if ([string]::IsNullOrEmpty($XMLobject.list)) {
            MessageBox $SeqName "The list of objects is empty" 2 1
            continue
          }
          if (Test-Path $($ExecutionContext.InvokeCommand.ExpandString($XMLobject.list)) -ErrorAction SilentlyContinue) {
            $XMLobjectList=$(Get-Content $($ExecutionContext.InvokeCommand.ExpandString($XMLobject.list))) -join ","
          }
          elseif (Test-Path $(Join-Path -Path $FileSeqParentPath -ChildPath $($ExecutionContext.InvokeCommand.ExpandString($XMLobject.list))) -ErrorAction SilentlyContinue) {
            $XMLobjectList=$(Get-Content $(Join-Path -Path $FileSeqParentPath -ChildPath $($ExecutionContext.InvokeCommand.ExpandString($XMLobject.list)))) -join ","
          }
          else {
            $XMLobjectList=$XMLobject.list
          }
          if ([string]::IsNullOrEmpty($XMLobjectList)) {
            MessageBox $SeqName "The list of objects is empty" 2 1
            continue
          }
        }
        else {  # No List defined
          continue
        }
        if ([bool]($XMLobject.PSobject.Properties.Name -contains "confirmation")) {
          $Confirmation=$XMLobject.confirmation
        }
        else {
          $Confirmation="default"
        }
        switch ($Confirmation) {
          "combobox" { $Script:SequenceFullPath=$FileSeqParentPath ; $List=Read-ComboBoxDialog $SeqName "Which object do you want to create" $XMLobjectList ; if ($List -eq "") { $List=$Null } ; break }
          "checkbox" { $Script:SequenceFullPath=$FileSeqParentPath ; $List=Read-MultiCheckboxList $SeqName "Which objects do you want to create" $XMLobjectList $true ; if (($List -eq "NONE") -or ($List -eq "")) { $List=$Null } ; break }
          "none" { $List=(($XMLobjectList -replace "\\,", "{COMMA}") -split ",") -replace "{COMMA}", "," ; break 
          }
          default { 
            $CreateObjects=MessageBox $SeqName "Do you want to create the objects:`r`n`r`n$XMLobjectList" 4 2
            if ($CreateObjects -eq "No") { $List=$Null } else { $List=$XMLobjectList }
          }
        }
        if ($List -ne $null) {
          if ($newTab) { . $CreateANewTab }
          foreach ($obj in $List) {
            $ObjectsCreated=$True
            Set-ObjectSettings $obj
          }
        }
      }
    }
  }

  return ($ObjectsCreated -and $AutoStart)

}


function Load-Sequence_Parameters($xmldata, $SeqName) {

  # Load the Parameter sections from a sequence file

  $ThreadTextBox.Text=$DefaultThreads
  $MaxObj=0 
  $DisplayWarning=$False
  $SecurityCode=$False
  $MessageBox=""
  $EndMessageBox=""
  $CustomHeader=""
  $CustomHeaderDelimiter=","
  $SendMail=$False
  $MailServer=""
  $MailServerPort=""
  $MailFrom=""
  $MailTo=""
  $MailUseSSL=""
  $MailUsername=""
  $MailPassword=""
  $MailSSLIgnoreErrors=""
  $MaxThreads=$DefaultThreads
  $UseObjectsList=$False
  $SeqAutoSave=$False
  $SeqAutoSaveInterval=1
  $UseLiveStatus=$False
  $UseTranscript=$False
  $Timeout=0
  $ContinueAfterTimeout=$False
  $MinimumVersion="1.0"
  $SequenceLog=""
  $SequenceLogTimestamp=$False
  $SequenceDebug=$False
  $ObjectAdditionalParams=0
  $ObjectAsParam=$False
  $AlwaysQueryVariables=$False

  # Get all the variables with a node name "parameter"
  $Parameters=New-Object PSObject
  $XMLSeqParam=($xmldata.sequence | Select-Object parameter).parameter
  foreach ($XMLParam in $XMLSeqParam) {  # Loop into the "parameters" found
    switch ($XMLParam.name) {  # If the parameter found is known, set its value
      "sequencename" { $SeqName=$XMLParam.value }
      "minimumversion" { $MinimumVersion=$XMLParam.value }
      "warning" { if ($XMLParam.value -eq "yes") { $DisplayWarning=$True } }
      "securitycode" { $SecurityCode=$XMLParam.value }
      "message" { $MessageBox=$XMLParam.value -replace "\\n", "`r`n" }
      "endmessage" { $EndMessageBox=$XMLParam.value -replace "\\n", "`r`n" }
      "maxthreads" { $ThreadTextBox.Text=$XMLParam.value ; $MaxThreads=$XMLParam.value }
      "maxobjects" { $MaxObj=$XMLParam.value }
      "customheader" { $CustomHeader=$XMLParam.value }
      "customheaderdelimiter" { $CustomHeaderDelimiter=$XMLParam.value }
      "sendmail" { if ($XMLParam.value -eq "yes") { $SendMail=$True } }
      "objectslist" { if ($XMLParam.value -eq "yes") { $UseObjectsList=$True } }
      "livestatus" { if ($XMLParam.value -eq "yes") { $UseLiveStatus=$True } }
      "transcript" { if ($XMLParam.value -eq "yes") { $UseTranscript=$True } }
      "autosave" { if ($XMLParam.value -eq "yes") { $SeqAutoSave=$True } }
      "objectadditionalparams" { $ObjectAdditionalParams=$XMLParam.value }
      "objectasparam" { if ($XMLParam.value -eq "yes") { $ObjectAsParam=$True } }
      "autosaveinterval" { if ($XMLParam.value -lt 1 -or $XMLParam.value -gt 60) { $SeqAutoSaveInterval=1 } else { $SeqAutoSaveInterval=$XMLParam.value }  }
      "alwaysqueryvariables" { if ($XMLParam.value -eq "yes") { $AlwaysQueryVariables=$True } }
      "timeout" { $Timeout=$XMLParam.value ; $ContinueAfterTimeout=($XMLParam.continueaftertimeout -eq "yes") }
      "sequencelog" { 
        $SequenceLog=$XMLParam.value
        if ([bool]($XMLParam.PSobject.Properties.Name -match "addtimestamp")) {
          $SequenceLogTimestamp=($XMLParam.addtimestamp -eq "Yes")
        }
        if ([bool]($XMLParam.PSobject.Properties.Name -match "debug")) {
          $SequenceDebug=($XMLParam.debug -eq "Yes")
        }
      }
    }
    switch -wildcard ($XMLParam.name) {  # A mail parameter has been detected
      "mail*" { New-Variable -Name $_ -Value $XMLParam.value -Force }
    }
  }

  $MailOptions=[PSObject]@{
    MailServer=$MailServer
    MailServerPort=$MailServerPort
    MailFrom=$MailFrom
    MailTo=$MailTo
    MailUseSSL=$MailUseSSL
    MailUsername=$MailUsername
    MailPassword=$MailPassword
    MailSSLIgnoreErrors=$MailSSLIgnoreErrors
  }
  $Parameters=[PSObject]@{
    SequenceName=$SeqName
    Warning=$DisplayWarning
    SecurityCode=$SecurityCode
    Message=$MessageBox
    EndMessage=$EndMessageBox
    MaxThreads=$MaxThreads
    MaxObjects=$MaxObj
    SendMail=$SendMail
    MailOptions=$MailOptions
    CustomHeader=$CustomHeader
    CustomHeaderDelimiter=$CustomHeaderDelimiter
    ObjectsList=$UseObjectsList
    SeqAutoSave=$SeqAutoSave
    SeqAutoSaveInterval=$SeqAutoSaveInterval
    UseLiveStatus=$UseLiveStatus
    UseTranscript=$UseTranscript
    MinimumVersion=$MinimumVersion
    SequenceLog=$SequenceLog
    SequenceLogTimestamp=$SequenceLogTimestamp
    SequenceDebug=$SequenceDebug
    ObjectAdditionalParams=$ObjectAdditionalParams
    ObjectAsParam=$ObjectAsParam
    AlwaysQueryVariables=$AlwaysQueryVariables
    TimeOut=$Timeout
    ContinueAfterTimeout=$ContinueAfterTimeout
  }

  return $Parameters

}


function Load-Sequence_Tasks($xmldata, $FileSeqParentPath, $SeqPath) {

  # Load the Tasks sections from a sequence file
  
  $TaskLoaded=,@()
  $ErrorFound=$False
  $TaskTypList=@("PreLoad","Task", "PostTask")
  $GlobalPosition=1
  $SeqPosition=0
  $Ids=@()

  foreach ($TaskType in $TaskTypList) {

    if ($TaskType -eq "task") {  # Define the parameters for the Preload checks
      $XMLSeqTask=($xmldata.sequence | Select-Object task).task
      $StepName="Step"
      $OKColor="Green"
    }
    elseif ($TaskType -eq "preload") {  # Define the parameters for the preload checks
      $XMLSeqTask=($xmldata.sequence | Select-Object preload).preload
      $StepName="PreLoad"
      $OKColor="Magenta"
    }
    else {  # Define the parameters for the posttask checks
      $XMLSeqTask=($xmldata.sequence | Select-Object posttask).posttask
      $StepName="PostTask"
      $OKColor="Magenta"
    }

    foreach ($XMLTask in $XMLSeqTask) {  # Loop in all the tasks found
      $SeqEnabled=$True
      $SeqPath=$XMLTask.path
      $SeqComment=$XMLTask.comment
      $SeqMaxOccurrences=0
      $SeqId=$Null
      $SeqMandatory=$False
      $SeqTimeOut=0
      $SeqContinueAfterTimeout=$False
      $TaskComment=$XMLTask.comment
      if ([bool]($XMLTask.PSobject.Properties.Name -match "altcomment")) {
        $SeqComment=$XMLTask.altcomment
      }
      if ([bool]($XMLTask.PSobject.Properties.Name -match "mandatory")) {
        $SeqMandatory=$XMLTask.Mandatory -eq $True
      }
      if ( ([bool]($XMLTask.PSobject.Properties.Name -match "id")) -and ($StepName -eq "Step") ) {  # Id are not ignored for PreLoads
        $SeqId=$XMLTask.id
      }
      if ([bool]($XMLTask.PSobject.Properties.Name -match "enabled")) {
        if ($XMLTask.Enabled -eq "false") {
          $SeqEnabled=$False
        }
      }
      if ([bool]($XMLTask.PSobject.Properties.Name -match "timeout")) {
        $SeqTimeOut=[int]$($XMLTask.timeout)
      }
      if ([bool]($XMLTask.PSobject.Properties.Name -match "continueaftertimeout")) {
        $SeqContinueAfterTimeout=$($XMLTask.ContinueAfterTimeout) -eq "yes"
      }
      if ([bool]($XMLTask.PSobject.Properties.Name -match "maxoccurrences")) {
        $SeqMaxOccurrences=[int]$($XMLTask.maxoccurrences)
      }

      $SeqFound=$False
      $SeqLocation=""
      $TaskRelativeTo=[IO.Path]::Combine($FileSeqParentPath, $SeqPath)  # Built a path name based on the sequence.xml file and the Task file path

      if (Test-Path $TaskRelativeTo) {  # Search first the Task file in the relative path of the sequence.xml file
        $SeqFound=$True
        $SeqLocation=$TaskRelativeTo  # Set the Sequence location to this path
      }
      elseif (Test-Path $SeqPath) {  # Search then in the path found in the node
        $SeqFound=$True 
        $SeqLocation=$SeqPath  # Set the Sequence location as defined in the node
      }
    
      if ($SeqFound -eq $True) {  # The Task is found
        $Error.Clear()
        # Load the Task content as a ScriptBlock and assign it to the ScriptBlockLoaded array
        try {
          $ScriptContent=Get-Content $SeqLocation -Raw -ErrorAction SilentlyContinue
          $ScriptBlockLoaded=[ScriptBlock]::Create($ScriptContent)
          if ($ScriptContent -like "*`$HydraReturn*") {
            $ParamNotFound=$True  # Add the Transcript command after the 1st occurrence of Param
            $ScriptContent=($ScriptContent.ToString() -split "`n") | ForEach-Object { if (($_ -like "*param*") -and  $ParamNotFound) { $_ + "`r`n $HydraReturnObject `r`n" ; $ParamNotFound=$False } else { $_ } }
          }
          $ScriptBlockLoaded=[ScriptBlock]::Create($ScriptContent)
        }
        catch {}
        if ($Error.Count -ne 0) {  # A syntax error has been detected
          $ErrorMsg=((($Error[0].ToString() -split "`r") | Select-String "At line" | Select-Object -Last 1).ToString()).Replace("`n", "")
          Create-CheckBoxInSequence "$StepName $($SeqPosition+1)" "  Error: $ErrorMsg" $GlobalPosition $False "Red" "Italic" $SeqMandatory $SeqLocation | Out-Null
          $TaskLoaded+=[PSObject]@{  
            Code="Error: error detected Line:$ErrorMsg"
            Comment=$SeqComment
            Id=$SeqId
            MaxOccurrences=$SeqMaxOccurrences
            Checked=$False
            Type=$TaskType
            Mandatory=$SeqMandatory
            Timeout=0
            ContinueAfterTimeout=$false
          }
          $ErrorFound=$True
        }
        elseif ($Ids -contains $SeqId) {  # The Id is double
          Create-CheckBoxInSequence "$StepName $($SeqPosition+1)" "  Error: Sequence ID already defined :$SeqId" $GlobalPosition $False "Red" "Italic" $SeqMandatory $SeqLocation | Out-Null
          $TaskLoaded+=[PSObject]@{  
            Code="Error: Sequence ID already defined :$SeqId"
            Comment=$SeqComment
            Id=$SeqId
            MaxOccurrences=$SeqMaxOccurrences
            Checked=$False
            Type=$TaskType
            Mandatory=$SeqMandatory
            Timeout=0
            ContinueAfterTimeout=$False
          }
          $ErrorFound=$True          
        }
        else {  # No syntax error detected
          Create-CheckBoxInSequence "$StepName $($SeqPosition+1)" "  $TaskComment" $GlobalPosition $SeqEnabled $OKColor "Normal" $SeqMandatory $SeqLocation | Out-Null
          if ($SeqId -ne $Null) { $Ids+=$SeqId }
          $TaskLoaded+=[PSObject]@{  
            Code=$ScriptBlockLoaded
            Comment=$SeqComment
            Id=$SeqId
            MaxOccurrences=$SeqMaxOccurrences
            Checked=$SeqEnabled
            Type=$TaskType
            Mandatory=$SeqMandatory
            Timeout=$SeqTimeOut
            ContinueAfterTimeout=$SeqContinueAfterTimeout
          }
        }
      }
      else {  # The Task was not found
          Create-CheckBoxInSequence "$StepName $($SeqPosition+1)" "Missing: $SeqPath" $GlobalPosition $False "Red" "Italic" $SeqMandatory $SeqLocation | Out-Null
          $TaskLoaded+=[PSObject]@{  
            Code="Missing: $SeqPath"
            Comment=$SeqComment
            Id=$SeqId
            MaxOccurrences=$SeqMaxOccurrences
            Checked=$False
            Type=$TaskType
            Mandatory=$SeqMandatory
            Timeout=0
            ContinueAfterTimeout=$False
          }
        $ErrorFound=$True
      }
      $SeqPosition++  # Increase the sequence position
      $GlobalPosition++  # Increase the global step position
    }

  }

  return $TaskLoaded, $ErrorFound

}


function Load-Sequence_Variables($xmldata) {

 # Load the Variable sections from a sequence file

  $XMLSeqVar=($xmldata.sequence | Select-Object variable).variable
  $Variables=@()  # Array for the variables
  foreach ($XMLVar in $XMLSeqVar) {  # Loop into the "variable" found
    if ($XMLVar.type -in $VariableTypes) {  # The variable Type is known
      if ([bool]($XMLVar.PSObject.Properties.Name -match "condition")) {
        $Condition=$XMLVar.condition
        try {  # Check if the condition for syntax errors
          $ScriptBlock=[ScriptBlock]::Create($Condition)
        }
        catch {
          if ($DebugMode -eq 1) { 
            write-host "`n Error with condition in sequence: (Variable: $($XMLVar.name)) $Condition" 
          }
          $Condition="1 -lt 0"
        }
      }
      else {
        $Condition="1 -gt 0"
      }
      
      if ([bool]($XMLVar.PSObject.Properties.Name -match "value")) { $Text=$XMLVar.value } else { $Text=$Null }      
      if ([bool]($XMLVar.PSObject.Properties.Name -match "title")) { $Title=$XMLVar.title } else { $Title=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "message")) { $Message=$XMLVar.message } else { $Message=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "defaultvalue")) { $DefaultValue=$XMLVar.defaultvalue } else { $DefaultValue=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "path")) { $Path=$XMLVar.path } else { $Path=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "filetype")) { $FileType=$XMLVar.filetype } else { $FileType=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "items")) { $Items=$XMLVar.items | ForEach-Object { $_.item } } else { $Items=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "vartype")) { $VarType=$XMLVar.vartype } else { $VarType=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "varvalue")) { $VarValue=$XMLVar.varvalue } else { $VarValue=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "returntype")) { $ReturnType=$XMLVar.returntype } else { $ReturnType=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "displayseparator")) { $DisplaySeparator=$XMLVar.displayseparator } else { $DisplaySeparator=$Null }
      if ([bool]($XMLVar.PSObject.Properties.Name -match "panelsize")) { $PanelSize=$XMLVar.panelsize } else { $PanelSize=$Null }

      $Variables+=[PSObject]@{  # Create a new variable object with its type, name and value
        Type=$XMLVar.type
        Name=$XMLVar.name
        Text=$Text
        Title=$Title
        Message=$Message
        DefaultValue=$DefaultValue
        Path=$Path
        FileType=$FileType
        Items=$Items
        VarType=$VarType
        VarValue=$VarValue
        ReturnType=$ReturnType
        Value=$Null
        Condition=$Condition
        DisplaySeparator=$DisplaySeparator
        PanelSize=$PanelSize
      }
    }
  }

  return $Variables

}


function Load-XAMLVariables($XAMLToParse, $FormToUse) {

  # Load and assign XAML variables from a form

  $XAMLToParse=$XAMLToParse -Replace 'mc:Ignorable="d"','' -Replace "x:Name",'Name'  -Replace '^<Win.*', '<Window'
  [xml]$XAML=$XAMLToParse

  #Read XAML

  $Reader=(New-Object System.Xml.XmlNodeReader $XAML)

  try {
    switch ($FormToUse) {
      "Main" { $Script:Form=[Windows.Markup.XamlReader]::Load($Reader) ; $Form.FontFamily=$FontDefaultFamily ; break }
      "ADPicker" { $Script:ADPickerForm=[Windows.Markup.XamlReader]::Load($Reader) ; $ADPickerForm.FontFamily=$FontDefaultFamily ; break }
      "IPQuery" { $Script:IPQueryForm=[Windows.Markup.XamlReader]::Load($Reader) ; $IPQueryForm.FontFamily=$FontDefaultFamily ; break }
      "SnapshotManager" { $Script:SnapshotManagerForm=[Windows.Markup.XamlReader]::Load($Reader) ; $SnapshotManagerForm.FontFamily=$FontDefaultFamily ; break }
      "SnapshotUpdate" { $Script:SnapshotUpdateForm=[Windows.Markup.XamlReader]::Load($Reader) ; $SnapshotUpdateForm.FontFamily=$FontDefaultFamily ; break }
      "Settings" { $Script:SettingsForm=[Windows.Markup.XamlReader]::Load($Reader) ; $SettingsForm.FontFamily=$FontDefaultFamily ; break }
      "Export" { $Script:ExportForm=[Windows.Markup.XamlReader]::Load($Reader) ; $ExportForm.FontFamily=$FontDefaultFamily ; break }
      "ExportChart" { $Script:ExportChartForm=[Windows.Markup.XamlReader]::Load($Reader) ; $ExportChartForm.FontFamily=$FontDefaultFamily ; break }
      "ExportExcelAll" { $Script:ExportExcelAllForm=[Windows.Markup.XamlReader]::Load($Reader) ; $ExportExcelAllForm.FontFamily=$FontDefaultFamily ; break }
      "CustomSort" { $Script:SortForm=[Windows.Markup.XamlReader]::Load($Reader) ; $SortForm.FontFamily=$FontDefaultFamily ; break }
      "CustomGroup" { $Script:SortForm=[Windows.Markup.XamlReader]::Load($Reader) ; $SortForm.FontFamily=$FontDefaultFamily ; break }
      "CustomFilter" { $Script:SortForm=[Windows.Markup.XamlReader]::Load($Reader) ; $SortForm.FontFamily=$FontDefaultFamily ; break }
      "HomePerso"{ $Script:HomePersoForm=[Windows.Markup.XamlReader]::Load($Reader) ; $HomePersoForm.FontFamily=$FontDefaultFamily ; break }
      "AutoSave" { $Script:AutoSaveForm=[Windows.Markup.XamlReader]::Load($Reader) ; $AutoSaveForm.FontFamily=$FontDefaultFamily ; break }
      "Keywords" { $Script:KeywordsForm=[Windows.Markup.XamlReader]::Load($Reader) ; $KeywordsForm.FontFamily=$FontDefaultFamily ; break }
      "About" { $Script:AboutForm=[Windows.Markup.XamlReader]::Load($Reader) ; $AboutForm.FontFamily=$FontDefaultFamily ; break }
      "Splash" { $Script:SplashForm=[Windows.Markup.XamlReader]::Load($Reader) ; break }
    }
  }
  catch {
    Write-Host "Error loading the graphical elements. There may be a problem with the XAML syntax or .NET is not correctly installed."
    Exit
  }

  # Create a variable for every XAML Objects
 
  switch ($FormToUse) {
    "Main" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $Form.FindName($_.Name) -Scope Script }
      Set-ObjectsControls
      break 
    }
    "ADPicker" {
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $ADPickerForm.FindName($_.Name) -Scope Script }
      Set-ADPickerControls
      break
    }
    "AutoSave" {
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $AutoSaveForm.FindName($_.Name) -Scope Script }
      Set-AutoSaveControls
      break
    }
    "HomePerso" {
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $HomePersoForm.FindName($_.Name) -Scope Script }
      Set-HomePersoControls
      break 
    }
    "IPQuery" {
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $IPQueryForm.FindName($_.Name) -Scope Script }
      Set-IPQueryControls
      break 
    }
    "SnapshotManager" {
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $SnapshotManagerForm.FindName($_.Name) -Scope Script }
      Set-SnapshotManagerControls
      break 
    }
    "SnapshotUpdate" {
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $SnapshotUpdateForm.FindName($_.Name) -Scope Script }
      Set-SnapshotUpdateControls
      break 
    }
    "Settings" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $SettingsForm.FindName($_.Name) -Scope Script }
      Set-SettingsControls   
      break 
    }
    "Export" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $ExportForm.FindName($_.Name) -Scope Script }
      Set-ExportControls   
      break 
    }
    "ExportChart" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $ExportChartForm.FindName($_.Name) -Scope Script }
      Set-ExportChartControls   
      break 
    }
    "ExportExcelAll" {
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $ExportExcelAllForm.FindName($_.Name) -Scope Script } 
      break 
    }
    "CustomSort" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $SortForm.FindName($_.Name) -Scope Script }
      Set-SortControls
      break 
    }
    "CustomGroup" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $SortForm.FindName($_.Name) -Scope Script }
      Set-GroupControls
      break 
    }
    "CustomFilter" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $SortForm.FindName($_.Name) -Scope Script }
      Set-FilterControls
      break 
    }
    "Keywords" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $KeywordsForm.FindName($_.Name) -Scope Script }
      Set-KeywordsControls 
      break 
    }
    "About" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $AboutForm.FindName($_.Name) -Scope Script }
      Set-AboutControls 
      break 
    }
    "Splash" { 
      $XAML.SelectNodes("//*[@Name]") | ForEach-Object { Set-Variable -Name ($_.Name) -Value $SplashForm.FindName($_.Name) -Scope Script }
      break 
    }
  }

}


function Open-ADPicker {

  # Load and show the window AD Picker

  $Script:LoadADCount=0
  Load-XAMLVariables $XAMLADPickerWindow "ADPicker"
  if ($LoadADCount -eq 0) {
    MessageBox "AD Picker" "Unable to contact a domain" 3 1
    return
  }
  $btQuery.IsEnabled=$False
  $ADPickerForm.Left=$Form.Left + ($Form.Width - $ADPickerForm.Width)/2
  $ADPickerForm.Top=$Form.Top + ($Form.Height - $ADPickerForm.Height)/2
  $ADPickerForm.Background="#FFD0D0D0"
  $ADPickerForm.Icon=Set-Icon $Icon049Base64
  $ADPickerForm.ShowDialog()

}


function Open-AutoSave {

  # Load and show the window AutoSave/Restore Point

  Load-XAMLVariables $XAMLAutosaveWindow "AutoSave"

  $AutoSaveForm.Left=$Form.Left + ($Form.Width - $AutoSaveForm.Width)/2
  $AutoSaveForm.Top=$Form.Top + ($Form.Height - $AutoSaveForm.Height)/2
  $AutoSaveForm.ResizeMode="NoResize"
  $AutoSaveForm.Background="#FFD0D0D0"
  $AutoSaveForm.Icon=Set-Icon $Icon341Base64
  $AutoSaveForm.ShowDialog()

}


function Open-Dialog {

  # Load and show the window About

  Load-XAMLVariables $XAMLAboutWindow "About"

  $AboutForm.Left=$Form.Left + ($Form.Width - $AboutForm.Width)/2
  $AboutForm.Top=$Form.Top + ($Form.Height - $AboutForm.Height)/2
  $AboutForm.ResizeMode="NoResize"
  $AboutImage.Source=[Convert]::FromBase64String($HydraLogoBase64)
  $AboutForm.Icon=Set-Icon $HydraIconBase64
  $AboutForm.ShowDialog()

}


function Open-Export($ExportType, $ExportAll=$False) {

  # Load and show the window Settings and set the content based on the variables

  if ($ExportAll -eq $true) {
    if ($ObjectsTabControl.Items | Select-Object header | Group-Object Header | Where-Object Count -gt 1) {
      MessageBox "Export All" "Unable to export the Tabs: Some Tab names are not unique." 3 1
      return
    }
  }

  Load-XAMLVariables $XAMLExportWindow "Export"
  $Script:MessageDuplicate=$False
  $Script:ExportCellsAsText=$False

  switch ($ExportType) {
    
    "HTML" { 
      $Button_Export_OK.Content="To HTML"
      $CB_Export_Format.Content="Disable the CSS Style"
      $Button_Export_OK.Add_Click( {
        if (!(Test-Path $(Split-Path $HTMLTempPath))) {
          MessageBox "HTML" "The HTML Temp folder is not set or doesn't exist.`r`nPlease set it in the Settings." 3 1
          return
        }
        if ($ExportAll -eq $False) {
          Export-ToHTML -UseStyle $($CB_Export_Format.IsChecked -eq $False) -Open $True
        }
        else {
          Export-ToHTML_All -UseStyle $($CB_Export_Format.IsChecked -eq $False) -Open $True
        }
        $Script:MessageDuplicate=$False
        $ExportForm.Close()
      })
      $Button_Export_OKAs.Content="To HTML as..."
      $Button_Export_OKAs.Add_Click( {
        $SaveAs=Save-As "HTML"
        if ($SaveAs -ne "") {
          if ($ExportAll -eq $False) {
            Export-ToHTML -UseStyle $($CB_Export_Format.IsChecked -eq $False) -Open $True -PathToSave $SaveAs -NameWithDate $False
          }
          else {
            Export-ToHTML_All -UseStyle $($CB_Export_Format.IsChecked -eq $False) -Open $True -PathToSave $SaveAs -NameWithDate $False
          }
        }
        $ExportForm.Close()
      })


    }
    "XLSX" { 
      if (!(Test-Path $(Split-Path $HTMLTempPath))) {
        MessageBox "HTML" "The HTML Temp folder is not set or doesn't exist.`r`nPlease set it in the Settings." 3 1
        return
      }
      if (!(Test-Path $(Split-Path $XLSXTempPath))) {
        MessageBox "XLSX" "The XLSX Temp folder is not set or doesn't exist.`r`nPlease set it in the Settings." 3 1
        return
      }
      $Button_Export_OK.Content="To XLSX"
      $Button_Export_OK.Add_Click( {
        if ($ExportAll -eq $False) {
          $Script:ExportCellsAsText=$($CB_Export_Format.IsChecked -eq $True)
          Export-ToExcel
          $Script:MessageDuplicate=$False
          $ExportForm.Close()
        }
        else {
          $Script:ExportCellsAsText=$($CB_Export_Format.IsChecked -eq $True)
          $ExportForm.Close()
          Open-ExportExcelAll -NameWithDate $True
          $Script:MessageDuplicate=$False
        }
      })
      $Button_Export_OKAs.Content="To XLSX as..."
      $Button_Export_OKAs.Add_Click( {
        $SaveAs=Save-As "XLSX"
        if ($SaveAs -ne "") {
          if ($ExportAll -eq $False) {
            $Script:ExportCellsAsText=$($CB_Export_Format.IsChecked -eq $True)
            Export-ToExcel -PathToSave $SaveAs -NameWithDate $False
            $Script:MessageDuplicate=$False
            $ExportForm.Close()
          }
          else {
            $Script:ExportCellsAsText=$($CB_Export_Format.IsChecked -eq $True)
            $ExportForm.Close()
            Open-ExportExcelAll -PathToSave $SaveAs -NameWithDate $False
            $Script:MessageDuplicate=$False
          }
        }
      })

    }
    "CSV" { 
      if (!(Test-Path $(Split-Path $CSVTempPath))) {
        MessageBox "CSV" "The CSV Temp folder is not set or doesn't exist.`r`nPlease set it in the Settings." 3 1
        return
      }
      $CB_Export_Color.Visibility="Hidden"
      $TB_CSVCurrentDelimiter.Visibility="Visible"
      $TB_CSVCurrentDelimiterLabel.Visibility="Visible"
      [System.Windows.Controls.Canvas]::SetTop($CB_Export_Selection,15)
      [System.Windows.Controls.Canvas]::SetTop($CB_Export_Header,45)
      [System.Windows.Controls.Canvas]::SetTop($TB_CSVCurrentDelimiter,75)
      [System.Windows.Controls.Canvas]::SetTop($TB_CSVCurrentDelimiterLabel,75)
      [System.Windows.Controls.Canvas]::SetTop($CB_Export_Filtered,105)
      $TB_CSVCurrentDelimiter.Text=$CSVDelimiter
      $Button_Export_OK.Content="To CSV"
      $Button_Export_OK.Add_Click( {
      
        if ($TB_CSVCurrentDelimiter.Text -ne '`t') {
          try {
            $CSVDelimiterCheck=[char]$($TB_CSVCurrentDelimiter.Text)
          }
          catch {
            $CSVDelimiterCheck=$CSVDelimiter
          }
        }
        else {
          $CSVDelimiterCheck=[char]"`t"
        }

        if ($CSVDelimiterCheck -eq $CSVDelimiter) {
          Export-CreateCSV -Object $CB_Export_Name.IsChecked -TaskResult $CB_Export_Result.IsChecked -State $CB_Export_State.IsChecked -SequenceName $CB_Export_SeqName.IsChecked `
                           -Header $CB_Export_Header.IsChecked -Hidden $CB_Export_Filtered.IsChecked -OnlySelection $CB_Export_Selection.IsChecked
        }
        else {
          Export-CreateCSV -Object $CB_Export_Name.IsChecked -TaskResult $CB_Export_Result.IsChecked -State $CB_Export_State.IsChecked -SequenceName $CB_Export_SeqName.IsChecked `
                           -Header $CB_Export_Header.IsChecked -Hidden $CB_Export_Filtered.IsChecked -OnlySelection $CB_Export_Selection.IsChecked -UseDelimiter $CSVDelimiterCheck
        }
        $Script:MessageDuplicate=$False
        $ExportForm.Close()
      })
      $Button_Export_OKAs.Content="To CSV as..."
      $Button_Export_OKAs.Add_Click( {
        $SaveAs=Save-As "CSV"
        if ($SaveAs -ne "") {

          if ($TB_CSVCurrentDelimiter.Text -ne '`t') {
            try {
              $CSVDelimiterCheck=[char]$($TB_CSVCurrentDelimiter.Text)
            }
            catch {
              $CSVDelimiterCheck=$CSVDelimiter
            }
          }
          else {
            $CSVDelimiterCheck=[char]"`t"
          }

          if ($TB_CSVCurrentDelimiter.Text -eq $CSVDelimiter) {
            Export-CreateCSV -Object $CB_Export_Name.IsChecked -TaskResult $CB_Export_Result.IsChecked -State $CB_Export_State.IsChecked -SequenceName $CB_Export_SeqName.IsChecked `
                             -Header $CB_Export_Header.IsChecked -Hidden $CB_Export_Filtered.IsChecked -OnlySelection $CB_Export_Selection.IsChecked -PathToSave $SaveAs -AddTimeStamp $False
          }
          else {
            Export-CreateCSV -Object $CB_Export_Name.IsChecked -TaskResult $CB_Export_Result.IsChecked -State $CB_Export_State.IsChecked -SequenceName $CB_Export_SeqName.IsChecked `
                             -Header $CB_Export_Header.IsChecked -Hidden $CB_Export_Filtered.IsChecked -OnlySelection $CB_Export_Selection.IsChecked -PathToSave $SaveAs -AddTimeStamp $False -UseDelimiter $CSVDelimiterCheck
          }
          $Script:MessageDuplicate=$False
        }
        $ExportForm.Close()
      })
    }
    "Mail" { 
      $Button_Export_OK.Content="To Mail"
      $Button_Export_OKAs.Visibility="Hidden"
      $Button_Export_OK.Add_Click( {
        Send-Email
        $ExportForm.Close()
      })
    }

  }

  $GridDefaultView=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)
  if ($GridDefaultView.Filter -eq $Null) {  # No filter: suppress the Filter option
    $CB_Export_Filtered.IsChecked=$False
    $CB_Export_Filtered.Visibility="Hidden"
  }

  $ExportForm.Left=$Form.Left + ($Form.Width - $ExportForm.Width)/2
  $ExportForm.Top=$Form.Top + ($Form.Height - $ExportForm.Height)/2
  $ExportForm.ResizeMode="NoResize"
  $ExportForm.Icon=Set-Icon $Icon026Base64
  $ExportForm.Background="#FFD0D0D0"
  [void]$ExportForm.ShowDialog()

}


function Open-ExportChart {

  # Load and show the window Export to a Chart

  filter Myfilter { if ( $_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
  $view=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource) | Myfilter
  $ViewCount=@($view).count

  if ($ViewCount -eq 0) {
    MessageBox "Chart" "Unable to create a chart with an empty tab.`r`n`r`nPlease be sure to have some data before creating a chart." 3 1
    return
  }

  Load-XAMLVariables $XAMLExportChartWindow "ExportChart"

  $ExportChartForm.Left=$Form.Left + ($Form.Width - $ExportChartForm.Width)/2
  $ExportChartForm.Top=$Form.Top + ($Form.Height - $ExportChartForm.Height)/2
  $ExportChartForm.ResizeMode="NoResize"
  $ExportChartForm.Background="#FFD0D0D0"
  $ExportChartForm.Icon=Set-Icon $Icon062Base64
  $ExportChartForm.ShowDialog()

}


function Open-ExportExcelAll($NameWithDate=$False, $PathToSave=$XLSXTempPath) {

  # Load and show the window Export All to Excel

  Load-XAMLVariables $XAMLExportExcelAllWindow "ExportExcelAll"

  $ExportExcelAllForm.Left=$Form.Left + ($Form.Width - $ExportExcelAllForm.Width)/2
  $ExportExcelAllForm.Top=$Form.Top + ($Form.Height - $ExportExcelAllForm.Height)/2
  $ExportExcelAllForm.ResizeMode="NoResize"
  $ExportExcelAllForm.Background="#FFD0D0D0"
  $ExportExcelAllForm.Icon=Set-Icon $Icon026Base64
  $ExportExcelAllForm.Add_ContentRendered( { Export-ToExcelAll -NameWithDate $NameWithDate -PathToSave $PathToSave } )
  $ExportExcelAllForm.ShowDialog()

}


function Open-HomePerso {

  # Load and show the window Home Personalization

  Load-XAMLVariables $XAMLHomePersoWindow "HomePerso"

  $HomePersoForm.Left=$Form.Left + ($Form.Width - $HomePersoForm.Width)/2
  $HomePersoForm.Top=$Form.Top + ($Form.Height - $HomePersoForm.Height)/2
  $HomePersoForm.ResizeMode="NoResize"
  $HomePersoForm.Background="#FFD0D0D0"
  $HomePersoForm.Icon=Set-Icon $Icon061Base64
  $HomePersoForm.ShowDialog()

}


function Open-IPQuery {

  # Load and show the window IP Query

  Load-XAMLVariables $XAMLIPRangeQueryWindow "IPQuery"

  $IPQueryForm.Left=$Form.Left + ($Form.Width - $IPQueryForm.Width)/2
  $IPQueryForm.Top=$Form.Top + ($Form.Height - $IPQueryForm.Height)/2
  $IPQueryForm.ResizeMode="NoResize"
  $IPQueryForm.Background="#FFD0D0D0"
  $IPQueryForm.Icon=Set-Icon $Icon006Base64
  $IPQueryForm.ShowDialog()

}


function Open-Keywords {

  # Load and show the window Keywords

  Load-XAMLVariables $XAMLKeywordsWindow "Keywords"

  $KeywordsForm.Left=$Form.Left + ($Form.Width - $KeywordsForm.Width)/2
  $KeywordsForm.Top=$Form.Top + ($Form.Height - $KeywordsForm.Height)/2
  $KeywordsForm.ResizeMode="NoResize"
  $KeywordsForm.Icon=Set-Icon $HydraIconBase64
  $KeywordsForm.ShowDialog()

}


function Open-Settings {

  # Open the Settings Window and set the content based on the variables

  Load-XAMLVariables $XAMLSettingsWindow "Settings"

  $SettingsForm.Left=$Form.Left + ($Form.Width - $SettingsForm.Width)/2
  $SettingsForm.Top=$Form.Top + ($Form.Height - $SettingsForm.Height)/2
  $SettingsForm.ResizeMode="NoResize"
  $SettingsForm.Icon=Set-Icon $Icon021Base64
  $SettingsForm.Background="#FFD0D0D0"
  $TB_CSVPath.Text=$CSVTempPath
  $TB_XLSXPath.Text=$XLSXTempPath
  $TB_HTMLPath.Text=$HTMLTempPath
  $TB_SnapshotPath.Text=$SnapshotsPath
  $TB_HydraLog.Text=$LogFilePath
  $TB_VisualStudio.Text=$VisualStudioPath
  $TB_Notepad.Text=$NotepadPath
  $TB_TranscriptsPath.Text=$TranscriptsPath

  $TB_MailSMTP.Text=$EMailSMTPServer
  $TB_MailFrom.Text=$EMailSendFrom
  $TB_MailTo.Text=$EMailSendTo
  $TB_MailSMTPPort.Text=$EMailSMTPPort
  $TB_MailUsername.Text=$EMailUsername
  $TB_MailPassword.Password=$EMailPassword
  $CB_MailSSL.IsChecked=$EMailUseSSL -eq "True"
  $CB_MailSSLIgnoreErrors.IsChecked=$EMailSSLIgnoreErrors -eq "True"

  $CB_SequencesExpanded.IsChecked=($SequenceListExpanded -eq 1)
  $CB_ObjectsNormalized.IsChecked=($ObjectsNormalized -eq 1)
  $CB_BundleWarning.IsChecked=($BundleUncheckOnWarning -eq 1)
  $CB_AutoSave.IsChecked=($UseAutoSave -eq 1)
  $CB_DebugMode.IsChecked=($DebugMode -eq 1)
  $CB_Splash.IsChecked=($SplashScreen -eq 1)
  $TB_CSVDelimiter.Text=$CSVDelimiter

  [void]$SettingsForm.ShowDialog()

}


function Open-SnapshotManager {

  # Load and show the Snapshot Manager

  if ([string]::IsNullOrEmpty($SnapshotsPath)) {
    MessageBox "Snapshot" "The Snapshot folder is not set.`r`nPlease set it in the Settings." 3 1
    return
  }

  if (!(Test-Path $SnapshotsPath)) {
    MessageBox "Snapshot" "The Snapshot folder is not reachable or not correctly set.`r`nPlease set it in the Settings." 3 1
    return
  }

  Load-XAMLVariables $XAMLSnapshotWindow "SnapshotManager"

  $SnapshotManagerForm.Left=$Form.Left + ($Form.Width - $SnapshotManagerForm.Width)/2
  $SnapshotManagerForm.Top=$Form.Top + ($Form.Height - $SnapshotManagerForm.Height)/2
  $SnapshotManagerForm.ResizeMode="NoResize"
  $SnapshotManagerForm.Background="#FFD0D0D0"
  $SnapshotManagerForm.Icon=Set-Icon $Icon336Base64
  $SnapshotManagerForm.ShowDialog()

}


function Open-SnapshotUpdate($AllTabs=$False) {

  # Load and show the Snapshot Update window

  if ([string]::IsNullOrEmpty($SnapshotsPath)) {
    MessageBox "Snapshot" "The Snapshot folder is not set.`r`nPlease set it in the Settings." 3 1
    return
  }

  if (!(Test-Path $SnapshotsPath)) {
    MessageBox "Snapshot" "The Snapshot folder is not reachable or not correctly set.`r`nPlease set it in the Settings." 3 1
    return
  }

  if ($AllTabs -eq $True) {  # Export all tabs
    foreach ($Tab in $ObjectsTabControl.Items) {  # Check if some of the tabs are empty
      if ($Tab.Name -eq "TabPlus") { continue }
      if (@($Tab.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
        MessageBox "Snapshot" "A new Snapshot version cannot be created because at least one Tab is empty ($($Tab.Header))." 3 1
        return
      }
    }
  }
  else {  # Check if the current tab is empty
    if (@($ObjectsTabControl.SelectedItem.Content.ItemsSource).Count -eq 0) {  # Only the placeholder
      MessageBox "Snapshot" "A new Snapshot version cannot be created because this Tab is empty." 3 1
      return
    }
  }

  Load-XAMLVariables $XAMLSnapshotWindow "SnapshotUpdate"

  $SnapshotUpdateForm.Left=$Form.Left + ($Form.Width - $SnapshotUpdateForm.Width)/2
  $SnapshotUpdateForm.Top=$Form.Top + ($Form.Height - $SnapshotUpdateForm.Height)/2
  $SnapshotUpdateForm.ResizeMode="NoResize"
  $SnapshotUpdateForm.Background="#FFD0D0D0"
  $SnapshotUpdateForm.Icon=Set-Icon $Icon338Base64
  $SnapshotUpdateForm.Tag=$AllTabs
  $SnapshotUpdateForm.ShowDialog()

}


function Open-Sort($SortType) {

  # Load and show the window Sort and set its content based on the variables

  Load-XAMLVariables $XAMLSortWindow $SortType
  $SortForm.Left=$Form.Left + ($Form.Width - $SortForm.Width)/2
  $SortForm.Top=$Form.Top + ($Form.Height - $SortForm.Height)/2
  $SortForm.ResizeMode="NoResize"
  $SortForm.Background="#FFD0D0D0"
  $SortForm.Icon=Set-Icon $Icon029Base64
  $SortForm.ShowDialog()

}


function Remove-Objects($FromGrid, $FromFile, $State="") {

  # Remove objects from the grid, and/or from their respective files

  if ($State -eq "") {
    filter myFilter1 { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
    filter myFilter2 { if ($_.Step -eq 0) { $_ } }
    $ObjectsToRemove=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter1 | Select-Object -ExpandProperty Item | myFilter2  # Get the selected objects, removing the last line (placeholder) if it is selected
  }
  else {
    filter myFilter1 { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
    filter myFilter2 { if (($_.Step -eq 0) -and ($_.State -eq $State)) { $_ } }
    $ObjectsToRemove=$ObjectsTabControl.SelectedItem.Content.Items | myFilter1 | myFilter2  # Select on a State base
  }

  if ($FromFile -eq $True) { # Remove from the file
    $FileList=$ObjectsToRemove | Select-Object -ExpandProperty FromFile -Unique
    foreach ($File in $FileList) {  # Generate the objects to remove for each file
      filter myFilter { if ($_.FromFile -eq $File) { $_ } }
      $ObjectsRemaining=$ObjectsToRemove | myFilter | Select-Object -ExpandProperty Objects
      $NewText=Select-String -Path $File -Pattern $ObjectsRemaining -NotMatch | Select-Object -ExpandProperty 'Line'  # Recreate the list of objects removing the ones stored in the array
      $NewText | Set-Content -Path $File  # Recreate the objects file with the new content
    }
  }

  if ($FromGrid -eq $True) { # Remove from the grid
    foreach ($Object in $ObjectsToRemove) {
      $DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag].Remove($Object) | Out-Null
    }
  }

  if (@($DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag]).Count -eq 0) {
    Reset-AllFilters
  }

  Set-State

}


function Remove-ObjectsOfSequence($Seq) {

  # Remove objects of a Sequence from the grid

  filter myFilter1 { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
  filter myFilter2 { if (($_.Step -eq 0) -and ($_.SequenceName -eq $Seq)) { $_ } }
  $ObjectsToRemove=$ObjectsTabControl.SelectedItem.Content.Items | myFilter1 | myFilter2 

  foreach ($Object in $ObjectsToRemove) {
    $DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag].Remove($Object) | Out-Null
  }

  Set-State

}


function Remove-Tab {

  # Suppress the Tab

  if (@($ObjectsTabControl.Items).Count -le 2) {  # At least 2 Tabs needed to accept the deletion
    return
  }

  $Script:TabMoving=$True
  $TabToDelete=$ObjectsTabControl.SelectedItem
  $ObjectsTabControl.Items.Remove($TabToDelete)

  if ($ObjectsTabControl.SelectedIndex -eq @($ObjectsTabControl.Items).Count-1) {  # The Plus Tab is selected: select the one before
    $ObjectsTabControl.SelectedIndex=@($ObjectsTabControl.Items).Count-2
  }
  $Script:TabMoving=$False

  Set-State

}


function Rename-Tab {

  # Rename the Tab 

  $NewTabName=(Read-InputBoxDialog "Tab" "Set the new Tab Name:" "")
  if ($NewTabName -eq "") { return }
  $ObjectsTabControl.SelectedItem.Header=$NewTabName

}


function Reset-DefaultSettings {

  # Reset all settings to Default

  $ReallyReset=(MessageBox "WARNING" "Do you really want to reset all settings to the default values ?`r`n`r`nThis will delete your manually loaded sequences and favorites too." 4 2)
  if ($ReallyReset -eq "yes") {
    Remove-Item -Path $HydraRegPath -Recurse -Force # Delete and recreate HKCU:\Software\Hydra\7
    if ($Profile -eq "") {
      New-Item -Path 'HKCU:\Software\Hydra' -Name 7 | Out-Null
    }
    else {
      New-Item -Path 'HKCU:\Software\Hydra\7' -Name $Profile | Out-Null
    }
    Set-DefaultSettings  # Set the Settings to default 
    $Script:ResetSettings=$True  # With this option, Hydra won't save anything in the Registry on exit
    $Form.Close()
  }

}


function Reset-Objects {

  # Reset the objects to their initial state

  if ($CellEditing -eq $True) {  # A cell is in edit mode
    return
  }

  filter myFilter { if ($_.Step -ne 0 ) { $_ } }
  $ObjectsRunning=@($DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter).Count  # Count the objects running
  if ($ObjectsRunning -gt 0) {  # Some objects are in progress
    MessageBox "Reset Objects" "Unable to reset the objects: some are still running." 3 1
    return
  }

  $ReallyReset=(MessageBox "WARNING" "Do you really want to reset the objects ?`r`nThis will clear all the states and task results."4 2)
  if ($ReallyReset -ne "yes") {
    return
  }
  
  $ObjectsList=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | Select-Object -ExpandProperty Objects
  $DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag].Clear()

  foreach ($Obj in $ObjectsList) {
    try {
      Set-ObjectSettings $Obj
    }
    catch {}
  }

  Check-Bundle  # Check the Bundles in use
  Set-State

  if ($UseClassicMenu -eq "False") {  # Actualize the Bundle menu
    RibbonSetBundle
  }
  else {
    ClassicMenuSetBundle
  }

}


function Select-Bundle($Bundle, $Select=$True) {

  # Select or unselect objects in a Bundle

  foreach ($dgis in $DataGridItemSource) {  # Get the name of all Bundles in use
    filter myFilter { if ($_.BundleName -eq $Bundle) { $_ } }
    $dgis | myFilter | ForEach-Object { $_.IsChecked=$Select }
  }

  Set-State 

}


function Select-Objects($State) {

  # Select the objects in the defined state

  $ObjectsTabControl.SelectedItem.Content.SelectedCells.Clear()  # Deselect all objects
  for ($i=0; $i -lt $ObjectsTabControl.SelectedItem.Content.Items.Count-1; $i++) {  # Loop to all objects
    if ($ObjectsTabControl.SelectedItem.Content.Items[$i].State -eq $State) {  # If the state matches, add the object to the selection
      $item=New-Object System.Windows.Controls.DataGridCellInfo($ObjectsTabControl.SelectedItem.Content.Items[$i], $ObjectsTabControl.SelectedItem.Content.Columns[1])
      $ObjectsTabControl.SelectedItem.Content.SelectedCells.Add($item)
    }
  }

}


function Select-ObjectsOfSequence($Seq) {

  # Select the objects of a specific Sequence

  $ObjectsTabControl.SelectedItem.Content.SelectedCells.Clear()  # Deselect all objects
  for ($i=0; $i -lt $ObjectsTabControl.SelectedItem.Content.Items.Count-1; $i++) {  # Loop to all objects
    if ($ObjectsTabControl.SelectedItem.Content.Items[$i].SequenceName -eq $Seq) {  # If the Sequence Name matches, add the object to the selection
      $item=New-Object System.Windows.Controls.DataGridCellInfo($ObjectsTabControl.SelectedItem.Content.Items[$i], $ObjectsTabControl.SelectedItem.Content.Columns[1])
      $ObjectsTabControl.SelectedItem.Content.SelectedCells.Add($item)
    }
  }

}


function Send-Email {

  # Send the state of the grid per email

  if (($EMailSMTPServer -eq "") -or ($EMailSendFrom -eq "") -or ($EMailSendTo -eq "")) {  # If parameters are missing, exit
    MessageBox "Email" "Unable to find the e-mail parameters.`r`n`r`nEnter the parameters in the Settings panel." 3 1
    return
  }

  $HTML=Export-CreateHTML -Object ($CB_Export_Name.IsChecked -eq $True) -TaskResult ($CB_Export_Result.IsChecked -eq $True) -State ($CB_Export_State.IsChecked -eq $True) `
                                      -SequenceName ($CB_Export_SeqName.IsChecked -eq $True) -Header ($CB_Export_Header.IsChecked -eq $True) -Hidden ($CB_Export_Filtered.IsChecked -eq $True) -Color ($CB_Export_Color.IsChecked -eq $True) `
                                      -OnlySelection ($CB_Export_Selection.IsChecked -eq $True) -WithStyle $False
  
  $ToSend=ConvertTo-HTML -Head $HTML[0] -Body "<H2>Sequence Results</H2> $($HTML[1] -replace "%%NEWLINE%%", "<BR>")" | Out-String  # Build a HTML with the values returned by the Export HTML function

  # Send the mail
  Send-MailCommand -SMTPServer $EMailSMTPServer -From $EMailSendFrom -To $EMailSendTo -Subject "Hydra Deployment Results" -Body $ToSend -HTML $True -SMTPPort $EMailSMTPPort -UseSSL $EMailUseSSL -IgnoreSSLError $EMailSSLIgnoreErrors -SMTPUsername $EMailUsername -SMTPPassword $EMailPassword

}


function Set-AssignSequence {  

  # Assign the current loaded Sequence to the selected and free objects

  if ($SequenceLoaded -eq $Null) {
    return
  }

  if ($NewSequenceLoaded -eq $False -and $SequenceSettings[$LastSequenceIndex].Parameter.MaxThreads -ne $ThreadTextBox.Text -and $SequenceLoaded.SequencePath -eq $SequenceSettings[$LastSequenceIndex].SequencePath) {
    $AlreadyRunning=$False
    for ($i=1; $i -lt $SequenceSettings.Count; $i++) {
      if ($SequenceLog[$i] -and $SequenceSettings[$i].SequencePath -eq $SequenceLoaded.SequencePath -and $SequenceSettings[$i].Name -eq $SequenceLoaded.Name) {  # An identical sequence is running
        $AlreadyRunning=$True
      }
    }
    if ($AlreadyRunning -eq $True) {
      MessageBox "Reuse Sequence" "A similar Sequence is already running.`r`nTo reuse this sequence with another Max Thread value, you need to reload the sequence first.`r`n" 3 1
      return
    }
  }

  filter myFilter { if (($_.Hidden -eq $False) -and ($_.IsChecked -eq $True) -and ($_.InProgress -eq $False) -and ($_.Bundle -eq $False)) { $_ } }
  $ObjectsToAssign=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter  # Determine the objects to assign the sequence to

  if (@($ObjectsToAssign).Count -eq 0) {  # No free objects
    return
  }

  if (($SequenceLoaded.Parameter.MaxObjects -gt 0) -and (@($ObjectsToAssign).Count -gt $SequenceLoaded.Parameter.MaxObjects)) {
    MessageBox "Too many objects" "You can't select more than $($SequenceLoaded.Parameter.MaxObjects) objects for this sequence.`r`nPlease correct your selection." 3 1
    return
  }

  filter myFilter { if ($_.Type -eq "posttask") { $_ } }
  $NbPostTask=@($SequenceLoaded.Task[1..$(@($SequenceLoaded.Task).Count-1)] | myFilter).Count
  if ($NbPostTask -gt 0) {  # PostTask in the sequence
    if (@($ObjectsToAssign | Select-Object Objects -Unique).Count -ne @($ObjectsToAssign).Count) {  # Some objects are not unique: that would make problem with the post task global variable hash
      MessageBox "PostTask" "This Sequence contains a PostTask but some of the objects selected are not unique.`r`nPlease correct your selection." 3 1
      return
    }
  }

  if ($SequenceLoaded.Parameter.UseTranscript -eq $True) {
    if ([string]::IsNullOrEmpty($TranscriptsPath)) {
      MessageBox "Transcript" "This Sequence contains a Transcript but the folder for the Transcript files is not set.`r`nPlease set the Transcript folder in the Settings." 3 1
      return
    }
    if (!(Test-Path $TranscriptsPath)) {
      MessageBox "Transcript" "This Sequence contains a Transcript but the folder for the Transcript files is not correctly set or not accessible.`r`nPlease correct the Transcript folder in the Settings." 3 1
      return
    }
    try {
      $TestPath=Join-Path $TranscriptsPath ([IO.Path]::GetRandomFileName())
      New-Item -Path $TestPath -ItemType File -ErrorAction Stop > $null 
    } 
    catch {
      MessageBox "Transcript" "This Sequence contains a Transcript but the folder for the Transcript files is not writable.`r`nPlease choose another Transcript folder in the Settings or modify its permissions." 3 1
      return
    }
    Remove-Item $TestPath -ErrorAction SilentlyContinue
    MessageBox "Transcript" "This Sequence contains a Transcript.`r`nThis should only be used for debugging purposes as it may slow down the execution of the Sequence." 2 1
  }

  if (($SequenceLoaded.Parameter.Warning -eq $True) -and ($AutoRun -eq $False)) {  # A warning parameter has to be confirmed
    $ReallyDeploy=Read-StartSequence $SequenceLoaded.Name $(@($ObjectsToAssign).Count)
    if ($ReallyDeploy -ne "OK") {
      return
    }
  }

  if (($SequenceLoaded.Parameter.SecurityCode -ne "") -and ($AutoRun -eq $False)) {  # A security code has to be typed
    $CodePrompt=Read-SecurityCode $SequenceLoaded.Parameter.SecurityCode $SequenceLoaded.Name
    if ($CodePrompt -ne "OK") {
      return
    }
  }

  if (($SequenceLoaded.Parameter.Message -ne "") -and ($AutoRun -eq $False)) {  # A Message has to be displayed
    MessageBox "Sequence Information" $($SequenceLoaded.Parameter.Message) 1 1
  }

  if ($SequenceLoaded.Parameter.SequenceDebug -eq $True) {  # A Debug log is activated
    MessageBox "Debug" "This Sequence contains a Debug option.`r`nThis should only be used for debugging purposes as it may slow down the execution of the Sequence." 2 1
  }

  $StepsToSkip=@()
  $RunspaceAlreadyCreated=$False

  if ($SequenceLoaded.Parameter.SeqAutoSave -eq $True) { 
    $Script:SequenceAutoSave=$True
    $Script:TimerAutoSaveMinutesInterval=$SequenceLoaded.Parameter.SeqAutoSaveInterval
    $Script:TimerAutoSave.Interval=60000*$TimerAutoSaveMinutesInterval 
  }

  filter myFilter { if ($_.Type -eq "preload") { $_ } }
  $NbPreLoad=@($SequenceLoaded.Task[1..$(@($SequenceLoaded.Task).Count-1)] | myFilter).Count
  if ($NbPreLoad -gt 0) {  # PreLoad in the sequence
    $Script:NewSequenceLoaded=$True
  }

  if ($NewSequenceLoaded) {  # A new sequence has been selected
    $QuerySequenceVariablesValidated="OK"
    if (@($SequenceLoaded.Variable).Count -gt 0) {  # The current loaded sequence has variables to set
      Set-VariableClear
      $QuerySequenceVariablesValidated=Set-QuerySequenceVariables
    }

    if ($QuerySequenceVariablesValidated -contains $False) {  # The variable query has been cancelled, the sequence start is stopped
      Set-Cancel $ObjectsToAssign
      return 
    }

    Set-AssignSequence_Runspace $True
    $Script:NewSequenceLoaded=$False

  }

  else {  # A sequence is reused

    if (@($SequenceLoaded.Variable).Count -gt 0)  {  # Variables have been already defined or must be queried again
      if ($SequenceLoaded.Parameter.AlwaysQueryVariables -eq $True) {
        $ReloadVariables="No"
      }
      else {
        $ReloadVariables=(MessageBox "WARNING" "Variables have been already defined for ""$($SequenceSettings[$LastSequenceIndex].Name)""`r`nDo you want to reuse them ?" 4 2)
      }
      if ($ReloadVariables -eq "no") {
        Load-Sequence $SequencesTreeView.SelectedItem.Header.Tag $SequencesTreeView.SelectedItem.Tag
        $RunspaceAlreadyCreated=$True
        $Script:NewSequenceLoaded=$True
        Set-VariableClear
        $QuerySequenceVariablesValidated=Set-QuerySequenceVariables  # Query the variables again
        if ($QuerySequenceVariablesValidated -contains $False) {  # The variable query has been cancelled, the sequence restart is stopped
          Set-Cancel $ObjectsToAssign
          return
        }
        Set-AssignSequence_Runspace $True 0 #-LoadModules $False
        $Script:NewSequenceLoaded=$False
        $ReloadVariables="no"
      }
      else {  # Reuse the variables: check if a new SequenceId is needed
        if (($NewSequenceIDNeeded -eq $True) -and ($ObjectsTabControl.SelectedItem.Tag -ne $LastSequenceTab)) {
          Set-AssignSequence_Runspace $True 
        }
      }
    }
    else {
      $ReloadVariables="no"
    }

    if (($SequenceSettings[$LastSequenceIndex].RunspacePool.IsDisposed) -or ($ReloadVariables -eq "no")) {  # The Runspace has been disposed: it has to be recreated
      if ($RunspaceAlreadyCreated -ne $True) {
        Set-AssignSequence_Runspace (($NewSequenceIDNeeded -eq $True) -and ($ObjectsTabControl.SelectedItem.Tag -ne $LastSequenceTab))
      }
    }
    $SequenceSettings[$LastSequenceIndex].Parameter.MaxThreads=$ThreadTextBox.Text

  }

  filter myFilter { if ($_.Tag -like "*CB*") { $_ } }
  $CheckBoxes=$SequenceStepsStackPanel.Children | myFilter  # Find the steps checkboxes
  foreach ($CheckBox in $CheckBoxes) {  # Search for the steps to skip
    try {
      if ($CheckBox.IsChecked -eq $False) {
        $CheckBoxPos=$CheckBox.Tag -replace '\D+(\d+)','$1'  # Find the step
        $StepsToSkip+=$CheckBoxPos  # Add this step to the list of steps to skip
      }
    }
    catch {}
  }

  foreach ($Obj in $ObjectsToAssign) {  # Set the different properties of the objects
    $Obj.Step=0
    $Obj.StepToString="0"
    $Obj.State="Pending"
    $Obj.SequenceID=$LastSequenceIndex
    $Obj.Historic=@()
    $Obj.TaskHistory=@()
    $Obj.Paused=$False
    $Obj.SequenceName=($SequenceSettings[$LastSequenceIndex]).Name
    $Obj.Color=$ColorSequencesPending
    $Obj.ColorTemp=$Null
    $Obj.nbTotalSteps=(@($SequenceLoaded.Task).Count-1)
    $Obj.nbTotalStepsToString=($Obj.nbTotalSteps+1).ToString()
    $Obj.StepsToSkip=$StepsToSkip
    $Obj.Bundle=$False
    $Obj.BundleName=""
    $Obj.BundleMaxThreads="N/A"
    $Obj.BundleNameAndThreads=$Obj.BundleName + " (" + $Obj.BundleMaxThreads + ")"
    $Obj.TaskResults="Sequence Loaded: $($Obj.SequenceName)"
    $Obj.TaskResultsExport=$Obj.TaskResults
    $Obj.InProgress=$True
    $Obj.CellFontFormated=$False
    $Obj.IsEnabled=$False
    $Obj.Transcript=$SequenceLoaded.Parameter.UseTranscript
  }

  $Script:SequenceSettings[$LastSequenceIndex].FirstStep=1  # Set the first step to 1: it may be changed later if the 1st step has to be skipped
  $Script:SequenceSettings[$LastSequenceIndex].Schedule=$Null  # A non-Bundle sequence has no scheduler
  $Script:SequenceSettings[$LastSequenceIndex].SchedulerExpired=$False

}


function Set-AssignSequenceToBundle($Schedule, $ObjectsToAssign) {  

  # Assign the current loaded Sequence to the selected and free objects
  if ($ObjectsToAssign -eq $Null) {
    filter myFilter { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
    $ObjectsToAssign=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter | Select-Object -ExpandProperty Item  # Get the selected objects, removing the last line (placeholder) if it is selected
    if (@($ObjectsToAssign).Count -eq 0) {
      return
    }
  }
  $StepsToSkip=@()

  filter myFilter { if ($_.Tag -like "*CB*") { $_ } }
  $CheckBoxes=$SequenceStepsStackPanel.Children | myFilter  # Find the steps checkboxes
  foreach ($CheckBox in $CheckBoxes) {  # Search for the steps to skip
    if ($CheckBox.IsChecked -eq $False) {
      $CheckBoxPos=$CheckBox.Tag -replace '\D+(\d+)','$1'  # Find the step
      $StepsToSkip+=$CheckBoxPos   # Add this step to the list of steps to skip
    }
  }

  Set-AssignSequence_Runspace $True -LoadModules $False
  $Script:NewSequenceLoaded=$True
  
  foreach ($Obj in $ObjectsToAssign) {  # Set the different properties of the objects
    $Obj.Step=0
    $Obj.StepToString="0"
    if ($Schedule -ne $Null) {
      if ($Schedule.ToShortDateString() -eq (Get-Date).ToShortDateString()) {  # The scheduler will start later than today
        $Obj.State=$Schedule.ToLongTimeString()
      }
      else {
        $Obj.State=$Schedule.ToShortTimeString() + " (" + $Schedule.ToShortDateString() + ")"
      }
    }
    else {
      $Obj.State="Pending"
    }
    $Obj.SequenceID=$LastSequenceIndex
    $Obj.Historic=@()
    $Obj.TaskHistory=@()
    $Obj.SequenceName=($SequenceSettings[$Obj.SequenceID]).Name
    $Obj.Color=$ColorSequencesPending
    $Obj.nbTotalSteps=(@($SequenceLoaded.Task).Count-1)
    $Obj.nbTotalStepsToString=($Obj.nbTotalSteps+1).ToString()
    $Obj.StepsToSkip=$StepsToSkip
    $Obj.Bundle=$True
    $Obj.BundleName=$BundleToSet
    $Obj.BundleMaxThreads=$ThreadTextBox.Text
    $Obj.BundleNameAndThreads=$Obj.BundleName + " (" + $Obj.BundleMaxThreads + ")"
    $Obj.TaskResults="Sequence Assigned: $($Obj.SequenceName)"
    $Obj.TaskResultsExport=$Obj.TaskResults
    $Obj.LastTaskResults="-"
    $Obj.InProgress=$False
    $Obj.IsEnabled=$True
    $Obj.CellFontFormated=$False
  }

  $Script:SequenceSettings[$LastSequenceIndex].FirstStep=1  # Set the first step to 1: it may be changed later if the 1st step has to be skipped
  $Script:SequenceSettings[$LastSequenceIndex].Schedule=$Schedule
  $Script:SequenceSettings[$LastSequenceIndex].SchedulerExpired=$False

}


function Set-AssignSequence_Runspace($NewIndex, $IndexID=0, $LoadModules=$True) {

  # Assign a runspace pool to a sequence 
  if ($IndexID -eq 0) {
    $IndexID=$LastSequenceIndex
  }

  if ($NewIndex) {  # A new sequence has been loaded: create a new one
    $Script:LastSequenceIndex++
    $IndexID++
    $Script:SequenceSettings+=$SequenceLoaded.Clone()
    $Script:SequenceSettings[$IndexID].Index=$IndexID
    $Script:SequenceSettings[$IndexID].Parameter.Maxthreads=$ThreadTextBox.Text
    $Script:SequenceLog+=,@()
    $Script:SequenceStats+=[PSCustomObject]@{
      SequenceName=$SequenceSettings[$IndexID].Name
      User=[Environment]::UserName
      Host=[Environment]::MachineName
      NbOfObjects=0
      Date=Get-Date -Format "dd.MM.yyyy"
      StartTime=Get-Date
      EndTime=Get-Date
      OK=0
      BREAK=0
      STOP=0
      END=0
      CANCEL=0
      ERROR=0
    }

    $Script:SequenceLog[$IndexID]+="Sequence $($SequenceSettings[$IndexID].Name)"
    $Script:SequenceLog[$IndexID]+="  Started on $([Environment]::MachineName), by $([Environment]::UserName), at $(Get-Date -Format "dd.MM.yyyy, HH:mm:ss")"
  }
  else {
    if (!($SequenceLog[$IndexID])) {  # The sequence is not running anymore: reset the log
      $Script:SequenceLog[$IndexID]=@()
      $Script:SequenceStats[$IndexID]=[PSCustomObject]@{
        SequenceName=$SequenceSettings[$IndexID].Name
        User=[Environment]::UserName
        Host=[Environment]::MachineName
        NbOfObjects=0
        Date=Get-Date -Format "dd.MM.yyyy"
        StartTime=Get-Date
        EndTime=Get-Date
        OK=0
        BREAK=0
        STOP=0
        END=0
        CANCEL=0
        ERROR=0
      }
      $Script:SequenceLog[$IndexID]+="Sequence $($SequenceSettings[$IndexID].Name)"
      $Script:SequenceLog[$IndexID]+="  Started on $([Environment]::MachineName), by $([Environment]::UserName), at $(Get-Date -Format "dd.MM.yyyy, HH:mm:ss")"
    }
  }

  $Script:NewSequenceIDNeeded=$False
  $Script:LastSequenceTab=$ObjectsTabControl.SelectedItem.Tag

  if ($Script:SequenceSettings[$IndexID].Parameter.Objectslist -eq $True) {
    filter myFilter { if (($_.Objects -ne "DummyPlaceHolder") -and ($_.Hidden -eq $False) -and ($_.IsChecked -eq $True) -and ($_.InProgress -eq $False) -and ($_.Bundle -eq $False)) { $_ } }
    $ObjectsList=($DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter) | Select-Object -ExpandProperty Objects
  }
  else {
    $ObjectsList=$Null
  }

  $SessionState=[System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault()  # Create a InitialSessionState and add default variables
  $SessionState.Variables.Add( (New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry("MyScriptInvocation", $MyScriptInvocation, $null)) )
  $SessionState.Variables.Add( (New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry("SequencePath", $($SequenceSettings[$IndexID].SequencePath), $null)) )
  $SessionState.Variables.Add( (New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry("SequenceFullPath", $($SequenceSettings[$IndexID].SequenceFullPath), $null)) )
  $SessionState.Variables.Add( (New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry("CentralLogPath", $($CentralLogPath + "\" + [Environment]::UserName + "\"), $null)) )
  $SessionState.Variables.Add( (New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry("HydraObjectsList", $ObjectsList, $null)) )

  if ($LoadModules -eq $True) {

    $tbStatusBar1Text=$tbStatusBar1.Text
    $tbStatusBar1ForeGround=$tbStatusBar1.ForeGround
    if ($SequenceSettings[$IndexID].ImportModule) {
      $tbStatusBar1.Text="Loading Modules. Please wait..."
      $tbStatusBar1.ForeGround="Green"
      $StartButton.IsEnabled=$False
      $StartButton.Opacity="0.2"
      [System.Windows.Forms.Application]::DoEvents()
    }

    foreach ($Module in $SequenceSettings[$IndexID].ImportModule) {  # Add modules to the InitialSessionState if some have been declared in the sequence.xml file

      if ($Module.Type -eq "ImportPSSnapIn") { 
        if ((@(Get-PSSnapin | Where-Object Name -eq $Module.Name).Count + @(Get-PSSnapin -Registered | Where-Object Name -eq $Module.Name).Count) -gt 0) {
          [void]$SessionState.ImportPSSnapIn($($Module.Name), [ref]$null)
          continue
        }
      }

      if ($Module.Type -eq "ImportPSModule") { 
        if ($Module.Version -eq 0) {  # Don't check the version
          #if (@(Get-Module -Name $($Module.Name) -ListAvailable -ErrorAction SilentlyContinue).Count -gt 0) {
          if (((Get-Module -Name $($Module.Name) -ListAvailable -ErrorAction SilentlyContinue).ExportedCommands).Count -gt 0) {
            [void]$SessionState.ImportPSModule($($Module.Name))
            continue
          }
        }
        else {  # Check the version
          $ModuleFound=Get-Module -Name $($Module.Name) -ListAvailable -ErrorAction SilentlyContinue | Where-Object { $_.Version -eq $Module.Version }
          if ($ModuleFound) {
            [Microsoft.PowerShell.Commands.ModuleSpecification[]]$ModuleToImport=@( @{ ModuleName=$Module.Name; RequiredVersion=$Module.Version } )  
            [void]$SessionState.ImportPSModule($ModuleToImport)
            continue
          }        
        }
      }

      if (Test-Path $Module.Name) {
        $ModulePath=$Module.Name
      }
      elseif (Test-Path $(Join-Path $($SequenceSettings[$IndexID].SequencePath) $Module.Name)) {
        $ModulePath=$(Join-Path $($SequenceSettings[$IndexID].SequencePath) $Module.Name)
      }
      else {
        MessageBox "ImportModule" "This Sequence contains an ImportModule that can't be found:`r`n`r`nType: $($Module.Type)`r`nPath: $($Module.Name)`r`n`r`nSome functions may fail." 2 1
        continue
      }
      if ($Module.CopyLocally -eq $true) {  # Copy the sources on %TEMP%
        $EnvTemp=$env:temp
        if (($Module.Type -eq "ImportPSSnapIn") -or ($Module.Type -eq "ImportPSModule")) {
          try {
            Copy-Item -Path $ModulePath -Destination $EnvTemp -Force -ErrorAction Stop | Out-Null
            $ModulePath=Join-Path $EnvTemp (Split-Path $ModulePath -Leaf)
          }
          catch  {
            MessageBox "ImportModule" "Unable to copy the module $ModulePath to $EnvTemp" 3 1
            continue
          }
        }
        else {  # Copy all files from ImportPSModulesFromPath
          try {
            Copy-Item -Path $ModulePath\*.* -Destination $EnvTemp -Force -ErrorAction Stop | Out-Null
            $ModulePath=$EnvTemp
          }
          catch {
            MessageBox "ImportModule" "Unable to copy the files from $ModulePath to $EnvTemp" 3 1
            continue
          }
        }
      }

      if ($Module.Type -eq "ImportPSSnapIn") { 
        [void]$SessionState.ImportPSSnapIn($ModulePath, [ref]$null)
      }
      if ($Module.Type -eq "ImportPSModulesFromPath") { 
        [void]$SessionState.ImportPSModulesFromPath($ModulePath) 
      }
      if ($Module.Type -eq "ImportPSModule") { 
        [void]$SessionState.ImportPSModule($ModulePath)
      }
  
    }

  }

  if ($AutoRun -eq $True) {
    $AutoRunVariables.GetEnumerator() | ForEach-Object {
      $SessionState.Variables.Add( (New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry($_.Key, $_.Value, $null)) )
    }
  }
  else {
    if ([string]::IsNullOrEmpty($SequenceSettings[$IndexID].Variable) -eq $False) {
      foreach ($var in $SequenceSettings[$IndexID].Variable) {  # Variables to pass to the runspaces
        $SessionState.Variables.Add( (New-Object System.Management.Automation.Runspaces.SessionStateVariableEntry($var.Name, $var.Value, $null)) )
      }
    }
  }

  $Script:SequenceSettings[$IndexID] | Add-Member -MemberType NoteProperty -Name "RunspacePool" -Value $([RunspaceFactory]::CreateRunspacePool(1, $SequenceSettings[$IndexID].Parameter.MaxThreads, $SessionState, $Host) ) -Force
    
  $SequenceSettings[$IndexID].RunspacePool.Open()

  if ($SequenceSettings[$IndexID].ImportModule -and $LoadModules -eq $True) {
   $tbStatusBar1.Text=$tbStatusBar1Text
    $tbStatusBar1.ForeGround=$tbStatusBar1ForeGround
    $StartButton.IsEnabled=$True
    $StartButton.Opacity="1"
    [System.Windows.Forms.Application]::DoEvents()
  }

}


function Set-AssignToExistingBundle($BundleToSet) {

  # Assign the selected objects to an existing Bundle

  filter myFilter { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
  $ObjectsToAssign=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter | Select-Object -ExpandProperty Item  # Get the selected objects, removing the last line (placeholder) if it is selected

  filter myFilter { if ($_.BundleName -eq $BundleToSet ) { $_ } }
  $RefObjectsInCurrentBundle=$ObjectsTabControl.SelectedItem.Content.ItemsSource | myFilter | Select-Object -First 1

  foreach ($Obj in $ObjectsToAssign) {  # Set the different properties of the objects based on the reference one
    $Obj.Step=0
    $Obj.NextStep=0
    $Obj.StepToString="0"
    $Obj.SequenceID=$RefObjectsInCurrentBundle.SequenceID
    $Obj.Historic=@()
    $Obj.TaskHistory=@()
    $Obj.Paused=$False
    $Obj.SequenceName=$RefObjectsInCurrentBundle.SequenceName
    $Obj.Color=$ColorSequencesPending
    $Obj.nbTotalSteps=$RefObjectsInCurrentBundle.nbTotalSteps
    $Obj.nbTotalStepsToString=($Obj.nbTotalSteps+1).ToString()
    $Obj.StepsToSkip=$RefObjectsInCurrentBundle.StepsToSkip
    $Obj.Bundle=$True
    $Obj.BundleName=$BundleToSet
    $Obj.BundleMaxThreads=$RefObjectsInCurrentBundle.BundleMaxThreads
    $Obj.BundleNameAndThreads=$Obj.BundleName + " (" + $Obj.BundleMaxThreads + ")"
    $Obj.TaskResults="Sequence Assigned: $($Obj.SequenceName)"
    $Obj.TaskResultsExport=$Obj.TaskResults
    $Obj.InProgress=$False
    $Obj.IsEnabled=$True
    $Obj.SharedVariable=$Null
    $Obj.TimeRemaining=""
    $Obj.Runspace=$Null
    $Obj.CellFontFormated=$False
    $Obj.CellFontFamily=$FontDefaultFamily
    $Obj.CellFontColor=$FontDefaultColor
    $Obj.CellFontSize=$FontDefaultSize
    $Obj.CellFontStyle=$FontDefaultStyle
    $Obj.CellFontWeight=$FontDefaultWeight
    $Obj.TasksTimedOut=@()
    $Schedule=$SequenceSettings[$Obj.SequenceID].Schedule
    if ($Schedule -ne $Null) {
      if ($Schedule.ToShortDateString() -eq (Get-Date).ToShortDateString()) {  # The scheduler will start later than today
        $Obj.State=$Schedule.ToLongTimeString()
      }
      else {
        $Obj.State=$Schedule.ToShortTimeString() + " (" + $Schedule.ToShortDateString() + ")"
      }
    }
    else {
      $Obj.State="Pending"
    }
  }

  Check-Bundle  # Check the Bundles in use
  Set-State

  if ($UseClassicMenu -eq "False") {  # Actualize the Bundle menu
    RibbonSetBundle
  }
  else {
    ClassicMenuSetBundle
  }

}


function Set-AutoSaveSettings {
 
  if ($AutoRun -eq $True) { 
    $Script:UseAutoSave=0
    return 
  }

  # Set AutoSave settings

  if (!(Test-Path "$TempEnv\.Hydra7AutoSave")) {
    try {
      New-Item -Path "$TempEnv\.Hydra7AutoSave" -ItemType Directory -Force | Out-Null
    }
    catch {
      $Script:UseAutoSave=0
      return
    }
  }

  # Create the AutoSave subfolders if needed

  for ($i=1; $i -le 3; $i++) {
    if (!(Test-Path "$TempEnv\.Hydra7AutoSave\$i")) {
      New-Item -Path "$TempEnv\.Hydra7AutoSave\$i" -ItemType Directory -Force | Out-Null
    }
  }

  # Find the oldest subfolder and assign it 

  $Script:AutoSaveFolder=Get-ChildItem "$TempEnv\.Hydra7AutoSave" -Directory | Sort-Object LastWriteTime | Select-Object -First 1 | Select-Object -ExpandProperty FullName
  
  # Search for a previous crash

  $Script:CurrentPSId=[System.Diagnostics.Process]::GetCurrentProcess() | Select-Object -ExpandProperty Id
  $PSId=Get-Process | Where-Object { $_.Path -like "*powershell*" } | Select-Object -ExpandProperty Id
  $RecentPIDs=Get-ChildItem "$TempEnv\.Hydra7AutoSave" -Filter "*.pid" | Select-Object -ExpandProperty BaseName
  $OrphanId=$RecentPIDs | Where-Object { $_ -notin $PSid }

  if ($OrphanId -ne $null) {  # A PID file without Powershell process was found
    $Form.Left=$PosFormX
    $Form.Top=$PosFormY
    $Form.WindowState=$WindowState
    $ResetCrash=(MessageBox "WARNING" "A previous Hydra run did not close correctly.`r`n`r`nDo you want to restore a previous state of all tabs ?" 4 2 $False)
    if ($ResetCrash -eq "yes") {
      Open-AutoSave
    }
    foreach ($id in $OrphanId) {
      try {
        Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$id.pid" -Force -ErrorAction SilentlyContinue | Out-Null
      }
      catch {}
    }
  }

  # Define the Timer settings

  $Script:TimerAutoSave=New-Object System.Windows.Forms.Timer
  $Script:TimerAutoSave.Add_Tick( { Create-AutoSavePoint } )
  $Script:TimerAutoSave.Stop()
  $Script:TimerAutoSave.Enabled=$False
  $Script:TimerAutoSave.Interval=60000*$TimerAutoSaveMinutesInterval 

  New-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -ItemType File -Force | Out-Null

}


function Set-Bundle($SequenceName, $UseScheduler) {

  # Set a Bundle

  filter myFilter { if ($_.Type -eq "preload") { $_ } }
  $NbPreLoad=@($SequenceLoaded.Task[1..$(@($SequenceLoaded.Task).Count-1)] | myFilter).Count

  if (($NbPreLoad -gt 0) -and ($UseScheduler -eq $True)) {  # The sequence has PreLoad
    MessageBox "Bundle" "The Sequence '$SequenceName' contains PreLoad tasks.`r`nPreLoad are not supported with a Scheduler." 3 1
    return
  }

  $Script:AllBundle=@()
  foreach ($dgis in $DataGridItemSource) {  # Get the name of all Bundles in use
    filter myFilter { if ($_.Bundle -eq $True) { $_ } }
    $Script:AllBundle+=$dgis | myFilter | Select-Object -ExpandProperty BundleName -Unique 
  }

  $Script:BundleToSet=(Read-InputBoxDialog "Bundle" "Set the Bundle Name to assign '$($SequenceName)':" "")
  if ($BundleToSet -eq "") { return }


  if ($BundleToSet -in $AllBundle) {  # Check if the name is already given to another bundle
    MessageBox "Bundle Name" "The Bundle Name '$BundleToSet' is already assigned." 3 1
    return
  }

  $Script:AllBundle+=$BundleToSet

  if ($UseScheduler -eq $True) {  # Ask for a Scheduler if needed
    $Scheduler=Read-DateTimePicker -WindowTitle "Enter the start for $BundleToSet"
    if ($Scheduler -eq "") { return }
  }
  else {
    $Scheduler=$Null  # No Scheduler set
  }

  Set-AssignSequenceToBundle $Scheduler
  Check-Bundle

  if ($UseClassicMenu -eq "False") {  # Adapt the menu items, if necessary
    RibbonSetBundle
  }
  else {
    ClassicMenuSetBundle
  }

}


function Set-BundleThreads($Bundle) {

  # Modify the Max. Threads for a Bundle

  $NewMaxThreads=Read-InputBoxDialog $($Bundle.BundleName) "Enter the new Maximum Threads value for $($Bundle.BundleName):"
  if ($NewMaxThreads -eq "") { return }
  if (![int32]::TryParse($NewMaxThreads, [ref]"")) {  # Check if the variable contains only integers
    MessageBox "Max. Threads" "Please enter a numeric value." 3 1
    return
  }

  $SequenceSettings[$Bundle.SequenceID].Parameter.MaxThreads=$NewMaxThreads
  
  # Modify BundleMaxThreads for the objects
  filter myFilter { if ($_.BundleName -eq $Bundle.BundleName) { $_ } }
  $ObjectsTabControl.SelectedItem.Content.ItemsSource | myFilter | ForEach-Object { $_.BundleMaxThreads=$NewMaxThreads ; $_.BundleNameAndThreads=$_.BundleName + " (" + $_.BundleMaxThreads + ")" }

}


function Set-Cancel($ObjectsToCancel) {

  # Set the object properties in Cancel state

  foreach ($Obj in $ObjectsToCancel) {
    $Obj.InProgress=$False
    $Obj.IsEnabled=$True
    $Obj.TaskResults="Cancelled"
    $Obj.TaskResultsExport=$Obj.TaskResults
    $Obj.State="CANCELLED"
    $Obj.Historic="Cancelled"
    $Obj.TaskHistory+="Cancelled"
    $Obj.IsChecked=$False
    $Obj.SharedVariable=$Null
    $Obj.Color=$Colors.Get_Item("CANCELLED")
    if ($SequenceLoaded.Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);CANCEL;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceLoaded.Parameter.SequenceLog
    }
    $Obj.Step=0
    $Obj.StepToString="0"
    $Script:ObjectsCounting[$Obj.Tab]++
  }

}


function Set-CancelBundle($ObjectsToCancel) {

  # Set the object properties in Cancel state

  foreach ($Obj in $ObjectsToCancel) {
    $Obj.InProgress=$False
    $Obj.IsEnabled=$True
    $Obj.TaskResults="Cancelled"
    $Obj.TaskResultsExport=$Obj.TaskResults
    $Obj.State="CANCELLED"
    $Obj.Historic="Cancelled"
    $Obj.TaskHistory+="Cancelled"
    $Obj.IsChecked=$False
    $Obj.SharedVariable=$Null
    $Obj.Color=$Colors.Get_Item("CANCELLED")
    if ($SequenceSettings[$Obj.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);CANCEL;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
    }
    $Obj.Step=0
    $Obj.StepToString="0"
    $Obj.TasksTimedOut=@()
    $Script:ObjectsCounting[$Obj.Tab]++
  }

}


function Save-RecentList {

  # Save the manually loaded sequences
  Remove-Variable Recent* -Scope Script
  $ManuallyLoaded=$SequencesTreeView.Items | Where-Object { $_.Header.Tag -like "*Manually Loaded*" } | Select-Object -ExpandProperty Items | Select-Object Header, Tag
  $RegRecent=Get-ItemProperty $HydraRegPath -ErrorAction SilentlyContinue | ForEach-Object { $_.PSObject.Properties } | Where-Object { $_.Name -like "Recent*" } | Select-Object -ExpandProperty Name
  $RegRecent | ForEach-Object { Remove-ItemProperty -Path $HydraRegPath -Name $_ }
  $i=0
  foreach ($ML in $ManuallyLoaded) {
    $i++
    $RegName="Recent{0:D2}" -f $i
    $RegData="$($ML.Header.Tag)|$($ML.Tag)"
    Set-ItemProperty -Path $HydraRegPath -Name $RegName -Value $RegData -Force
    Set-Variable -Name $RegName -Value $RegData -Scope Script -Force
  }

}


function Set-CheckboxesStep($CheckAll=$True) {

  # Check or uncheck all Step checkboxes

  $SequenceStepsStackPanel.Children | ForEach-Object { 
    if ($_ -is [System.Windows.Controls.Checkbox]) { 
      $_.IsChecked=$CheckAll -or !($_.IsHitTestVisible)
    } 
  }

}


function Set-CloseForm {

  # Save all current settings (windows size and position, user's settings, colors,...) into the registry

  if ($AutoRun -eq $True) {  # # Don't save anything when running in AutoRun
    try {
      Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -Force -ErrorAction SilentlyContinue
    }
    catch {}
    return 
  }  

  if ($ResetSettings -eq $True) { return }  # $ResetSettings set to $True: nothing will be saved to the registry 

  Set-ItemProperty -Path $HydraRegPath -Name "TabStyle" -Value $TabStyle -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ButtonStyle" -Value $ButtonStyle -Force
  $colors.GetEnumerator() | ForEach-Object {
    Set-ItemProperty -Path $HydraRegPath -Name "Color_$($_.Key)" -Value $($_.Value) -Force
  }
  Set-ItemProperty -Path $HydraRegPath -Name "ColorSequencesPending" -Value $ColorSequencesPending -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ColorSequencesRunning" -Value $ColorSequencesRunning -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ColorRibbon" -Value $ColorRibbon -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ColorRibbonForeground" -Value $ColorRibbonForeground -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ColorPanels" -Value $ColorPanels -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ColorPanelsForeground" -Value $ColorPanelsForeground -Force
  Set-ItemProperty -Path $HydraRegPath -Name "RibbonHomeHash" -Value $RibbonHomeHash -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ColorBackground" -Value $ColorBackground -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ColorForeground" -Value $ColorForeground -Force
  Set-ItemProperty -Path $HydraRegPath -Name "UseClassicMenu" -Value $UseClassicMenu -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ShowSequenceName" -Value $ShowSequenceName -Force
  Set-ItemProperty -Path $HydraRegPath -Name "SequenceListExpanded" -Value $SequenceListExpanded -Force
  Set-ItemProperty -Path $HydraRegPath -Name "ObjectsNormalized" -Value $ObjectsNormalized -Force
  Set-ItemProperty -Path $HydraRegPath -Name "BundleUncheckOnWarning" -Value $BundleUncheckOnWarning -Force
  Set-ItemProperty -Path $HydraRegPath -Name "DebugMode" -Value $DebugMode -Force
  Set-ItemProperty -Path $HydraRegPath -Name "SplashScreen" -Value $SplashScreen -Force
  Set-ItemProperty -Path $HydraRegPath -Name "CSVDelimiter" -Value $CSVDelimiter -Force
  Set-ItemProperty -Path $HydraRegPath -Name "CSVTempPath" -Value $CSVTempPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "XLSXTempPath" -Value $XLSXTempPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "HTMLTempPath" -Value $HTMLTempPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "SnapshotsPath" -Value $SnapshotsPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "LogFilePath" -Value $LogFilePath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "VisualStudioPath" -Value $VisualStudioPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "NotepadPath" -Value $NotepadPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "CentralLogPath" -Value $CentralLogPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "TranscriptsPath" -Value $TranscriptsPath -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailSMTPServer" -Value $EMailSMTPServer -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailSendFrom" -Value $EMailSendFrom -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailSendTo" -Value $EMailSendTo -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailSMTPPort" -Value $EMailSMTPPort -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailUsername" -Value $EMailUsername -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailPassword" -Value $EMailPassword -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailUseSSL" -Value $EMailUseSSL -Force
  Set-ItemProperty -Path $HydraRegPath -Name "EMailSSLIgnoreErrors" -Value $EMailSSLIgnoreErrors -Force
  Set-ItemProperty -Path $HydraRegPath -Name "LastDirObjects" -Value $LastDirObjects -Force
  Set-ItemProperty -Path $HydraRegPath -Name "LastDirSequences" -Value $LastDirSequences -Force
  Set-ItemProperty -Path $HydraRegPath -Name "LastDirTabs" -Value $LastDirTabs -Force
  Set-ItemProperty -Path $HydraRegPath -Name "LastDirBundles" -Value $LastDirBundles -Force
  Set-ItemProperty -Path $HydraRegPath -Name "WrapText" -Value $WrapText -Force
  Set-ItemProperty -Path $HydraRegPath -Name "PosFormX" -Value $Form.Left -Force
  Set-ItemProperty -Path $HydraRegPath -Name "PosFormY" -Value $Form.Top -Force
  Set-ItemProperty -Path $HydraRegPath -Name "PosFormH" -Value $Form.Height -Force
  Set-ItemProperty -Path $HydraRegPath -Name "PosFormW" -Value $Form.Width -Force
  Set-ItemProperty -Path $HydraRegPath -Name "GridSplitH2" -Value $SequencesGrid.RowDefinitions[2].ActualHeight -Force
  
  if ($SequencesPosition -eq "Left") {
    if ($OrginialSequencesPosition -eq $SequencesPosition) {  # No position change
      Set-ItemProperty -Path $HydraRegPath -Name "GridSplitW" -Value $MainGrid.ColumnDefinitions[0].ActualWidth -Force
    }
    else {
      Set-ItemProperty -Path $HydraRegPath -Name "GridSplitW" -Value $MainGrid.ColumnDefinitions[2].ActualWidth -Force  # It hasn't changed yet
    }
  }
  else {  # $SequencesPosition -eq "Right"
    if ($OrginialSequencesPosition -eq $SequencesPosition) {  # No position change
      Set-ItemProperty -Path $HydraRegPath -Name "GridSplitW" -Value $MainGrid.ColumnDefinitions[2].ActualWidth -Force
    }
    else {
      Set-ItemProperty -Path $HydraRegPath -Name "GridSplitW" -Value $MainGrid.ColumnDefinitions[0].ActualWidth -Force  # It hasn't changed yet
    }
  }
  
  Set-ItemProperty -Path $HydraRegPath -Name "WindowState" -Value $Form.WindowState -Force
  Set-ItemProperty -Path $HydraRegPath -Name "FontDefaultFamily" -Value $FontDefaultFamily -Force
  Set-ItemProperty -Path $HydraRegPath -Name "UseAutoSave" -Value $UseAutoSave -Force
  Set-ItemProperty -Path $HydraRegPath -Name "SequencesPosition" -Value $SequencesPosition -Force

  # Save the manually loaded sequences
  Save-RecentList

  # Save the Favorites
  if (!(Test-Path "$HydraRegPath\Favorites")) {  # Create the Favorites registry structure if it's missing
    New-Item -Path $HydraRegPath -Name Favorites | Out-Null
  }
  $RegFav=Get-ItemProperty "$HydraRegPath\Favorites" -ErrorAction SilentlyContinue | ForEach-Object { $_.PSObject.Properties } | Where-Object { $_.Name -like "Favorite*" } | Select-Object -ExpandProperty Name
  $RegFav | ForEach-Object { Remove-ItemProperty -Path "$HydraRegPath\Favorites" -Name $_ }
  $i=0
  foreach ($Fav in $Favorites) {
    $i++
    $FavName="Favorite{0:D3}" -f $i
    Set-ItemProperty -Path "$HydraRegPath\Favorites" -Name $FavName -Value $Fav -Force
  }

  # Save Addon Variables
  Get-Variable | Where-Object Name -like "Addon_*" | ForEach-Object {
    Set-ItemProperty -Path $HydraRegPath -Name $_.Name -Value $_.Value -Force
  }

  if (($UseAutoSave -eq 1) -and ($AutoRun -eq $False)) {
    Create-AutoSavePoint
  }

  try {
    Remove-Item -Path "$TempEnv\.Hydra7AutoSave\$CurrentPSId.pid" -Force -ErrorAction SilentlyContinue
  }
  catch {}

  if ($PSVersionTable.PSVersion.Major -ge 5) {
    try {
      Get-Runspace -ErrorAction Stop | Where-Object { $_.InitialSessionState.Variables.Name -like "Hydra*" -and ($_.RunspaceAvailability -eq "Available" -or $_.RunspaceAvailability -eq "None") } | foreach { 
        $_.Close()
        $_.Dispose()
      }
    }
    catch {}
  }

}


function Set-ColumnTemplate($ColumnId) {

  # Modify the Column Template to display a Sort, Filter or Group icon

 if ($ColumnId -lt 1 -or $ColumnId -gt 6) { return }

  switch ($ColumnId) {
    1 { $ColumnHeader="Objects" }
    2 { $ColumnHeader="TaskResults" }
    3 { $ColumnHeader="State" }
    4 { $ColumnHeader="Bundle" }
    5 { $ColumnHeader="Color" }
    6 { $ColumnHeader="SequenceName" }
  }

  #Create a template for the column header

  $TextBlock=New-Object System.Windows.FrameworkElementFactory([System.Windows.Controls.TextBlock])
  $TextBlock.SetValue([System.Windows.Controls.TextBlock]::TextProperty, $ColumnHeader.Replace( "TaskResults", "Task Results").Replace( "SequenceName", "Sequence Name"))
  $TextBlock.SetValue([System.Windows.Controls.Image]::MarginProperty, $(New-Object System.Windows.Thickness(0,0,10,0)))

  $DockPanel=New-Object System.Windows.FrameworkElementFactory([System.Windows.Controls.DockPanel])
  $DockPanel.AppendChild($TextBlock)
  
  $GridDefaultView=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource)

  # Add the Sort icon if needed
  foreach ($SD in $GridDefaultView.SortDescriptions) {
    if ($SD.PropertyName -ne $ColumnHeader) { continue }
    $Image=New-Object System.Windows.FrameworkElementFactory([System.Windows.Controls.Image])
    $Image.SetValue([System.Windows.Controls.Image]::WidthProperty, 12.0)
    $Image.SetValue([System.Windows.Controls.Image]::HeightProperty, 12.0)
    $Image.SetValue([System.Windows.Controls.Image]::MarginProperty, $(New-Object System.Windows.Thickness(5,0,0,0)))
    switch ($SD.Direction) {
      "Ascending" { $Image.SetValue([System.Windows.Controls.Image]::SourceProperty, $(Set-Icon $Icon201Base64)) }
      "Descending" { $Image.SetValue([System.Windows.Controls.Image]::SourceProperty, $(Set-Icon $Icon202Base64)) }
    }
    $DockPanel.AppendChild($Image)
  }

  # Add the Group icon if needed
  foreach ($GD in $GridDefaultView.GroupDescriptions) {
    if ($GD.PropertyName -ne $ColumnHeader) { continue }
    $Image=New-Object System.Windows.FrameworkElementFactory([System.Windows.Controls.Image])
    $Image.SetValue([System.Windows.Controls.Image]::WidthProperty, 12.0)
    $Image.SetValue([System.Windows.Controls.Image]::HeightProperty, 12.0)
    $Image.SetValue([System.Windows.Controls.Image]::MarginProperty, $(New-Object System.Windows.Thickness(5,0,0,0)))
    $Image.SetValue([System.Windows.Controls.Image]::SourceProperty, $(Set-Icon $Icon203Base64))
    $DockPanel.AppendChild($Image)
  }

  # Add the Filter icon if needed
  foreach ($Filter in $($GridFilter[$($ObjectsTabControl.SelectedItem.Tag)] -split "-and")) {
    if ($Filter -like "*item.$ColumnHeader*") {
      $Image=New-Object System.Windows.FrameworkElementFactory([System.Windows.Controls.Image])
      $Image.SetValue([System.Windows.Controls.Image]::WidthProperty, 12.0)
      $Image.SetValue([System.Windows.Controls.Image]::HeightProperty, 12.0)
      $Image.SetValue([System.Windows.Controls.Image]::MarginProperty, $(New-Object System.Windows.Thickness(5,0,0,0)))
      if ($Filter -like "*-notmatch*") {
        $Image.SetValue([System.Windows.Controls.Image]::SourceProperty, $(Set-Icon $Icon205Base64))
      }
      else {
        $Image.SetValue([System.Windows.Controls.Image]::SourceProperty, $(Set-Icon $Icon204Base64))
      }
      $DockPanel.AppendChild($Image)
    }
  }

  $DataTemplate=New-Object System.Windows.DataTemplate
  $DataTemplate.VisualTree=$DockPanel

  # Apply the template
  $ObjectsTabControl.SelectedItem.Content.Columns[$ColumnId].HeaderTemplate=$DataTemplate

}


function Set-ConsoleVisible($Visible) {

  # Show or Hide the Powershell console

  Add-Type -Name Window -Namespace Console -MemberDefinition '
  [DllImport("Kernel32.dll")]
  public static extern IntPtr GetConsoleWindow(); 

  [DllImport("user32.dll")]
  public static extern bool ShowWindow(IntPtr hWnd, Int32 nCmdShow);
'
  $consolePtr=[Console.Window]::GetConsoleWindow()
  if ($Visible) {
    $DebugMode=5
  }
  else {
    $DebugMode=0
  }
  [void] [Console.Window]::ShowWindow($consolePtr, $DebugMode)  # 0 to make the Powershell console invisible, 5 to make the Powershell console visible 

  if ($Visible) {
    write-host "Debug Mode"
    Write-host "----------"
    write-host
  }
}


function Set-DefaultSettings {

  # Create all variables needed and set their default values

  New-Variable -Name CSVSeparator -Value ";" -Scope Script -Force
  New-Variable -Name CSVTempPath -Value "C:\Temp\HydraExport.csv" -Scope Script -Force
  New-Variable -Name XLSXTempPath -Value "C:\Temp\HydraExport.xlsx" -Scope Script -Force
  New-Variable -Name HTMLTempPath -Value "C:\Temp\HydraExport.html" -Scope Script -Force
  New-Variable -Name LogFilePath -Value "C:\_logfiles\Hydra.log" -Scope Script -Force
  New-Variable -Name VisualStudioPath -Value "" -Scope Script -Force
  New-Variable -Name NotepadPath -Value "" -Scope Script -Force
  New-Variable -Name SnapshotsPath -Value "C:\Temp" -Scope Script -Force
  New-Variable -Name CentralLogPath -Value "C:\Temp" -Scope Script -Force
  New-Variable -Name LogFileEnabled -Value "True" -Scope Script -Force
  New-Variable -Name TranscriptsPath -Value "C:\Temp" -Scope Script -Force
  New-Variable -Name TempEnv -Value $env:TEMP -Scope Script -Force
  New-Variable -Name Colors -Value @{"OK"="#FF90EE90" ; "GOTO"="#FF90EE90" ; "END"="#FF90EE90" ; "BREAK"="#FFADD8E6" ; "STOP"="#FFF08080" ; "CANCELLED"="#FFC0C0C0" ; "PENDING"="#FF00FFFF"} -Scope Script -Force
  New-Variable -Name DefaultThreads -Value "10" -Scope Script -Force
  New-Variable -Name BundleUncheckOnWarning -Value 1 -Scope Script -Force
  New-Variable -Name ObjectsNormalized -Value 1 -Scope Script -Force
  New-Variable -Name SplashScreen -Value 1 -Scope Script -Force
  New-Variable -Name CSVDelimiter -Value "," -Scope Script -Force
  New-Variable -Name WelcomeScreen -Value "True" -Scope Script -Force
  New-Variable -Name DebugMode -Value 0 -Scope Script -Force
  New-Variable -Name ColorRibbon -Value "#FFC0C0C0" -Scope Script -Force
  New-Variable -Name ColorRibbonForeground -Value "#FF000000" -Scope Script -Force
  New-Variable -Name ColorPanels -Value "#FFF0F0F0" -Scope Script -Force
  New-Variable -Name ColorPanelsForeground -Value "#FF000000" -Scope Script -Force
  New-Variable -Name RibbonHomeHash -Value '[ordered]@{"Load"="RibbonLoad1","RibbonLoad2","RibbonLoad3";"Sequences"="RibbonSequences1";"Objects"="RibbonObjects1","RibbonObjects2","RibbonObjects4";"Export"="RibbonExport2";"Cancel"="RibbonObjects7"}' -Scope Script -Force
  New-Variable -Name ColorBackground -Value "#FF808080" -Scope Script -Force 
  New-Variable -Name ColorForeground -Value "#FF000000" -Scope Script -Force
  New-Variable -Name ColorSequencesPending -Value "#FFFEFAD6" -Scope Script -Force
  New-Variable -Name ColorSequencesRunning -Value "#FFD5EADA" -Scope Script -Force
  New-Variable -Name UseClassicMenu -Value "False" -Scope Script -Force
  New-Variable -Name ShowSequenceName -Value "False" -Scope Script -Force
  New-Variable -Name LastDirObjects -Value "" -Scope Script -Force
  New-Variable -Name LastDirSequences -Value "" -Scope Script -Force
  New-Variable -Name LastDirTabs -Value "" -Scope Script -Force
  New-Variable -Name LastDirBundles -Value "" -Scope Script -Force
  New-Variable -Name ShowSearchBox -Value "True" -Scope Script -Force
  New-Variable -Name FileLoaded -Value "False" -Scope Script -Force
  New-Variable -Name ADQueriesList -Value "$HydraSettingsPath\Hydra_ADQueries.qry" -Scope Script -Force
  New-Variable -Name nbCheckedBoxes -Value 0 -Scope Script -Force
  New-Variable -Name LoadedFiles -Value "" -Scope Script -Force
  New-Variable -Name SequenceListExpanded -Value 1 -Scope Script -Force
  New-Variable -Name RowHeaderVisible -Value "False" -Scope Script -Force
  New-Variable -Name CheckBoxesKeepState -Value "False" -Scope Script -Force
  New-Variable -Name EMailSMTPServer -Value "" -Scope Script -Force
  New-Variable -Name EMailSendFrom -Value "" -Scope Script -Force
  New-Variable -Name EMailSendTo -Value "" -Scope Script -Force
  New-Variable -Name EMailSMTPPort -Value "" -Scope Script -Force
  New-Variable -Name EMailUsername -Value "" -Scope Script -Force
  New-Variable -Name EMailPassword -Value "" -Scope Script -Force
  New-Variable -Name EMailUseSSL -Value "False" -Scope Script -Force
  New-Variable -Name EMailSSLIgnoreErrors -Value "False" -Scope Script -Force
  New-Variable -Name GrpCheckedOnWarning -Value "False" -Scope Script -Force
  New-Variable -Name GrpShowThreads -Value "True" -Scope Script -Force

  New-Variable -Name PosFormX -Value 100 -Scope Script -Force 
  New-Variable -Name PosFormY -Value 10 -Scope Script -Force
  New-Variable -Name PosFormW -Value 1150 -Scope Script -Force 
  New-Variable -Name PosFormH -Value 800 -Scope Script -Force
  New-Variable -Name GridSplitH2 -Value 320 -Scope Script -Force
  New-Variable -Name GridSplitW -Value 250 -Scope Script -Force
  New-Variable -Name WindowState -Value "Normal" -Scope Script -Force

  New-Variable -Name TabStyle -Value "1" -Scope Script -Force
  New-Variable -Name ButtonStyle -Value "1" -Scope Script -Force
  New-Variable -Name ResetSettings -Value $False -Scope Script -Force
  New-Variable -Name WrapText -Value "NoWrap" -Scope Script -Force
  New-Variable -Name SequencesPosition -Value "Left" -Scope Script -Force

  New-Variable -Name TimerIntervalDefault -Value 1000 -Scope Script -Force
  New-Variable -Name TimerInterval -Value $TimerIntervalDefault -Scope Script -Force
  New-Variable -Name TimerAutoSaveMinutesInterval -Value 1 -Scope Script -Force
  New-Variable -Name SendMail -Value $False -Scope Script -Force
  New-Variable -Name TimerSet -Value $False -Scope Script -Force
  New-Variable -Name SelectionChanged -Value $False -Scope Script -Force
  New-Variable -Name VariablesQuery -Value $Null -Scope Script -Force
  New-Variable -Name AllBundle -Value @() -Scope Script -Force
  New-Variable -Name TabMoved -Value $False -Scope Script -Force
  New-Variable -Name TabMoving -Value $False -Scope Script -Force
  New-Variable -Name NewSequenceIDNeeded -Value $False -Scope Script -Force
  New-Variable -Name LastSequenceTab -Value 1 -Scope Script -Force
  New-Variable -Name SnapshotSingle -Value $False -Scope Script -Force
  New-Variable -Name SnapshotMulti -Value $False -Scope Script -Force
  New-Variable -Name UseAutoSave -Value 1 -Scope Script -Force
  New-Variable -Name SequenceAutoSave -Value $False -Scope Script -Force
  New-Variable -Name Favorites -Value @() -Scope Script -Force
  Remove-Variable Recent* -Scope Global

  $Script:ColumnHeaderNames=@{"Objects"=1 ; "Task Results"=2 ; "State"=3 ; "Bundle"=4 ; "Color"=5 ; "Sequence Name"=6 }
  $Script:FontWeightValues=@("Black","Bold","DemiBold","ExtraBlack","ExtraBold","ExtraLight","Heavy","Light","Medium","Normal","Regular","SemiBold","Thin","UltraBlack","UltraBold","UltraLight")
  $Script:FontStyleValues=@("Normal","Italic","Oblique")
  $Script:FontFamilyValues=$(New-Object System.Drawing.Text.InstalledFontCollection).Families

  New-Variable -Name FontDefaultFamily -Value "Segoe UI" -Scope Script -Force
  New-Variable -Name FontDefaultColor -Value "#FF000000" -Scope Script -Force
  New-Variable -Name FontDefaultSize -Value "12" -Scope Script -Force
  New-Variable -Name FontDefaultStyle -Value "Regular" -Scope Script -Force
  New-Variable -Name FontDefaultWeight -Value "Normal" -Scope Script -Force
  New-Variable -Name ConditionValue -Value $Null -Scope Script -Force

  $Script:TabLastIndex=0
  $Script:UniqueID=0
  $Script:CellEditing=$False
  $Script:GridFilter=,@()

  [System.Collections.ObjectModel.ObservableCollection[Object]]$Script:DataGridItemSource=,@()

  $Script:SequenceSettings=,@()
  $Script:SequenceLog=,@()
  $Script:SequenceStats=,@()
  $Script:LastSequenceIndex=0
  $Script:TabObjectAdditionalParams=,@()

  $Script:RunspacePool=,@()
  $Script:ObjectsCounting=,@()

  $Script:SequenceRunning=$False
  $Script:NewSequenceLoaded=$True
  $Script:SequenceLoaded=$Null

  #Define the Timer for the grid refreshes
  $Script:Timer=New-Object System.windows.Forms.Timer
  $Script:Timer.Enabled=$False

  $Script:HydraReturnObject=@'
  $HydraReturn=New-Object -TypeName PSObject -Property (@{'State'="OK";
                                                          'TaskResult'=$Null;
                                                          'Color'=$Null;
                                                          'SharedVariable'=$Null;
                                                          'TaskResultExport'=$Null;
                                                          'GotoStep'=$Null })
'@

}


function Set-DisplaySequence($SeqID, $ShowVar=$True) {

  $SeqPosition=0
  $GlobalPosition=0

  $SequenceStepsStackPanel.Children.Clear()
  Create-LabelInSequence $($SequenceSettings[$SeqID].Name) -FontSize 15

  foreach ($Task in $SequenceSettings[$SeqID].Task[1..$(@($SequenceSettings[$SeqID].Task).Count-1)])  {

    if ($Task.Type -eq "PreLoad") {
      $StepName="Preload"
    }
    else {
      $StepName="Step"
    }

    $SeqMandatory=$False
    try {
      $SeqMandatory=$Task.Mandatory -eq $True
    }
    catch {
      $SeqMandatory=$False
    }

    Create-CheckBoxInSequence "$StepName $($SeqPosition+1)" "  $($Task.Comment)" $GlobalPosition $($Task.Checked) "Magenta" "Italic" $SeqMandatory | Out-Null
  
    $SeqPosition++
    $GlobalPosition++

  }

  if (($ShowVar -eq $True) -and !([string]::IsNullOrEmpty( $SequenceSettings[$SeqID].Variable))) {
    Create-LabelInSequence "" "Blue" "Normal" 12 -8
    foreach ($var in $SequenceSettings[$SeqID].Variable) {
      switch ($var.Type) {
        "secretinputbox" { Create-LabelInSequence -SequenceLabel "$($var.Name): xxxxxxxx" -Color "Blue" -FontStyle "Italic" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) ; break }
        "credentialbox" { Create-LabelInSequence -SequenceLabel"$($var.Name): $($var.Value[0])/xxxxxx" -Color "Blue" -FontStyle "Italic" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) ; break }
        "credentials" { Create-LabelInSequence -SequenceLabel"$($var.Name): credentials" -Color "Blue" -FontStyle "Italic" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) ; break }
        default { Create-LabelInSequence -SequenceLabel"$($var.Name): $($var.Value)" -Color "Blue" -FontStyle "Italic" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) }
      }
    }
  }

}


function Set-LogFile($AtStart=$False) {

  # Check and create the logfile if necessary

  if (Test-Path $LogFilePath) {  # The log file is already present
    $LogFileOK=$True
    try {  # Check if it's writable
      [io.file]::OpenWrite($LogFilePath).Close()
    }
    catch { 
      $LogFileOK=$False
      MessageBox "WARNING" "The Logfile $LogfilePath was detected but seems to be read-only.`r`nLogs won't be written." 2 1
    }
    if (($LogFileOK -eq $True) -and ($AtStart -eq $True)) {
      Add-Content -Path $LogFilePath -Value "" -ErrorAction SilentlyContinue
      Add-Content -Path $LogFilePath -Value $("-"*40) -ErrorAction SilentlyContinue
      Add-Content -Path $LogFilePath -Value "Hydra Started on $(Get-Date -Format "dd.MM.yyyy"), at $(Get-Date -Format "HH:mm:ss")" -ErrorAction SilentlyContinue
      Add-Content -Path $LogFilePath -Value "" -ErrorAction SilentlyContinue
    }
  }
  else {  # The log file doesn't exist
    try {
      New-Item -Path $LogFilePath -ItemType File -Force -ErrorAction Stop | Out-Null
      if ($AtStart -eq $True) {
        Add-Content -Path $LogFilePath -Value "" -ErrorAction Stop
        Add-Content -Path $LogFilePath -Value "Hydra Started on $(Get-Date -Format "dd.MM.yyyy , hh:mm:ss")" -ErrorAction Stop
      }
    }
    catch {
      MessageBox "WARNING" "The Logfile $LogfilePath can't be created: Logs won't be written.`r`nPlease choose another path in the Settings." 2 1
    }
  }

}


function Set-ObjectsPaste_AddParams {

  
  $ColSelected=@($ObjectsTabControl.SelectedItem.Content.SelectedCells | Select-Object -ExpandProperty Column | Select-Object Header | Group-Object -Property Header).Count

  if ($ColSelected -gt 1) {  # Only one column should be highlighted
    return
  }

  if ($ColSelected -eq 1) {
    $ColSelectedName=$ObjectsTabControl.SelectedItem.Content.SelectedCells | Select-Object -ExpandProperty Column | Select-Object -ExpandProperty Header | Select-Object -Unique

    if ($ColSelectedName -like "Param*") {

      $ColNumber=$ColSelectedName -replace '\D+(\d+)','$1'
      $Clipboard=[System.Windows.Forms.Clipboard]::GetText()
      if ($Clipboard -eq "") { return }
      $Separator="`n"  # Use Separators to split the objects and remove useless spaces
      $Clipboard=@($Clipboard.Split($Separator).Trim()) | Where-Object { $_ }
      $ClipboardItems=@($Clipboard).Count
      $i=0

      $Separator="|","`t"  # Use Separators to split the objects
      filter myFilter { if ($_.Item.ToString() -ne "{NewItemPlaceholder}") { $_ } }
      if ($ClipboardItems -eq 1) {
        $ObjectsTabControl.SelectedItem.Content.SelectedCells | myfilter | ForEach-Object { 
          $_.Item.AddParams[$ColNumber -1]=$Clipboard.Trim()
        }
      }
      else {
        $ObjectsTabControl.SelectedItem.Content.SelectedCells | myfilter | ForEach-Object { 
          if ($i -lt $ClipboardItems) {
            $_.Item.AddParams[$ColNumber -1]=(@($Clipboard[$i].Split([string[]]$Separator, [System.StringSplitOptions]::None))[0]).Trim()
            $i++
          }
        }
      }
      $ObjectsTabControl.SelectedItem.Content.Items.Refresh()

      Set-State
      return

    }
    
  }

  $nbCol=$TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]
  $Clipboard=[System.Windows.Forms.Clipboard]::GetText()
  $Separator="`r","`n"  # Use Separators to split the objects and remove useless spaces
  $Clipboard=@($Clipboard.Split([string[]]$Separator, [System.StringSplitOptions]::None).Trim()) | Where-Object { $_ }

  foreach ($item in $Clipboard) {  # Only add non-empty objects
    if ($item -ne "") {

      $Separator="|","`t"  # Use Separators to split the objects and remove useless spaces
      $Clipboard2=@($item.Split([string[]]$Separator, [System.StringSplitOptions]::None).Trim())

      if (@($Clipboard2.Count -gt 1)) {  # With params
        if ($(@($Clipboard2).Count -1) -ge $nbCol) { $nbParam=$nbCol } else { $nbParam=@($Clipboard2).Count -1 }
        $ParamToPass=$Clipboard2[1..$($nbParam)]
        if ($nbParam -lt $nbCol) { $ParamToPass+=@("")*$($nbCol - $nbParam) }
        Set-ObjectSettings $Clipboard2[0] -AddParams $ParamToPass
      }
      else {  # No Params
        Set-ObjectSettings $Clipboard2[0]
      }

    }
  }

  Set-State

}


function Set-ObjectsPaste {

  # Paste the objects stored in the Clipboard to the grid

  if ($TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag] -gt 0 ) {
    Set-ObjectsPaste_AddParams
    return
  }
  
  $Clipboard=[System.Windows.Forms.Clipboard]::GetText()

  if ($Clipboard -eq "") { return }
  $Separator=";",",","|","`r","`n","`t"  # Use Separators to split the objects and remove useless spaces
  #$Clipboard=@($Clipboard.Split($Separator).Trim())  # PS5 only
  #$Clipboard=@($Clipboard.Split([char[]]$Separator).Trim())
  $Clipboard=$Clipboard.Split([string[]]$Separator, [System.StringSplitOptions]::None).Trim()

  foreach ($item in $Clipboard) {  # Only add non-empty objects
    if ($item -ne "") {
      Set-ObjectSettings $item
    }
  }

  Set-State

}


function Set-ObjectSettings($ObjectName="", $TaskResult="Pending", $TaskResultExport="Pending",$State="Pending", $Step=0, $NextStep=0, $StepsToSkip=$Null, $Checked=$True, $SequenceID=0, $SequenceName="", $JobID=0, 
                            $Historic=@(), $SharedVariable=$Null, $Color=$ColorSequencesPending, $nbTotalSteps=0, $InProgress=$False, $Bundle=$False, $BundleName="", $BundleMaxThreads="N/A", $FromFile=$Null, 
                            $CellFontFormated=$False, $CellFontFamily=$FontDefaultFamily, $CellFontColor=$FontDefaultColor, $CellFontSize=$FontDefaultSize, $CellFontStyle=$FontDefaultStyle, $CellFontWeight=$FontDefaultWeight, 
                            $Hidden=$False, $AssignToExistingItem=$False, $GridItemTag=$($ObjectsTabControl.SelectedItem.Tag), $Transcript=$False, $AddParams=$Null) {

  # Set the properties to an exisiting object, or create a new object

  $Script:UniqueID++

  $Obj=New-Object -TypeName GridObject
  $Obj.Objects=$ObjectName
  $Obj.TaskResults=$TaskResult
  $Obj.TaskResultsExport=$TaskResultExport
  $Obj.LastTaskResults="-"
  $Obj.State=$State
  $Obj.Step=$Step
  $Obj.NextStep=$NextStep
  $Obj.StepToString=$Step.ToString()
  $Obj.StepsToSkip=$StepsToSkip
  $Obj.IsChecked=$Checked
  $Obj.SequenceID=$SequenceID
  $Obj.SequenceName=$SequenceName
  $Obj.JobID=$JobID
  $Obj.Historic=$Historic
  $Obj.TaskHistory=@()
  $Obj.Paused=$False
  $Obj.TimeRemaining=""
  $Obj.Runspace=$Null
  $Obj.SharedVariable=$SharedVariable
  $Obj.Color=$Color
  $Obj.ColorTemp=$Null
  $Obj.UniqueID=$UniqueID
  $Obj.nbTotalSteps=$nbTotalSteps
  $Obj.nbTotalStepsToString=$nbTotalSteps.ToString()
  $Obj.InProgress=$InProgress
  $Obj.IsEnabled=$True
  $Obj.Bundle=$Bundle
  $Obj.BundleName=$BundleName
  $Obj.BundleMaxThreads=$BundleMaxThreads
  $Obj.BundleNameAndThreads=$Obj.BundleName + " (" + $Obj.BundleMaxThreads + ")"
  $Obj.FromFile=$FromFile
  $Obj.CellFontFormated=$CellFontFormated
  $Obj.CellFontFamily=$CellFontFamily
  $Obj.CellFontColor=$CellFontColor
  $Obj.CellFontSize=$CellFontSize
  $Obj.CellFontStyle=$CellFontStyle
  $Obj.CellFontWeight=$CellFontWeight
  $Obj.WrapText=$WrapText
  $Obj.Hidden=$Hidden
  $Obj.Tab=$GridItemTag
  $Obj.Transcript=$Transcript
  $Obj.TasksTimedOut=@()
  if ($AddParams -eq $Null) {
    $Obj.AddParams=@()
    if ($TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag] -ne 0) { 
      for($i=0;$i -lt $TabObjectAdditionalParams[$ObjectsTabControl.SelectedItem.Tag]; $i++) {
        $Obj.AddParams+=""
      }
      if (@($AddParams).Count -gt $TabObjectAdditionalParams[$GridItemTag]) { $Script:TabObjectAdditionalParams[$GridItemTag]=@($AddParams).Count }
    }
  }
  else {
    $Obj.AddParams=$AddParams
  }

  if ($AssignToExistingItem) {  # An object is already existing: don't add it
    return $obj
  }

  $Script:DataGridItemSource[$GridItemTag].Add($Obj)  # Add the newly created object to the items source

}


function Set-QuerySequenceVariables {

  # Query the value of each variable defined in the current loaded sequence

  Create-LabelInSequence "" "Blue" "Normal" 12 -8
  $Script:SequenceFullPath=$SequenceLoaded.SequenceFullPath

  $SequenceLoaded.Variable | ForEach-Object { Set-Variable -Name ($_.Name) -Value $Null }
  foreach ($var in $SequenceLoaded.Variable) {
    $Script:ConditionValue=$Null
    $TypePos=$VariableTypes.IndexOf($var.Type.ToLower())  # Determine the index in $VariableTypes of the variable type: the position is set in the function Set-Startup_SeqVariables
    $VariableTextValue=$var.Text
    $SequenceLoaded.Variable | ForEach-Object { Set-Variable -Name ($_.Name) -Value ($_.Value) }  # Reload the variables, in case they are needed in some conditions
    try {  # Check the Condition
      $ConditionValueExp=Invoke-Expression $var.condition
    }
    catch {
      $ConditionValueExp=$False
      if ($DebugMode -eq 1) { 
        Write-Host "`n Error with condition in sequence: (Variable: $($var.name)) $($var.condition)" 
      }
    }

    if ($ConditionValueExp -eq $False) {  # If the condition is false, skip to next variable
      $var.Value=$Null
      continue
    }

    if ($ConditionValueExp -ne $True) { # The Condition Value returned a non-boolean
      $Script:ConditionValue=$ConditionValueExp
    }

    $VariableQuery=Invoke-Expression -Command $VariableCommand[$TypePos]  # Execute the command associated to the index above and store the result in $VariableQuery
    if ($VariableQuery -eq "") {  # Query cancelled
      MessageBox "Variable - $($var.Type)" "  Process cancelled  " 3 1
      Set-VariableClear
      $Script:ConditionValue=$Null
      return $False
    }
    $var.Value=$VariableQuery
    # Check if the variable is a secret
    switch ($var.Type) {
      "secretinputbox" { Create-LabelInSequence -SequenceLabel "$($var.Name): xxxxxxxx" -Color "Blue" -FontStyle "Normal" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) ; break }
      "credentialbox" { Create-LabelInSequence -SequenceLabel "$($var.Name): $($var.Value[0])/xxxxxx" -Color "Blue" -FontStyle "Normal" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) ; break }
      "credentials" { Create-LabelInSequence -SequenceLabel "$($var.Name): credentials" -Color "Blue" -FontStyle "Normal" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) ; break }
      default { Create-LabelInSequence -SequenceLabel "$($var.Name): $($var.Value)" -Color "Blue" -FontStyle "Normal" -FontSize 12 -MarginUp -8 -PanelSize $($var.PanelSize) }
    }
  }

  $Script:ConditionValue=$Null
  return $True

}


function Set-QuerySequenceVariablesBundle($BundleObjectsInStandby) {

  # Query variables for objects in bundles

  $BundleIDs=$BundleObjectsInStandby | Select-Object -ExpandProperty SequenceID -Unique

  foreach ($Id in $BundleIDs) {  # Loops in all bundles

    if ($SequenceSettings[$Id].Parameter.Warning -eq $True) {  # Ask for start confirmation if a warning is set
      filter myFilter { if ($_.SequenceID -eq $Id) { $_ } }
      $nbObjects=@($BundleObjectsInStandby | myFilter).Count
      $ReallyDeploy=Read-StartSequence $SequenceSettings[$Id].Name $nbObjects
      if ($ReallyDeploy -ne "OK") {
        filter myFilter { if ($_.SequenceID -eq $Id) { $_ } }
        $ObjectsToCancel=$BundleObjectsInStandby | myFilter
        Set-CancelBundle $ObjectsToCancel
        continue
      }
    }

    if ($SequenceSettings[$Id].Parameter.SecurityCode -ne "") {  # Ask for start security code if set
      $CodePrompt=Read-SecurityCode $SequenceSettings[$Id].Parameter.SecurityCode $SequenceSettings[$Id].Name
      if ($CodePrompt -ne "OK") {
        filter myFilter { if ($_.SequenceID -eq $Id) { $_ } }
        $ObjectsToCancel=$BundleObjectsInStandby | myFilter
        Set-CancelBundle $ObjectsToCancel
        continue
      }
    }

    if ($SequenceSettings[$Id].Parameter.Message -ne "") {  # A Message has to be displayed
      MessageBox "Sequence Information" $($SequenceSettings[$Id].Parameter.Message) 1 1
    }

    $PreLoadUsed=$SequenceSettings[$Id].Task | Where-Object Type -eq "PreLoad"
    if ([string]::IsNullOrEmpty($SequenceSettings[$Id].Variable) -eq $False -or $PreLoadUsed) {  # Variables have been already defined or a PreLoad is present
      if (!($PreLoadUsed)) {
        if (($SequenceSettings[$Id].Variable | Select-Object -First 1).Value -ne $null) {  # The first and therefore all variables have already been set
          $ReloadVariables=(MessageBox "WARNING" "Variables have been already defined for ""$($SequenceSettings[$Id].Name)""`r`nDo you want to reuse them ?" 4 2)
          if ($ReloadVariables -eq "yes") { continue }
        }
      }
      Set-DisplaySequence $Id
      Set-VariableClear
      $QuerySequenceVariablesValidated=""
      $QuerySequenceVariablesValidated=Set-QuerySequenceVariablesToSequence $Id  # Query the variables again
      if ($QuerySequenceVariablesValidated -notcontains $True) {  # The variable query has been cancelled, the sequence restart is stopped
        filter myFilter { if ($_.SequenceID -eq $Id) { $_ } }
        $ObjectsToCancel=$BundleObjectsInStandby | myFilter
        Set-CancelBundle $ObjectsToCancel
        continue
      }
    }

  }

}


function Set-QuerySequenceVariablesToSequence($SeqIndex) {

  # Query the value of each variable defined in a specific sequence

  Create-LabelInSequence ""
  $Script:SequenceFullPath=$SequenceSettings[$SeqIndex].SequenceFullPath

  $SequenceSettings[$SeqIndex].Variable | ForEach-Object { Set-Variable -Name ($_.Name) -Value $Null }


  foreach ($var in $SequenceSettings[$SeqIndex].Variable) {
    $Script:ConditionValue=$Null
    $TypePos=$VariableTypes.IndexOf($var.Type.ToLower())  # Determine the index in $VariableTypes of the variable type: the position is set in the function Set-Startup_SeqVariables
    $VariableTextValue=$var.Text
    $SequenceSettings[$SeqIndex].Variable | ForEach-Object { Set-Variable -Name ($_.Name) -Value ($_.Value) }  # Reload the variables, in case they are needed in some conditions
    try {  # Check the Condition
      $ConditionValueExp=Invoke-Expression $var.condition
    }
    catch {
      $ConditionValueExp=$False
      if ($DebugMode -eq 1) { 
        Write-Host "`n Error with condition in sequence: (Variable: $($var.name)) $($var.condition)" 
      }
    }

    if ($ConditionValueExp -eq $False) {  # If the condition is false, skip to next variable
      $var.Value=$Null
      continue
    }

    if ($ConditionValueExp -ne $True) { # The Condition Value returned a non-boolean
      $Script:ConditionValue=$ConditionValueExp
    }

    $VariableQuery=Invoke-Expression -Command $VariableCommand[$TypePos]  # Execute the command associated to the index above and store the result in $VariableQuery
    if ($VariableQuery -eq "") {  # Query cancelled
      MessageBox "Variable - $($var.Type)" "  Process cancelled  " 3 1
      Set-VariableClear
      return $False
    }
    $var.Value=$VariableQuery
    # Check if the variable is a secret
    switch ($var.Type) {
      "secretinputbox" { Create-LabelInSequence "$($var.Name): xxxxxxxx" "Blue" "Normal" 12 -8 ; break }
      "credentialbox" { Create-LabelInSequence "$($var.Name): $($var.Value[0])/xxxxxx" "Blue" "Normal" 12 -8 ; break }
      "credentials" { Create-LabelInSequence "$($var.Name): credentials" "Blue" "Normal" 12 -8 ; break }
      default { Create-LabelInSequence "$($var.Name): $($var.Value)" "Blue" "Normal" 12 -8 }
    }
  }

  return $True

}


function Set-RemoveFromExistingBundle($BundleToRemoveFrom) {

  # Remove objects from a Bundle

  filter myFilter1 { if ($_.Item.GetType().Name -eq "GridObject") { $_ } }
  filter myFilter2 { if ($_.BundleName -eq $BundleToRemoveFrom) { $_ } }
  $AllObjectsInBundle=$ObjectsTabControl.SelectedItem.Content.SelectedCells | myFilter1 | Select-Object -ExpandProperty item  | myFilter2

  foreach ($Obj in $AllObjectsInBundle) {  # Reset the objects to Pending
    $Obj.TaskResults="Pending"
    $Obj.TaskResultsExport=$Obj.TaskResults
    $Obj.LastTaskResults="-"
    $Obj.State="Pending"
    $Obj.Step=0
    $Obj.StepToString="0"
    $Obj.StepsToSkip=$Null
    $Obj.IsChecked=$True
    $Obj.IsEnabled=$True
    $Obj.SequenceID=0
    $Obj.SequenceName=""
    $Obj.JobID=0
    $Obj.Historic=@()
    $Obj.TaskHistory=@()
    $Obj.Paused=$False
    $Obj.TimeRemaining=""
    $Obj.Runspace=$Null
    $Obj.SharedVariable=$Null
    $Obj.Color=$ColorSequencesPending
    $Obj.UniqueID=$UniqueID
    $Obj.nbTotalSteps=0
    $Obj.nbTotalStepsToString="0"
    $Obj.InProgress=$False
    $Obj.Bundle=$False
    $Obj.BundleName=""
    $Obj.BundleMaxThreads="N/A"
    $Obj.BundleNameAndThreads=$Obj.BundleName + " (" + $Obj.BundleMaxThreads + ")"
    $Obj.FromFile=$Null
    $Obj.CellFontFormated=$False
    $Obj.CellFontFamily=$FontDefaultFamily
    $Obj.CellFontColor=$FontDefaultColor
    $Obj.CellFontSize=$FontDefaultSize
    $Obj.CellFontStyle=$FontDefaultStyle
    $Obj.CellFontWeight=$FontDefaultWeight
    $Obj.TasksTimedOut=@()
  }

  $Script:AllBundle=@()
  foreach ($dgis in $DataGridItemSource) {  # Get the name of all Bundles in use
    filter myFilter { if ($_.Bundle -eq $True) { $_ } }
    $Script:AllBundle+=$dgis | myFilter | Select-Object -ExpandProperty BundleName -Unique 
  }

  Check-Bundle  # Check the Bundles in use
  Set-State

  if ($UseClassicMenu -eq "False") {  # Actualize the Bundle menu
    RibbonSetBundle
  }
  else {
    ClassicMenuSetBundle
  }

}


function Set-StartButtonState {

  # Enable or disable the Start button

  if ($TabMoving) { return }

  filter Myfilter { if (($_.Hidden -eq $False) -and ($_.IsChecked -eq $True) -and ($_.InProgress -eq $False)) { $_ } }
  $ObjectsReady=$ObjectsTabControl.SelectedItem.Content.ItemsSource | Myfilter  # Get the objects ready to start

  filter Myfilter { if ($_.Bundle -eq $True) { $_ } }
  $BundleReady=$ObjectsReady | Myfilter  # Determine if bundles are ready to start

  if (@($BundleReady).Count -gt 0) {
    $StartButton.IsEnabled=$True
    $StartButton.Opacity="1"
    return
  }

  if ($SequencesTreeView.SelectedItem -eq $Null) {  # No sequence selected
    $StartButton.IsEnabled=$False
    $StartButton.Opacity="0.2"
    return
  }

  if ($SequencesTreeView.SelectedItem.HasItems) {  # Not a leaf is selected
    $StartButton.IsEnabled=$False
    $StartButton.Opacity="0.2"
    return
  }

  if ($SequenceLoaded -eq $Null) {  # No sequence loaded or the sequence loaded is wrong
    $StartButton.IsEnabled=$False
    $StartButton.Opacity="0.2"
    return
  }
  
  filter Myfilter { if ($_.Bundle -eq $False) { $_ } }
  $FreeReady=$ObjectsReady | Myfilter  # Check if objects are free and ready to start
  if (@($FreeReady).Count -gt 0) {
    $StartButton.IsEnabled=$True
    $StartButton.Opacity="1"
    return
  }

  $StartButton.IsEnabled=$False
  $StartButton.Opacity="0.2"

}


function Set-Startup_GlobalVariables($Invocation) {

  Set-Location $PSScriptRoot  # Set the current directory to the Hydra path

  # Define global varibales

  New-Variable -Name PSScriptName -Value $($Invocation.MyCommand.Name) -Scope Script -Force
  New-Variable -Name HydraBinPath -Value $PSScriptRoot -Scope Script -Force
  New-Variable -Name MyScriptInvocation -Value $Invocation -Scope Script -Force
  New-Variable -Name HydraSettingsPath -Value "$PSScriptRoot\Settings" -Scope Script -Force
  New-Variable -Name HydraGUIPath -Value "$PSScriptRoot\GUI" -Scope Script -Force
  New-Variable -Name HydraDocsPath -Value "$PSScriptRoot\Docs" -Scope Script -Force
  New-Variable -Name HydraCustomPath -Value "$PSScriptRoot\Custom" -Scope Script -Force
  New-Variable -Name SequencesListPath -Value @() -Scope Script -Force
  New-Variable -Name DisableManualSequence -Value $False -Scope Script -Force
  New-Variable -Name HydraAddonsList -Value @() -Scope Script -Force

}


function Set-Startup {

  # Pre-Checks and global variables definition

  if ($Profile -ne "") {
    $pat="^[a-zA-Z0-9]+$"
    if (!($Profile -match $pat)) {
      [void][System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
      MessageBox "Hydra" "Please specify a profile name only composed of letters and numbers.`n`rDon't use any special characters." 3 1 $False
      exit
    }
  }

  if ($Host.Version.Major -lt 4) {  # The Powershell version is lower than 4: exit
    [void][System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms")
    MessageBox "Hydra" "You need Powershell 4 or higher to run this version of Hydra.`n`r`n`rPlease install a newer version." 3 1 $False
    exit
  }

  if ($AutoRun -eq $False) {  ####

    if (!(Test-Path 'HKCU:\Software\Hydra')) {  # Create the Hydra registry structure if it's missing
      New-Item -Path 'HKCU:\Software' -Name Hydra | Out-Null
    }

    if (!(Test-Path 'HKCU:\Software\Hydra\7') -and (Test-Path 'HKCU:\Software\Hydra\6')) {
      $ImportV6Settings=MessageBox "Hydra" "Settings of Hydra 6 have been found.`n`rDo you want to import them in Hydra 7 ?" 4 2 $False
      if ($ImportV6Settings -eq "Yes") {
        try {
          Copy-Item 'HKCU:\Software\Hydra\6' -Destination 'HKCU:\Software\Hydra\7' -Recurse -ErrorAction Stop
        }
        catch {
          MessageBox "Hydra" "The import of the Hydra 6 settings has failed.`n`rDefault settings will be applied." 2 1 $False
        }
      }
    }

    if (!(Test-Path 'HKCU:\Software\Hydra\7')) {  # Create the Hydra6 registry subkey if it's missing
      New-Item -Path 'HKCU:\Software\Hydra' -Name 7 | Out-Null
    }
  
    if ($Profile -ne "") {
      if (!(Test-Path "HKCU:\Software\Hydra\7\$Profile")) {  # Create the Profile registry subkey if it's missing and necessary
        New-Item -Path 'HKCU:\Software\Hydra\7' -Name $Profile | Out-Null
      }
      $Script:HydraRegPath="HKCU:\Software\Hydra\7\$Profile"
    }
    else {
      $Script:HydraRegPath="HKCU:\Software\Hydra\7"
    }

    if ($SequencesListParam -ne $Null) {  # Hydra has been started with a Sequences List as parameter
      $Script:SequencesListPath+=$SequencesListParam  # Set the global variable SequencesListPath with this parameter
      $SkipGroupCheck=$True  # If a sequence is set, the groups check is skipped
    }

    if ($SkipGroupCheck -eq $False) {  # Check if the user is in a known group and assign the sequence
      if (Test-Path "$HydraSettingsPath\Hydra_GroupsMembership.gm") {
        $UserId=[Security.Principal.WindowsIdentity]::GetCurrent()  # Enumarate the groups of the user
        $UserGroups=$UserId.Groups | ForEach-Object { $_.Translate([Security.Principal.NTAccount]) }
        $GroupsMembership=Import-Csv -Delimiter ";" -Path "$HydraSettingsPath\Hydra_GroupsMembership.gm" -Header Group, Sequence, DisableManualSequence
        foreach ($item in $GroupsMembership) {
          if ($item.Group -in $UserGroups) {
            $Script:SequencesListPath+=$item.Sequence
          }
          if ($item.DisableManualSequence -eq "1") {  # Deactivate the Menu options "Load a sequence manually" and "Load a sequence list"
            $Global:DisableManualSequence=$True
          }
        }
      }
    }

    if (@($SequencesListPath).Count -eq 0) {
      $Script:SequencesListPath+="$HydraSettingsPath\Hydra_Sequences.lst"
    }
  
    $ErrorMsg=@()
    $SeqListFound=$False
    $NewSequencesListPath=@()
    foreach ($SequencesList in $SequencesListPath) {
      if (Test-Path $SequencesList) {
        $SeqListFound=$True
        $NewSequencesListPath+=$SequencesList
      }
      elseif (Test-Path "$HydraSettingsPath\$SequencesList") {
        $SeqListFound=$True
        $NewSequencesListPath+="$HydraSettingsPath\$SequencesList"
      }
      else {
        $ErrorMsg+=$SequencesList
      }
    }

    if (@($ErrorMsg).Count -ne 0) {  # Some Sequence paths were not found
      if ($SeqListFound -eq $False) {  # No sequence list found at all
        $LoadSeq=MessageBox "Hydra" "Unable to find the Sequences List(s):`r`n$($SequencesListPath -join "`r`n")`r`n`r`nDo you want to load one manually ?`r`n`r`n`r`n" 4 2 $False
        if ($LoadSeq -eq "No") {  # No Sequences List to load
          exit
        }
        $LoadSeqPath=Read-OpenFileDialog "Sequences List" $HydraSettingsPath "Sequences Lists (*.lst)|*.lst|All files (*.*)|*.*"
        if ($LoadSeqPath -eq "") {  # No Sequences List selected
          exit
        }
        else {  # Set the file selected as new Sequences List
          New-Variable -Name SequencesListPath -Value @() -Scope Script -Force
          $Script:SequencesListPath+=$LoadSeqPath
        }
      }
      else {  # Only some Sequence Lists were not found: just warn
        $Script:SequencesListPath=$NewSequencesListPath
        MessageBox "Hydra" "Some Sequences List(s) were not found:`r`n$($ErrorMsg -join "`r`n")`r`n`r`n" 2 1 $False
      }
    }
    else {
      $Script:SequencesListPath=$NewSequencesListPath
    }

  }

  else {  # Autorun -eq $False

    if ($Profile -ne "") {
      if (!(Test-Path "HKCU:\Software\Hydra\7\$Profile")) {  # Create the Profile registry subkey if it's missing and necessary
        $Script:HydraRegPath="HKCU:\Software\Hydra\7\$Profile"
      }
    }
    else {
      $Script:HydraRegPath="HKCU:\Software\Hydra\7"
    }

  }

  Set-DefaultSettings  # Set the default variables settings
  Get-RegistrySettings  # Get registry values and replace the default ones defined in the steps before
  Set-Startup_SeqVariables  # Set the variables types
  $Script:LiveStatus=[hashtable]::Synchronized(@{})  # Set the hashtable for the Live Status messages

  Set-LogFile $True

}


function Set-Startup_SeqVariables {

  # Define the variables types

  $Script:nbVariableTypes=15
  $Script:SeqVariableHash=@(0)*($nbVariableTypes+1)
  $Script:VariableCommand=@(0)*($nbVariableTypes+1)

  # Define the names of the variables that can be used in a .sequence.xml
  $Script:VariableTypes=@("", "inputbox", "multilineinputbox", "selectfile", "selectfolder", "combobox", "multicheckbox", "credentials", "secretinputbox", "credentialbox", "multiinputboxes", "selectdate", "selecttime", "selectdatetime", "custom", "cancel")

  # Create a script block based on a command to any of the variable types. It will pass $SeqVariables defined by the user
  $Script:VariableCommand[1]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null -or $var.DefaultValue -ne $Null) {  # New format
      Read-InputBoxDialog -WindowTitle $($var.Title) -Message $($var.Message) -DefaultText $($var.DefaultValue)
      return
    }
    if ($VariableTextValue -eq $null) { Read-InputBoxDialog ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-InputBoxDialog }
      1 { Read-InputBoxDialog $VariableTextValue.Split(';')[0] }
      2 { Read-InputBoxDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-InputBoxDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] }
    }
'@
  $Script:VariableCommand[2]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null -or $var.DefaultValue -ne $Null) {  # New format
      Read-MultiLineInputBoxDialog -WindowTitle $($var.Title) -Message $($var.Message) -DefaultText $($var.DefaultValue)
      return
    }
    if ($VariableTextValue -eq $null) { Read-MultiLineInputBoxDialog ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-MultiLineInputBoxDialog }
      1 { Read-MultiLineInputBoxDialog $VariableTextValue.Split(';')[0] }
      2 { Read-MultiLineInputBoxDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-MultiLineInputBoxDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] }
    }
'@
  $Script:VariableCommand[3]=@'
    if ($var.Title -ne $Null -or $var.path -ne $Null -or $var.filetype -ne $Null) {  # New format
      Read-OpenFileDialog -WindowTitle $($var.Title) -InitialDirectory $($var.Path) -Filter $($var.filetype)
      return
    }
    if ($VariableTextValue -eq $null) { Read-OpenFileDialog ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-OpenFileDialog }
      1 { Read-OpenFileDialog $VariableTextValue.Split(';')[0] }
      2 { Read-OpenFileDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
      3 { Read-OpenFileDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] }
      {$_ -ge 4} { Read-OpenFileDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] $VariableTextValue.Split(';')[3] }
    }
'@
  $Script:VariableCommand[4]=@'
    if ($var.Path -ne $Null) {  # New format
      fBrowse-Folder_Modern -SelectedPath $($var.Path) 
      return
    }
    if (($VariableTextValue -eq $null) -or ($VariableTextValue -eq "")) { fBrowse-Folder_Modern ; return }
    fBrowse-Folder_Modern $VariableTextValue
'@
  $Script:VariableCommand[5]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      if ($var.Path -ne $Null) {
        Read-ComboBoxDialog -WindowTitle $($var.Title) -Message $($var.Message) -Path $($var.Path) -Entries $Null -DisplaySeparator $($var.DisplaySeparator)
        return
      }
      if ($var.Items -ne $Null) {
        Read-ComboBoxDialog -WindowTitle $($var.Title) -Message $($var.Message) -Items $($var.Items) -Entries $Null -DisplaySeparator $($var.DisplaySeparator)
        return
      }
    }
    if ($VariableTextValue -eq $null) { Read-ComboBoxDialog ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-ComboBoxDialog }
      1 { Read-ComboBoxDialog $VariableTextValue.Split(';')[0] }
      2 { Read-ComboBoxDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-ComboBoxDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] }
    }
'@
  $Script:VariableCommand[6]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      if ($var.Path -ne $Null) {
        Read-MultiCheckboxList -WindowTitle $($var.Title) -Message $($var.Message) -Path $($var.Path) -Entries $Null -DisplaySeparator $($var.DisplaySeparator)
        return
      }
      if ($var.Items -ne $Null) {
        Read-MultiCheckboxList -WindowTitle $($var.Title) -Message $($var.Message) -Items $($var.Items) -Entries $Null -DisplaySeparator $($var.DisplaySeparator)
        return
      }
    }
    if ($VariableTextValue -eq $null) { Read-MultiCheckboxList ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-MultiCheckboxList }
      1 { Read-MultiCheckboxList $VariableTextValue.Split(';')[0] }
      2 { Read-MultiCheckboxList $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
      3 { Read-MultiCheckboxList $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] }
      {$_ -ge 4} { Read-MultiCheckboxList $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] $VariableTextValue.Split(';')[3] }
    } 
'@
  $Script:VariableCommand[7]=@'
    if ($var.Message -ne $Null) {  # New format
      Read-Credentials -Message $($var.Message)
      return
    }
    if ($VariableTextValue -eq $null) { Read-Credentials ; return }
    Read-Credentials $VariableTextValue
'@
  $Script:VariableCommand[8]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      Read-InputDialogBoxSecret -WindowTitle $($var.Title) -Message $($var.Message) -DefaultText $($var.DefaultValue)
      return
    }
    if ($VariableTextValue -eq $null) { Read-InputDialogBoxSecret ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-InputDialogBoxSecret }
      1 { Read-InputDialogBoxSecret $VariableTextValue.Split(';')[0] }
      2 { Read-InputDialogBoxSecret $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-InputDialogBoxSecret $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] }
    }
'@
  $Script:VariableCommand[9]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      Read-Credentialbox -WindowTitle $($var.Title) -Message $($var.Message)
      return
    }
    if ($VariableTextValue -eq $null) { Read-Credentialbox ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-Credentialbox }
      1 { Read-Credentialbox $VariableTextValue.Split(';')[0] }
      {$_ -ge 2} { Read-Credentialbox $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
    }
'@
  $Script:VariableCommand[10]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      if ($var.Path -ne $Null) {
        Read-MultiInputBoxesDialog -WindowTitle $($var.Title) -Message $($var.Message) -Path $($var.Path) -Entries $Null
        return
      }
      if ($var.Items -ne $Null) {
        Read-MultiInputBoxesDialog -WindowTitle $($var.Title) -Message $($var.Message) -Items $($var.Items) -Entries $Null
        return
      }
    }
    if ($VariableTextValue -eq $null) { Read-MultiInputBoxesDialog ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-MultiInputBoxesDialog }
      1 { Read-MultiInputBoxesDialog $VariableTextValue.Split(';')[0] }
      2 { Read-MultiInputBoxesDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-MultiInputBoxesDialog $VariableTextValue.Split(';')[0] $VariableTextValue.Split(';')[1] $VariableTextValue.Split(';')[2] }
    } 
'@
  $Script:VariableCommand[11]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      $RetObj=($var.returntype -eq "object")
      Read-DateTimePicker -Type "Date" -WindowTitle $($var.Title) -Message $($var.Message) -ReturnObject $RetObj
      return
    }
    if ($VariableTextValue -eq $null) { Read-DateTimePicker -Type "Date" ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-DateTimePicker -Type "Date" }
      1 { Read-DateTimePicker -Type "Date" -WindowTitle $VariableTextValue.Split(';')[0] }
      2 { Read-DateTimePicker -Type "Date" -WindowTitle $VariableTextValue.Split(';')[0] -Message $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-DateTimePicker -Type "Date" -WindowTitle $VariableTextValue.Split(';')[0] -Message $VariableTextValue.Split(';')[1] -ReturnObject $VariableTextValue.Split(';')[2] }
    } 
'@
  $Script:VariableCommand[12]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      $RetObj=($var.returntype -eq "object")
      Read-DateTimePicker -Type "Time" -WindowTitle $($var.Title) -Message $($var.Message) -ReturnObject $RetObj
      return
    }
    if ($VariableTextValue -eq $null) { Read-DateTimePicker -Type "Time" ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-DateTimePicker -Type "Time" }
      1 { Read-DateTimePicker -Type "Time" -WindowTitle $VariableTextValue.Split(';')[0] }
      2 { Read-DateTimePicker -Type "Time" -WindowTitle $VariableTextValue.Split(';')[0] -Message $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-DateTimePicker -Type "Time" -WindowTitle $VariableTextValue.Split(';')[0] -Message $VariableTextValue.Split(';')[1] -ReturnObject $VariableTextValue.Split(';')[2] }
    } 
'@
  $Script:VariableCommand[13]=@'
    if ($var.Title -ne $Null -or $var.Message -ne $Null) {  # New format
      $RetObj=($var.returntype -eq "object")
      Read-DateTimePicker -Type "DateTime" -WindowTitle $($var.Title) -Message $($var.Message) -ReturnObject $RetObj
      return
    }
    if ($VariableTextValue -eq $null) { Read-DateTimePicker -Type "DateTime" ; return }
    switch ($VariableTextValue.Split(';').Count) {
      0 { Read-DateTimePicker -Type "DateTime" }
      1 { Read-DateTimePicker -Type "DateTime" -WindowTitle $VariableTextValue.Split(';')[0] }
      2 { Read-DateTimePicker -Type "DateTime" -WindowTitle $VariableTextValue.Split(';')[0] -Message $VariableTextValue.Split(';')[1] }
      {$_ -ge 3} { Read-DateTimePicker -Type "DateTime" -WindowTitle $VariableTextValue.Split(';')[0] -Message $VariableTextValue.Split(';')[1] -ReturnObject $VariableTextValue.Split(';')[2] }
    } 
'@
  $Script:VariableCommand[14]=@'
    if ($var.vartype -ne $Null -and $var.varvalue -ne $Null) {  # New format
      try {
        if ($var.vartype -eq "string" -or $var.vartype -eq "boolean") {
          $var.varvalue=$var.varvalue -f $ConditionValue
          $VarRet=$($(Invoke-Expression '$var.varvalue') -as ($var.vartype -as [type]))
        }
        elseif ($var.vartype -eq "invoke") {
          $VarRet=$(Invoke-Expression $var.varvalue)
        }
        else {
          $VarRet=$($(Invoke-Expression $var.varvalue) -as ($var.vartype -as [type]))
        }
      }
      catch { 
        if ($DebugMode -eq 1) { 
          write-host "Error with the syntax of the variable custom" 
        }
        $VarRet=$Null 
      }
      return $VarRet
    }

    $VariableTextValueSplit=$VariableTextValue -split ";",2
    if ($VariableTextValueSplit[0] -eq "string" -or $VariableTextValueSplit[0] -eq "boolean") {
      if (($VariableTextValueSplit[1].trim()[0] -eq "'" -and $VariableTextValueSplit[1].trim()[-1] -eq "'") -or ($VariableTextValueSplit[1].trim()[0] -eq '"' -and $VariableTextValueSplit[1].trim()[-1] -eq '"')) {
        # Nothing to do
      }
      else {
        $VariableTextValueSplit[1]='"' + $VariableTextValueSplit[1] + '"'
      }
    }
    if ($VariableTextValueSplit.Count -ne 2) { return $null }
    try {
      if ($VariableTextValueSplit[0] -eq "invoke") {
        $VarRet=$(Invoke-Expression $VariableTextValueSplit[1])
      }
      else {
        $VarRet=$($(Invoke-Expression $VariableTextValueSplit[1]) -as ($VariableTextValueSplit[0] -as [type]))
      }
    }
    catch { 
      if ($DebugMode -eq 1) { 
        write-host "Error with the syntax of the variable custom" 
      }
      $VarRet=$Null 
    }
    return $VarRet
'@
  $Script:VariableCommand[15]=@'
    return ""
'@

}


function Set-State {

  # Update the state of the running objects

  if ($AutoRun -eq $True) { return }  # No update if Autorun, to gain time 

  if ($TabMoving) { return }

  filter Myfilter { if ( $_.ToString() -ne "{NewItemPlaceholder}") { $_ } }

  $view=[System.Windows.Data.CollectionViewSource]::GetDefaultView($ObjectsTabControl.SelectedItem.Content.ItemsSource) | Myfilter

  filter Myfilter { if ( $_.IsChecked -eq $True ) { $_ } }
  $oSelected=@($view | Myfilter).Count

  filter Myfilter { if ( $_.InProgress -eq $True ) { $_ } }
  $oRemaining=@($view | Myfilter).Count

  filter Myfilter { if ( $_.Step -ne 0 ) { $_ } }
  $oRunning=@($view | Myfilter).Count 

  if ($oRemaining -eq 0) {
    $tbStatus.Text="Selected: $oSelected"
    $ObjectsCounting[$ObjectsTabControl.SelectedItem.Content.Tag]=0
  }
  else {
    $tbStatus.Text="Selected: $oSelected, Running: $oRunning, Done: $($ObjectsCounting[$ObjectsTabControl.SelectedItem.Content.Tag]), Remaining: $oRemaining"
  }

  Set-StartButtonState

}


function Set-Timer {

  # Start the timer used to get a responsive GUI and get the state of the runspaces at every interval
 
  $Timer.Stop()
  $Timer.Interval=$TimerInterval
  $Timer.Start()

}


function Set-VariableClear {

  # Clean up the variables part in the sequence panel
  
  $VarSet=$SequenceStepsStackPanel.Children | Where-Object { $_.Margin.Top -eq -8 }
  foreach ($vs in $VarSet) { $SequenceStepsStackPanel.Children.Remove($vs) }

}


function Set-WrapCells($Selection=$False, $WrapStyle) {

  # Apply cell wrapping to all or selected objects

  filter myFilter { if ($_.ToString() -ne "{NewItemPlaceholder}") { $_ } }
  if ($Selection -eq $True) {
    $ObjectsTabControl.SelectedItem.Content.SelectedCells | Select-Object -ExpandProperty Item | myFilter | ForEach-Object { $_.WrapText=$WrapStyle }
  }
  else {
    $ObjectsTabControl.SelectedItem.Content.Items | myFilter | ForEach-Object { $_.WrapText=$WrapStyle }
  }

}


function Start-Sequence {

  # Start all objects pending

  Set-AssignSequence  # Assign the current loaded sequence to the free objects

  filter myFilter { if (($_.Hidden -eq $False) -and ($_.IsChecked -eq $True) -and ($_.InProgress -eq $False) -and ($_.Bundle -eq $True)) { $_ } }
  $BundleInStandby=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter  # Determine the objects in Bundle to start
  if (@($BundleInStandby).Count -gt 0) {  # Some objetcs in bundle are pending
    Set-QuerySequenceVariablesBundle $BundleInStandby
    filter myFilter { if (($_.Hidden -eq $False) -and ($_.IsChecked -eq $True) -and ($_.InProgress -eq $False) -and ($_.Bundle -eq $True)) { $_ } }
    $BundleInStandby=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter  # Determine the objects in Bundle to start, in case some have been cancelled
    $SequenceIDsInBundle=$BundleInStandby | Select-Object -ExpandProperty SequenceID -Unique
    foreach ($Obj in $BundleInStandby) {  # The pending objects in bundles can start
      $Obj.InProgress=$True
      $Obj.IsEnabled=$False
      $Obj.Historic=@()
      $Obj.TaskHistory=@()
    }
    foreach ($ID in $SequenceIDsInBundle) {  # Prepare the sequence for objects in Bundles
      Set-AssignSequence_Runspace $False $ID
      $Script:SequenceSettings[$ID].FirstStep=1  # Set the first step to 1: it may be changed later if the 1st step has to be skipped
    }
  }

  try {  # Identify sequences with schedulers
    filter myFilter { if (($_.Schedule -ne $Null) -and ($_.SchedulerExpired -eq $False)) { $_ } }
    $SequencesScheduled=($SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter).Index  # Determine sequences with timer not currently expired
  }
  catch {
     $SequencesScheduled=@()
  }

  foreach ($SeqSched in $SequencesScheduled) {  # Loop in the sequences with a timer set
    $TimeDiff=New-TimeSpan -Start $(Get-Date) -End $SequenceSettings[$SeqSched].Schedule
    if ($TimeDiff.TotalSeconds -lt 0) {  # Timer expired
      $SequenceSettings[$SeqSched].Schedule=$Null
      $SequenceSettings[$SeqSched].SchedulerExpired=$True
    }
    else {  # Reset the Task Result comment, in case it has been cancelled before
      filter myFilter { if (($_.Hidden -eq $False) -and ($_.SequenceID -eq $SeqSched) -and ($_.Step -eq 0)) { $_ } }
      $ObjectsPending=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter  # Find the objects of the sequence not already running
      foreach ($Obj in $ObjectsPending) {  
        $Obj.TaskResults="Sequence Assigned: $($Obj.SequenceName)"
        $Obj.TaskResultsExport=$Obj.TaskResults
        $Obj.Color=$ColorSequencesPending
      }
    }
  } 

  try {
    filter myFilter { if ($_.SchedulerExpired -eq $True) { $_ } }
    $SequencesExpired=($SequenceSettings[1..$($SequenceSettings.Count-1)] | myFilter).Index  # Determine potential sequences with an expired timer
  }
  catch {
    $SequencesExpired=@()
  }

  foreach ($SeqSched in $SequencesExpired) {  # Loop in the sequences with a timer set
    filter myFilter { if (($_.Hidden -eq $False) -and ($_.SequenceID -eq $SeqSched) -and ($_.InProgress -eq $True) -and ($_.Step -eq 0)) { $_ } }
    $ObjectsPending=$DataGridItemSource[$ObjectsTabControl.SelectedItem.Tag] | myFilter  # Find the objects of the sequence not already running
    foreach ($Obj in $ObjectsPending) {  # Set the results as expired
      $Obj.TimeRemaining="Expired"
      $Obj.InProgress=$False
      $Obj.IsEnabled=$True
      $Obj.TaskResults="CANCELLED - Timer Expired"
      $Obj.TaskResultsExport=$Obj.TaskResults
      $Obj.State="CANCEL at step $($Obj.Step)"
      $Obj.IsChecked=$False
      $Obj.Color=$Colors.Get_Item("CANCELLED")
      $Obj.Step=0
      $Obj.StepToString="0"
      $Obj.TasksTimedOut=@()
    }
    
  }

  if (!($SequenceRunning)) {  # No any sequence currently running
    $Timer.Enabled=$True  # Enable the Timer
    Set-Timer
    if (($UseAutoSave -eq 1) -and ($AutoRun -eq $False) -and ($SequenceAutoSave -eq $True)) {
      $Script:TimerAutoSave.Enabled=$True
      $Script:TimerAutoSave.Start()
    }
  }

  if ($TimerSet -eq $False) {  # Timer not activated
    $Timer.Add_Tick($Get_SequencesState)  # Start $Get_SequencesState at every Tick of the Timer
    $Script:TimerSet=$True
  }

}


function Start-SequenceStep($Object) {

   # Start the next step of the sequence for an object

  $Script:LiveStatus[$Object.Objects]=$Null

  if ([string]::IsNullOrEmpty($Object.Historic)) {  # First Step
    $nowStart=Get-Date -Format "HH:mm:ss"
    $Object.Historic+=$Object.Objects + " - Start on $nowStart"
    if (!($Object.TaskHistory)) {
      $Object.TaskHistory+="Start on $nowStart"
    }    
    $Object.Color=$ColorSequencesRunning
    $Object.TasksTimedOut=@()
  }
  

  if ($Object.Step -in $Object.StepsToSkip) {  # The step has to be skipped
    $Object.TaskResults=$SequenceSettings[$Object.SequenceID].Task[$Object.Step].Comment + " - Step skipped"
    $Object.TaskResultsExport=$Object.TaskResults
    $Object.Historic+="  Step $($Object.Step) - Step skipped"
    $Object.TaskHistory+="Step $($Object.Step) - Step skipped"
    if ($SequenceSettings[$Object.SequenceID].Parameter.SequenceDebug -eq $True) {
      Write-DebugLog "$($Obj.Objects);SKIP;Step $($Obj.Step);Step skipped" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
    }
    return
  }

  $Object.TaskResults=$SequenceSettings[$Object.SequenceID].Task[$Object.Step].Comment  # Print the Step comment in the Task Results 
  $Object.TaskResultsExport=$Object.TaskResults
  if ($SequenceSettings[$Object.SequenceID].Parameter.SequenceDebug -eq $True) {
    Write-DebugLog "$($Obj.Objects);START;Step $($Obj.Step);$($Obj.TaskResultsExport)" $SequenceSettings[$Obj.SequenceID].Parameter.SequenceLog
  }

  $Object.TaskStartedAt=Get-Date

  & $CreateRunspace $Object $SequenceSettings[$Object.SequenceID].Task[$Object.Step].Code  # Create a runspace for the object

}


function Test-Color($Color) {

  # Check if the argument is a color

  try {
    [windows.media.color]$($Color) | Out-Null  # Check if the parameter is a HTML color
    $IsHTMLColor=$True
  }
  catch {
    $IsHTMLColor=$False
  }

  return $IsHTMLColor

}


function Write-DebugLog($Content, $DebugLog) {

  # Write a line in the Sequence Log when set in Debug mode

  $DebugLog="$DebugLog.debug"
  $NewContent=$(Get-Date -Format "dd.MM.yyyy,HH:mm:ss") + ";$Content"
  try {
    Add-Content -Value $NewContent -Path "$DebugLog" #-ErrorAction SilentlyContinue
  }
  catch {
    # Error when writing in the Debug Log: ignore
  }

}


function Write-DebugReceiveOutput($ReceiveOutput) {

  # Debug output if the Receive part is not correct

  if ( (($ReceiveOutput | Get-Member -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -contains 'State') -and (($ReceiveOutput | Get-Member -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name) -contains 'TaskResult') ) { # Extended $HydraReturn object returned
    $ReceiveOutput | Get-Member -type NoteProperty | ForEach-Object {
      $name=$_.Name
      $value=$ReceiveOutput."$($_.Name)"
      Write-Host "Property $name`: $value"
    } 
  }
  else {  # Legacy Return
    for ($i=0; $i -lt $ReceiveOutput.Count; $i++) {
      switch ($i) {
        0 { Write-Host "Value 1 - Status: $($ReceiveOutput[$i])" }
        1 { Write-Host "Value 2 - Result state: $($ReceiveOutput[$i])" }
        2 { Write-Host "Value 3 - Style: $($ReceiveOutput[$i])" }
        3 { Write-Host "Value 4 - Shared value: $($ReceiveOutput[$i])" }
        {$_ -gt 3} { Write-Host "Value $($i+1) - Error: $($ReceiveOutput[$i])" }
      } 
    }
  }

}


function Write-Log {

  # Write the log and the Sequence logs, if any

  for ($i=1; $i -lt $SequenceSettings.Count; $i++) {

    if ($SequenceLog[$i]) {

      try {
        Add-Content -Value $($SequenceLog[$i] -join "`r`n") -Path $LogFilePath -ErrorAction SilentlyContinue
        Add-Content -Value $("-" *40) -Path $LogFilePath -ErrorAction SilentlyContinue
      }
      catch {}

      if (!([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.SequenceLog))) {

        if ($SequenceSettings[$i].Parameter.SequenceLogTimestamp) {
          $Now=Get-Date -Format "yyyyMMdd_HHmmss"
          $SeqLogFile=$([System.IO.Path]::GetDirectoryName($SequenceSettings[$i].Parameter.SequenceLog) + "\" + [System.IO.Path]::GetFileNameWithoutExtension($SequenceSettings[$i].Parameter.SequenceLog) + "_$Now" + [System.IO.Path]::GetExtension($SequenceSettings[$i].Parameter.SequenceLog))
        }
        else {
          $SeqLogFile=$SequenceSettings[$i].Parameter.SequenceLog
        }
        try {
          Add-Content -Value $($SequenceLog[$i] -join "`r`n") -Path $SeqLogFile -ErrorAction SilentlyContinue
        }
        catch {
          Write-Host "Error writing the log"
        }
      }

      if ($SequenceSettings[$i].Parameter.SendMail -eq $True) {  # To Move in Log
        $parameters=@{
          SmtpServer=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailServer"])) { $EMailSMTPServer } else { $SequenceSettings[$i].Parameter.MailOptions["MailServer"] }
          From=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailFrom"])) { $EMailSendFrom } else { $SequenceSettings[$i].Parameter.MailOptions["MailFrom"] }
          To=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailTo"])) { $EMailSendTo } else { $SequenceSettings[$i].Parameter.MailOptions["MailTo"] }
          Port=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailServerPort"])) { $EMailSMTPPort } else { $SequenceSettings[$i].Parameter.MailOptions["MailServerPort"] }
          UseSSL=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailUseSSL"])) { $EMailUseSSL -eq "True" } else { $SequenceSettings[$i].Parameter.MailOptions["MailUseSSL"] }
          IgnoreSSLError=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailSSLIgnoreErrors"])) { $EMailSSLIgnoreErrors -eq "True" } else { $SequenceSettings[$i].Parameter.MailOptions["MailSSLIgnoreErrors"] }
          SMTPUsername=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailUsername"])) { $SMTPUsername } else { $SequenceSettings[$i].Parameter.MailOptions["MailUsername"] }
          SMTPPassword=if ([string]::IsNullOrEmpty($SequenceSettings[$i].Parameter.MailOptions["MailPassword"])) { $SMTPPassword } else { $SequenceSettings[$i].Parameter.MailOptions["MailPassword"] }
          Subject="Hydra Results"
          Body=$($SequenceLog[$i] -join "<BR>`r`n")
          BodyAsHTML=$True
          Encoding='UTF8'
          AllowMessage=$False
        }
        Send-MailCommand @parameters
      }

    } 

    if ($SequenceStats[$i]) {

      try {
        $SeqStatsFile="$LogFilePath`.stats"
        if (!(Test-Path $SeqStatsFile)) {
          Set-Content -Value "SequenceName;User;Host;NbOfObjects;Date;StartTime;EndTime;TimeElapsed;OK;BREAK;STOP;END;CANCEL;ERROR" -Path $SeqStatsFile -Force -ErrorAction Stop
        }
        $TimeElapsed=New-TimeSpan -Start $($SequenceStats[$i].StartTime) -End $($SequenceStats[$i].EndTime)
        $TimeElapsedMMss="{0:D2}:{1:D2}" -f $($TimeElapsed.Hours*60 + $TimeElapsed.Minutes), $($TimeElapsed.Seconds)
        $StatResults="$($SequenceStats[$i].SequenceName);$($SequenceStats[$i].User);$($SequenceStats[$i].Host);$($SequenceStats[$i].NbOfObjects);$($SequenceStats[$i].Date);$(($SequenceStats[$i].StartTime).ToLongTimeString());$(($SequenceStats[$i].EndTime).ToLongTimeString());$TimeElapsedMMss;$($SequenceStats[$i].OK);$($SequenceStats[$i].BREAK);$($SequenceStats[$i].STOP);$($SequenceStats[$i].END);$($SequenceStats[$i].CANCEL);$($SequenceStats[$i].ERROR)"
        Add-Content -Value $StatResults -Path $SeqStatsFile -Force -ErrorAction SilentlyContinue
      }
      catch {
        Write-Host "Error writing the statistics"
      }

    }
     
    $Script:SequenceLog[$i]=,@()
    $SequenceStats[$i]=,@()
  }

}


function Check-AutoRunStartup {

  # Check the AutoRun options
  
  if ($AutoRun -eq $False) { 
    return 
  }

  try {
    $Script:LogFilePath=Get-ItemProperty HKCU:Software\Hydra\7 -Name LogFilePath -ErrorAction Stop | Select-Object -ExpandProperty LogFilePath
  }
  catch {
    $Script:LogFilePath="C:\_Logfiles\Hydra.log"
  }

  $Settings.GetEnumerator() | ForEach-Object {
    Set-Variable -Name $_.Key -Value $_.Value -Scope Script -Force
  }

  if ($AutoRunExport -ne "") {
    if (($AutoRunExport -ne "CSV") -and ($AutoRunExport -ne "HTML") -and ($AutoRunExport -ne "XLSX")) {
      Write-Host "AutoRun Warning: AutoRunExport value $AutoRunExport is not known: skipped"
      if (Test-Path $LogFilePath) {
        try {
          Add-Content -Path $LogFilePath -Value "" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "$("#" * 60)" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "Hydra Started on $(Get-Date -Format "dd.MM.yyyy , hh:mm:ss")" -ErrorAction SilentlyContinue
          Add-Content -Value "AutoRun Warning: AutoRunExport value $AutoRunExport is not known: skipped" -Path $LogFilePath -ErrorAction SilentlyContinue
        }
        catch {}
      }
    }
  }

  if ($AutoRunSequence -ne "") {
    if (!(Test-Path $AutoRunSequence)) {
      Write-Host "AutoRun Error: The Sequence $AutoRunSequence couldn't be found"
      if (Test-Path $LogFilePath) {
        try {
          Add-Content -Path $LogFilePath -Value "" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "$("#" * 60)" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "Hydra Started on $(Get-Date -Format "dd.MM.yyyy , hh:mm:ss")" -ErrorAction SilentlyContinue
          Add-Content -Value "AutoRun Error: The Sequence $AutoRunSequence couldn't be found" -Path $LogFilePath -ErrorAction SilentlyContinue
        }
        catch {}
      }
      $Script:AutoRun=$False
      exit
    }
    if ($AutoRunObjects -eq "") {
      Write-Host "AutoRun Error: AutoRunObjects must be set"
      if (Test-Path $LogFilePath) {
        try {
          Add-Content -Path $LogFilePath -Value "" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "$("#" * 60)" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "Hydra Started on $(Get-Date -Format "dd.MM.yyyy , hh:mm:ss")" -ErrorAction SilentlyContinue
          Add-Content -Value "AutoRun Error: AutoRunObjects must be set" -Path $LogFilePath -ErrorAction SilentlyContinue
        }
        catch {}
      }
      $Script:AutoRun=$False
      exit
    }
    if (($AutoRunObjects -ne "") -and ($AutoRunSequence -eq "")) {
      Write-Host "AutoRun Error: AutoRunSequence must be set"
      if (Test-Path $LogFilePath) {
        try {
          Add-Content -Path $LogFilePath -Value "" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "$("#" * 60)" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "Hydra Started on $(Get-Date -Format "dd.MM.yyyy , hh:mm:ss")" -ErrorAction SilentlyContinue
          Add-Content -Value "AutoRun Error: AutoRunSequence must be set" -Path $LogFilePath -ErrorAction SilentlyContinue
        }
        catch {}
      }
      $Script:AutoRun=$False
      exit
    }
    return
  }

  if ($AutoRunBundle -ne "") {
    if (!(Test-Path $AutoRunBundle)) {
      Write-Host "AutoRun Error: The Bundle $AutoRunBundle couldn't be found"
      if (Test-Path $LogFilePath) {
        try {
          Add-Content -Path $LogFilePath -Value "" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "$("#" * 60)" -ErrorAction SilentlyContinue
          Add-Content -Path $LogFilePath -Value "Hydra Started on $(Get-Date -Format "dd.MM.yyyy , hh:mm:ss")" -ErrorAction SilentlyContinue
          Add-Content -Value "AutoRun Error: The Bundle $AutoRunBundle couldn't be found" -Path $LogFilePath -ErrorAction SilentlyContinue
        }
        catch {}
      }
      $Script:AutoRun=$False
      exit
    }
  }

}



###  MAIN  ###

$Script:HydraVersion="7.5.6"

[void][System.Reflection.Assembly]::LoadWithPartialName('PresentationFramework')
Add-Type -AssemblyName System.Windows.Forms

Check-AutoRunStartup

Set-Startup_GlobalVariables $MyInvocation

. $HydraGUIPath\Hydra7_Dialogs.ps1
. $HydraGUIPath\Hydra7_Form.ps1
. $HydraGUIPath\Hydra7_Res.ps1

Set-Startup

if (($SplashScreen -eq $True) -and ($AutoRun -eq $False)) { 
  Set-SplashScreen
  $Script:SplashScreenDisplayed=1 
}
else {
  $Script:SplashScreenDisplayed=2
}

Load-XAMLVariables $XAMLMainWindow "Main"

Get-ChildItem $HydraGUIPath -Name "Hydra7_Addon*.ps1" | ForEach-Object {  # Load Addons, if any
  . $HydraGUIPath\$_
  $Script:HydraAddonsList+=$_
}

Set-IconMain
Set-HomePersoIcons
[System.Windows.Input.Mouse]::OverrideCursor=$Null

Set-ConsoleVisible ($DebugMode -eq 1)
$Form.FontFamily=$FontDefaultFamily
$RibbonWin.FontFamily=$FontDefaultFamily 

$Async=$Form.Dispatcher.InvokeAsync({
  [void]$Form.ShowDialog()
})
$Async.Wait() | Out-Null

$Timer.Dispose()
if ($AutoRun -eq $False) { $TimerAutoSave.Dispose() }