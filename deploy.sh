#!/bin/bash
# AcaMail — Google Cloud Run Deployment Script
# Run this from the project root directory

set -e

PROJECT_ID="gen-lang-client-0629729646"
REGION="us-central1"
SERVICE_NAME="acamail"

echo "🚀 Deploying AcaMail to Google Cloud Run..."
echo ""

# Verify required files (use find to check — works even with read-restricted files)
echo "🔍 Checking required files..."
MISSING=0
for f in credentials.json token.json .env main.py requirements.txt Dockerfile contacts.json; do
    if find . -maxdepth 1 -name "$f" 2>/dev/null | grep -q .; then
        echo "   ✓ $f"
    else
        echo "   ✗ $f MISSING!"
        MISSING=1
    fi
done
echo ""

if [ "$MISSING" = "1" ]; then
    echo "❌ Some required files are missing. Please add them before deploying."
    exit 1
fi

# Enable required APIs (non-fatal — may already be enabled)
echo "⚙️  Enabling Cloud Run API..."
gcloud services enable run.googleapis.com --project=$PROJECT_ID 2>/dev/null || echo "   ⚠ Could not enable run API (may already be enabled)"
gcloud services enable artifactregistry.googleapis.com --project=$PROJECT_ID 2>/dev/null || echo "   ⚠ Could not enable artifact registry API (may already be enabled)"
echo "   ✓ APIs check done"
echo ""

# Deploy to Cloud Run
echo "📦 Building and deploying (this may take 2-3 minutes)..."
gcloud run deploy $SERVICE_NAME \
    --source . \
    --project=$PROJECT_ID \
    --region=$REGION \
    --no-allow-unauthenticated \
    --min-instances=1 \
    --max-instances=1 \
    --cpu=1 \
    --memory=512Mi \
    --timeout=3600 \
    --no-cpu-throttling

echo ""
echo "✅ AcaMail deployed successfully!"
echo ""
echo "📊 View logs:  gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
echo "🔄 Redeploy:   bash deploy.sh"
echo "🛑 To stop:    gcloud run services update $SERVICE_NAME --min-instances=0 --region=$REGION --project=$PROJECT_ID"
echo "🗑  To delete:  gcloud run services delete $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
