# Mira Sense scheduled-task wrapper: injects the access token and runs the
# perception sampler. Created so the mind loop receives machine observations
# despite the API requiring auth.
$env:MIRA_ACCESS_TOKEN = "110403"
& "C:\Users\sanka\OneDrive\Desktop\coding and stuff\projects\mira\scripts\mira_sense.ps1"