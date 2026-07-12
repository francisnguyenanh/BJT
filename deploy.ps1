# Deploy bjt_app to Cloud Run.
# One-time setup (APIs, Firestore DB, secrets, IAM) is documented in DEPLOY.md
# and is NOT part of this script. Run this file every time you want to ship
# a code change:
#
#   .\deploy.ps1
#
$ErrorActionPreference = "Stop"

$PROJECT_ID = "feednotebooklm"
$REGION     = "us-central1"
$SERVICE    = "bjt-app"

gcloud config set project $PROJECT_ID | Out-Null

gcloud run deploy $SERVICE `
  --source . `
  --region $REGION `
  --allow-unauthenticated `
  --memory 512Mi `
  --cpu 1 `
  --min-instances 0 `
  --max-instances 2 `
  --set-secrets "KAGGLE_USERNAME=bjt-kaggle-username:latest,KAGGLE_API_KEY=bjt-kaggle-api-key:latest"

if ($LASTEXITCODE -ne 0) {
    Write-Host "Deploy failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Deployed. Service URL:"
gcloud run services describe $SERVICE --region $REGION --format "value(status.url)"
