# April 28, 2026 — OpenAI on Bedrock Launch Day

Today, AWS announced OpenAI models on Amazon Bedrock:
- **o3** — OpenAI's best reasoning model
- **o4-mini** — Fast, cost-effective reasoning
- **Codex** — Software engineering agent

This makes AWS Bedrock the only hyperscaler offering both Anthropic (Claude) and OpenAI frontier models through a single API.

## Why This Matters for Governance

The barrier to deploying powerful AI just dropped to zero. Any developer with AWS credentials can now spin up agents with GPT-class reasoning capabilities.

**Governance is now urgent, not optional.**

This dashboard was built today to demonstrate:
1. How to track which agents exist in your AWS account
2. How to score risk based on guardrails, ownership, and production approval
3. How to maintain audit trails for compliance
4. How to give risk teams visibility without blocking developers

## The Architecture

- **Bedrock Agent Registry API** — Discovers all agents automatically
- **Risk Scoring** — 0-100 scale based on: guardrails present, owner assigned, idle TTL, audit recency, production approval
- **DynamoDB Governance Layer** — Stores metadata Bedrock doesn't capture
- **Audit Trail** — Every governance change logged immutably

## Why This Pattern

Because "who's running what AI agents?" is about to become the most important question in enterprise security — and most organizations won't have an answer.

---

*Built April 28, 2026 by Lobby (AI assistant) for Krish (kdeath83)*
