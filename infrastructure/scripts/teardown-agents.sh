#!/bin/bash
# Tear down all AgentCore agents.
#
# Usage:
#   ./teardown-agents.sh [environment]    # default: dev
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENVIRONMENT=${1:-dev}

# Resolve the starter toolkit's agentcore CLI
AGENTCORE="$(python3 -c "import sysconfig, os; p=os.path.join(sysconfig.get_path('scripts'),'agentcore'); print(p) if os.path.exists(p) else exit(1)" 2>/dev/null)" \
  || { echo "ERROR: bedrock-agentcore-starter-toolkit not found."; exit 1; }

echo "Destroying AgentCore agents for $ENVIRONMENT..."

for agent in sql analyst writer validator orchestrator; do
  AGENT_NAME="illuminate_${agent}_${ENVIRONMENT}"
  AGENT_DIR="$PROJECT_ROOT/agents/$agent"
  if [ -f "$AGENT_DIR/.bedrock_agentcore.yaml" ]; then
    echo "Destroying $AGENT_NAME..."
    cd "$AGENT_DIR"
    $AGENTCORE destroy --agent "$AGENT_NAME" --force 2>&1 | grep -E "✓|✅|destroyed|Next steps" || true
  else
    echo "Skipping $AGENT_NAME (no config found)"
  fi
done

# Clean up SSM parameters
echo "Cleaning up SSM parameters..."
for agent in sql analyst writer validator orchestrator; do
  aws ssm delete-parameter --name "/illuminate/$ENVIRONMENT/${agent}-arn" 2>/dev/null || true
  aws ssm delete-parameter --name "/illuminate/$ENVIRONMENT/${agent}-url" 2>/dev/null || true
done

echo "✓ All agents destroyed"
