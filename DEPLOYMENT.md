# Deployment Guide

## Prerequisites

- AWS CLI configured (ap-south-1)
- kubectl configured for your EKS cluster
- Docker installed locally (for building images)

## 1. Create GitHub App

1. Go to https://github.com/organizations/VahanInc/settings/apps/new
2. Fill in:
   - **Name**: `vahan-agent`
   - **Homepage URL**: `https://github.com/VahanInc/vahan-agent`
   - **Webhook URL**: `https://<your-ingress-domain>/webhooks/github`
   - **Webhook secret**: generate one (`openssl rand -hex 32`)
3. Permissions:
   - **Repository permissions**:
     - Contents: Read & Write
     - Issues: Read & Write
     - Pull requests: Read & Write
     - Metadata: Read-only
   - **Organization permissions**: Members: Read-only
4. Subscribe to events: Issue comment, Pull request, Pull request review, Push
5. Create the app
6. Generate a private key (download the PEM file)
7. Install the app on VahanInc org (all repos or select repos)
8. Note down: **App ID**, **Installation ID**, **Private Key (PEM contents)**, **Webhook Secret**

## 2. Create Slack App

1. Go to https://api.slack.com/apps → Create New App → From scratch
2. Fill in:
   - **Name**: `vahan-agent`
   - **Workspace**: your Slack workspace
3. Features → OAuth & Permissions → Bot Token Scopes:
   - `app_mentions:read`
   - `chat:write`
   - `channels:history`
   - `groups:history`
   - `users:read`
   - `users:read.email`
4. Features → Event Subscriptions:
   - Enable events
   - **Request URL**: `https://<your-ingress-domain>/webhooks/slack`
   - Subscribe to bot events: `app_mention`
5. Install to Workspace
6. Note down: **Bot Token** (`xoxb-...`), **Signing Secret**, **Bot User ID**

## 3. Build & Push Docker Images

### Orchestrator image

```bash
cd /path/to/vahan-agent
docker build -t 091997204841.dkr.ecr.ap-south-1.amazonaws.com/vahan-agent/orchestrator:latest .
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin 091997204841.dkr.ecr.ap-south-1.amazonaws.com
docker push 091997204841.dkr.ecr.ap-south-1.amazonaws.com/vahan-agent/orchestrator:latest
```

### Sandbox image (for Modal/custom provider)

```bash
cd /path/to/vahan-agent/sandbox
docker build -t 091997204841.dkr.ecr.ap-south-1.amazonaws.com/vahan-agent/sandbox:latest .
docker push 091997204841.dkr.ecr.ap-south-1.amazonaws.com/vahan-agent/sandbox:latest
```

## 4. Fill Secrets

Edit `k8s/base/secret.yaml` and fill in all empty values:

```bash
# Generate a webhook secret
openssl rand -hex 32

# Get the RDS connection string
echo "postgresql://agent_admin:<password>@vahan-agent-db.ciqpn8ajz11z.ap-south-1.rds.amazonaws.com:5432/vahan_agent"
```

**Do NOT commit the filled secret.yaml to git.**

## 5. Deploy to EKS

```bash
# Create namespace and deploy
kubectl apply -k k8s/base/

# Verify
kubectl get pods -n vahan-agent
kubectl logs -n vahan-agent deployment/vahan-agent -f
```

## 6. Configure Ingress Domain

Update `k8s/base/ingress.yaml` with your actual domain or use the ALB DNS name directly.

For Slack/GitHub webhooks, you need a publicly accessible HTTPS endpoint. Options:
- Use the ALB DNS name directly (e.g., `k8s-vahanag-vahanag-xxxxx.ap-south-1.elb.amazonaws.com`)
- Create a CNAME record: `agent.vahan.co` → ALB DNS
- Or use ngrok for testing: `ngrok http 8000`

## 7. Add Agent Config to Repos

Copy the config files to each repo you want the agent to work on:

```bash
# JobFinder
cp repo-configs/jobfinder/AGENTS.md /path/to/JobFinder/AGENTS.md
cp repo-configs/jobfinder/context.yaml /path/to/JobFinder/context.yaml

# New repo (use templates)
cp repo-configs/TEMPLATE-AGENTS.md /path/to/new-repo/AGENTS.md
cp repo-configs/TEMPLATE-context.yaml /path/to/new-repo/context.yaml
# Then fill in the blanks
```

## 8. Test

```bash
# In Slack, tag the agent:
@vahan-agent fix the login timeout in mitra auth repo:VahanInc/JobFinder

# Watch logs:
kubectl logs -n vahan-agent deployment/vahan-agent -f
```

## Infrastructure Summary

| Resource | Details |
|----------|---------|
| **RDS** | `vahan-agent-db.ciqpn8ajz11z.ap-south-1.rds.amazonaws.com:5432/vahan_agent` (db.t4g.micro) |
| **ECR (orchestrator)** | `091997204841.dkr.ecr.ap-south-1.amazonaws.com/vahan-agent/orchestrator` |
| **ECR (sandbox)** | `091997204841.dkr.ecr.ap-south-1.amazonaws.com/vahan-agent/sandbox` |
| **EKS namespace** | `vahan-agent` |
| **Model** | Claude Sonnet 4.6 (primary), Claude Haiku 4.5 (fallback) |
| **Sandbox provider** | Modal (MVP), Fargate (future) |
