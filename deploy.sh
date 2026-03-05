#!/bin/bash
# AcaMail — Google Cloud Run Deployment Script
# Run this from the project root directory

set -e

PROJECT_ID="gen-lang-client-0629729646"
REGION="us-central1"
SERVICE_NAME="acamail"

echo "🚀 Deploying AcaMail to Google Cloud Run..."
echo ""

# Step 1: Prepare token file
if [ ! -f "token.json" ]; then
    echo "📋 Copying Gmail token to project directory..."
    cp ~/Downloads/gmail_bot_token.json token.json
    echo "   ✓ token.json ready"
fi

# Verify required files
echo "🔍 Checking required files..."
for f in credentials.json token.json .env main.py requirements.txt Dockerfile; do
    if [ -f "$f" ]; then
        echo "   ✓ $f"
    else
        echo "   ✗ $f MISSING!"
        exit 1
    fi
done
echo ""

# Step 2: Enable required APIs
echo "⚙️  Enabling Cloud Run API..."
gcloud services enable run.googleapis.com --project=$PROJECT_ID 2>/dev/null
gcloud services enable artifactregistry.googleapis.com --project=$PROJECT_ID 2>/dev/null
echo "   ✓ APIs enabled"
echo ""

# Step 3: Deploy to Cloud Run
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
echo "📊 View logs: gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
echo "🛑 To stop:   gcloud run services update $SERVICE_NAME --min-instances=0 --region=$REGION --project=$PROJECT_ID"
echo "🗑  To delete: gcloud run services delete $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
