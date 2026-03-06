#!/bin/bash
# AcaMail — Google Cloud Run Deployment Script (Webhook Mode)
# Run this from the project root directory

set -e

PROJECT_ID="gen-lang-client-0629729646"
REGION="us-central1"
SERVICE_NAME="acamail"

echo "🚀 Deploying AcaMail to Google Cloud Run (Webhook mode)..."
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
echo "⚙️  Enabling APIs..."
gcloud services enable run.googleapis.com --project=$PROJECT_ID 2>/dev/null || true
gcloud services enable artifactregistry.googleapis.com --project=$PROJECT_ID 2>/dev/null || true
gcloud services enable cloudscheduler.googleapis.com --project=$PROJECT_ID 2>/dev/null || true
echo "   ✓ APIs check done"
echo ""

# Deploy to Cloud Run (webhook mode — min-instances=0 for cost savings)
echo "📦 Building and deploying (this may take 2-3 minutes)..."
gcloud run deploy $SERVICE_NAME \
    --source . \
    --project=$PROJECT_ID \
    --region=$REGION \
    --allow-unauthenticated \
    --min-instances=0 \
    --max-instances=2 \
    --cpu=1 \
    --memory=512Mi \
    --timeout=300

echo ""

# Get the service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
    --project=$PROJECT_ID \
    --region=$REGION \
    --format='value(status.url)' 2>/dev/null)

if [ -z "$SERVICE_URL" ]; then
    echo "⚠️  Could not retrieve service URL. Please check Cloud Console."
    echo "   You need to manually set WEBHOOK_URL in .env"
else
    echo "🌐 Service URL: $SERVICE_URL"
    echo ""

    # Check if WEBHOOK_URL is set in .env
    if grep -q "WEBHOOK_URL=" .env 2>/dev/null; then
        CURRENT_URL=$(grep "WEBHOOK_URL=" .env | cut -d'=' -f2-)
        if [ "$CURRENT_URL" != "$SERVICE_URL" ]; then
            echo "📝 Updating WEBHOOK_URL in .env..."
            # Use sed to update the WEBHOOK_URL
            if [[ "$OSTYPE" == "darwin"* ]]; then
                sed -i '' "s|WEBHOOK_URL=.*|WEBHOOK_URL=$SERVICE_URL|" .env
            else
                sed -i "s|WEBHOOK_URL=.*|WEBHOOK_URL=$SERVICE_URL|" .env
            fi
            echo "   ✓ WEBHOOK_URL updated to $SERVICE_URL"
            echo ""
            echo "⚠️  WEBHOOK_URL was updated. You need to redeploy for it to take effect:"
            echo "   bash deploy.sh"
        fi
    else
        echo "⚠️  WEBHOOK_URL not found in .env"
        echo "   Please add this line to your .env file:"
        echo "   WEBHOOK_URL=$SERVICE_URL"
        echo ""
        echo "   Then redeploy: bash deploy.sh"
    fi
fi
echo ""

# Set up Cloud Scheduler jobs for daily digest
echo "⏰ Setting up Cloud Scheduler jobs..."

# Read the scheduler secret from .env
SCHEDULER_SECRET=""
if [ -f .env ]; then
    SCHEDULER_SECRET=$(grep "CLOUD_SCHEDULER_SECRET=" .env 2>/dev/null | cut -d'=' -f2- || true)
fi

if [ -z "$SCHEDULER_SECRET" ]; then
    SCHEDULER_SECRET="acamail-trigger-$(date +%s)"
    echo "   Generated scheduler secret: $SCHEDULER_SECRET"
    echo "   ⚠️  Please add to .env: CLOUD_SCHEDULER_SECRET=$SCHEDULER_SECRET"
fi

if [ -n "$SERVICE_URL" ]; then
    # Read push hours from .env (default: 12,21)
    PUSH_HOURS=$(grep "PUSH_HOURS=" .env 2>/dev/null | cut -d'=' -f2- || echo "12,21")
    IFS=',' read -ra HOURS <<< "$PUSH_HOURS"

    for HOUR in "${HOURS[@]}"; do
        HOUR=$(echo "$HOUR" | tr -d ' ')
        JOB_NAME="acamail-digest-${HOUR}"

        # Delete existing job if any (ignore errors)
        gcloud scheduler jobs delete $JOB_NAME \
            --project=$PROJECT_ID \
            --location=$REGION \
            --quiet 2>/dev/null || true

        # Create new job
        gcloud scheduler jobs create http $JOB_NAME \
            --project=$PROJECT_ID \
            --location=$REGION \
            --schedule="0 ${HOUR} * * *" \
            --time-zone="$(grep 'TIMEZONE=' .env 2>/dev/null | cut -d'=' -f2- || echo 'America/Chicago')" \
            --uri="${SERVICE_URL}/trigger/digest" \
            --http-method=POST \
            --headers="X-Scheduler-Secret=${SCHEDULER_SECRET}" \
            --attempt-deadline=300s \
            2>/dev/null

        if [ $? -eq 0 ]; then
            echo "   ✓ Scheduled digest at ${HOUR}:00"
        else
            echo "   ⚠ Failed to create job $JOB_NAME (may need manual setup)"
        fi
    done
else
    echo "   ⚠ Skipped — service URL not available"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 View logs:  gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
echo "🔄 Redeploy:   bash deploy.sh"
echo "📋 Scheduler:  gcloud scheduler jobs list --project=$PROJECT_ID --location=$REGION"
echo "🗑  Delete:     gcloud run services delete $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
