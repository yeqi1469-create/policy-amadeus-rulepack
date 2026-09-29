param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute $Executable -Argument '--auto-update'
$hourly = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Hours 1)
$daily = New-ScheduledTaskTrigger -Daily -At '09:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'Policy Amadeus Auto Update' -Action $action -Trigger @($hourly, $daily) -Settings $settings -Description 'Free hourly retries and all-country daily coverage. Missed runs start when available.' -Force | Out-Null
