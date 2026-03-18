$paths = @('Machine', 'User')
$removed = $false
foreach ($target in $paths) {
    $currentPath = [Environment]::GetEnvironmentVariable('Path', $target)
    if ($currentPath -match 'C:\\MinGW\\bin') {
        Write-Host "Found C:\MinGW\bin in $target Path. Removing..."
        $newPath = ($currentPath -split ';' | Where-Object { $_ -ne 'C:\MinGW\bin' -and $_ -ne 'C:\MinGW\bin\' }) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $newPath, $target)
        $removed = $true
        Write-Host "Removed from $target Path."
    }
}
if ($removed) {
    Write-Host "PATH updated successfully!"
} else {
    Write-Host "C:\MinGW\bin not found in PATH."
}
