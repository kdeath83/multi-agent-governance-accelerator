# Multi-Agent Governance Accelerator 🔐

**Prototype / Proof of Concept**


A governance layer for AWS Bedrock Agent Registry — because deploying AI agents without oversight is like giving everyone root access and hoping for the best.


## Why This Exists

The OpenAI models on Bedrock announcement means enterprises will soon have:
- **o3** — OpenAI's best reasoning model
- **o4-mini** — Fast, cost-effective reasoning
- **Codex** — Software engineering agent

...all accessible through the same AWS APIs developers already use.

**The governance problem:** Organizations deploying AI agents at scale face:
- **No visibility** — Who created which agent? What's it connected to?
- **No guardrails** — Agents running without safety controls
- **No audit trail** — Changes happen, nobody knows who or why
- **Compliance gaps** — Risk teams can't assess what they can't see

This dashboard provides a **governance control plane** on top of AWS Bedrock — think of it as a "single pane of glass" for AI agent risk management.

## Quick Start

### Local Development

**Backend:**
```bash
cd backend
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Mac/Linux
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### One-Click Deploy to AWS

**Option 1: Local Deploy (Windows)**
```batch
deploy.bat
```

**Option 2: GitHub Actions**
1. Fork/push to GitHub
2. Add AWS secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ACCOUNT_ID`
3. Push to `main` branch → Auto deploys

**Option 3: Manual CDK**
```bash
cd infrastructure/cdk
pip install -r requirements.txt
cdk bootstrap
cdk deploy
```

## Features

- ✅ **Agent Discovery** — Pulls all agents from Bedrock Registry automatically
- ✅ **Risk Scoring** — Calculates risk (0-100) based on guardrails, ownership, approval status
- ✅ **Compliance Dashboard** — Green/Yellow/Red status at a glance
- ✅ **Audit Trail** — Every governance change logged with who/what/when
- ✅ **Concurrent Safety** — Optimistic locking prevents update conflicts
- ✅ **JWT Auth** — Secure access control
- ✅ **Rate Limiting** — Prevents API abuse
- ✅ **Pagination** — Handles hundreds of agents efficiently
- ✅ **WAF Protected** — Basic AWS WAF rules (SQLi, XSS, rate limiting)
- ✅ **CloudWatch Alarms** — Alerts on errors and throttling
- ✅ **Encrypted Storage** — DynamoDB encryption at rest
- ✅ **HTTPS Only** — TLS 1.3 via CloudFront

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Browser   │────▶│ CloudFront  │────▶│  S3 Static  │
└─────────────┘     └─────────────┘     └─────────────┘
                            │
                            ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   AWS WAF   │────▶│ API Gateway │────▶│   Lambda    │
└─────────────┘     └─────────────┘     └─────────────┘
                                                │
                        ┌─────────────┬─────────┴─────────┐
                        ▼             ▼                   ▼
                ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
                │  Bedrock    │ │ Governance  │ │   Audit     │
                │   Agents    │ │  DynamoDB   │ │   DynamoDB  │
                └─────────────┘ └─────────────┘ └─────────────┘
```

## The Governance Problem This Solves

**Before:** A developer creates a Bedrock agent with access to sensitive data. Nobody knows it exists. No guardrails. Six months later, an auditor asks "what AI systems do we have?" — crickets.

**After:** The same agent appears in the dashboard within minutes. Risk score shows RED (no owner, no guardrails, production approved=false). Compliance team gets visibility. Developer adds owner + guardrails → score drops to YELLOW.

**The value:** Governance without friction. Agents self-register via Bedrock API. Risk scores update automatically. Audit trail captures every change. Risk teams get visibility without blocking development.

## Production Considerations ⚠️

This is a **prototype**. For production deployment, consider:

- **Secrets Management** — Use AWS Secrets Manager or Parameter Store for JWT_SECRET_KEY
- **Penetration Testing** — Run security assessment before handling production data
- **WAF Tuning** — Adjust rate limits based on your traffic patterns
- **Backup Strategy** — DynamoDB point-in-time recovery is enabled, but test restores
- **Monitoring** — Add PagerDuty/OpsGenie integration for critical alarms
- **Multi-Region** — Currently single-region; consider failover for critical workloads

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/health` | GET | No | Health check |
| `/api/agents` | GET | Yes | List agents (paginated) |
| `/api/agents/{id}` | GET | Yes | Get agent details |
| `/api/agents/{id}/governance` | PUT | Yes | Update governance |
| `/api/agents/{id}/audit` | GET | Yes | Get audit trail |
| `/api/stats` | GET | Yes | Dashboard statistics |

## Cost Estimate (Monthly - Prototype Scale)

| Service | Usage | Cost |
|---------|-------|------|
| Lambda | 100K requests | ~$2 |
| API Gateway | 100K requests | ~$3 |
| DynamoDB | 10GB, on-demand | ~$5 |
| S3 | 1GB | ~$0.50 |
| CloudFront | 100GB transfer | ~$8 |
| WAF | 1 WebACL | ~$5 |
| **Total** | | **~$24/month** |

*Note: Costs scale with usage. Production workloads with millions of requests will cost more.*

## Environment Variables

Backend (`backend/.env` — copy from `.env.example`):
```
JWT_SECRET_KEY=generate-a-64-char-random-string-for-prototype
AWS_REGION=us-east-1
LOG_LEVEL=INFO
```

⚠️ **Important:** `JWT_SECRET_KEY` must be set. Generate one with:
```bash
node -e "console.log(require('crypto').randomBytes(64).toString('hex'))"
```

For production, use AWS Secrets Manager instead of environment variables.

Frontend (`frontend/.env`):
```
# Leave blank for local dev, set to API Gateway URL after deploy
VITE_API_URL=
```

## Why AWS Bedrock + This Dashboard?

AWS Bedrock just became the most capable AI platform on earth — Anthropic Claude *and* OpenAI models, both available through the same API. That's the feature, and the risk.

This dashboard adds the governance layer that enterprise deployments will need as they adopt o3, o4-mini, and Codex agents: visibility, audit trails, and risk scoring.

Built to address governance gaps as powerful AI models become widely available. Because when the most powerful AI models in the world become one API call away, governance stops being optional.

## Disclaimer

This is **experimental code** for learning and prototyping. It demonstrates governance concepts but has not undergone production security hardening. Use for proof-of-concept deployments only.


For production AI governance at scale, consider:
- AWS-native solutions (AWS Config, Security Hub)
- Enterprise AI governance platforms (AimSecurity, HiddenLayer, etc.)
- Custom builds with full security review

## License

MIT — See LICENSE for details.
