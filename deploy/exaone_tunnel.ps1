# Keeps the reverse tunnel that lets the server (211.233.203.19) reach EXAONE
# (Ollama on this PC, port 11434).  Reconnects whenever ssh exits, so a
# dropped connection or a sleeping PC does not stop plan generation for long.
# Run:  powershell -ExecutionPolicy Bypass -File deploy\exaone_tunnel.ps1
while ($true) {
  Write-Host "$(Get-Date -Format 'HH:mm:ss') tunnel connecting"
  ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -R 11434:127.0.0.1:11434 root@211.233.203.19
  Write-Host "$(Get-Date -Format 'HH:mm:ss') tunnel closed, retrying in 5s"
  Start-Sleep -Seconds 5
}
