# Mira Telemetry scheduled-task wrapper: injects the access token and runs the
# telemetry sampler. Created so the HUD metrics (CPU/mem/batt) populate without
# exposing the token in the scheduled-task command line.
$env:MIRA_ACCESS_TOKEN = "110403"
& "C:\Users\sanka\OneDrive\Desktop\coding and stuff\projects\mira\scripts\mira_telemetry.ps1"