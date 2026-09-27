# One command: build the reproducibility image and run every verification gate. Report lands in .\repro_out
Set-Location (Join-Path $PSScriptRoot "..")
docker build -f repro/Dockerfile -t netscope-repro .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
New-Item -ItemType Directory -Force repro_out | Out-Null
docker run --rm -v "${PWD}/repro_out:/app/repro_out" netscope-repro
exit $LASTEXITCODE
