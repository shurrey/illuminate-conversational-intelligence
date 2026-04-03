#!/bin/bash
# Tear down all Illuminate infrastructure in reverse deployment order.
#
# Usage:
#   ./teardown-all.sh [environment]    # default: dev
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENVIRONMENT=${1:-dev}
REGION=${AWS_REGION:-us-east-1}

echo "Tearing down ALL Illuminate infrastructure for $ENVIRONMENT..."
echo ""

# 1. Frontend (empty S3 bucket first)
"$SCRIPT_DIR/teardown-frontend.sh" "$ENVIRONMENT" || true

# 2. API
"$SCRIPT_DIR/teardown-api.sh" "$ENVIRONMENT" || true

# 3. Agents (agentcore CLI)
"$SCRIPT_DIR/teardown-agents.sh" "$ENVIRONMENT" || true

# 4. Base infrastructure (VPC, Cognito, Secrets, WAF)
"$SCRIPT_DIR/teardown-base.sh" "$ENVIRONMENT"

echo ""
echo "✓ All Illuminate infrastructure torn down for $ENVIRONMENT"
