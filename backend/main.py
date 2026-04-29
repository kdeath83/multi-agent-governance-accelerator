"""
AWS Agent Registry Governance Dashboard - Prototype / Proof of Concept

An experimental tool for managing and governing AI agents on AWS Bedrock.
Demonstrates: async AWS APIs, risk scoring, governance workflows, audit logging.

Note: For production use, additional hardening (secrets management, WAF rules, 
penetration testing) would be required.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Optional, Dict, Any
import json

import aioboto3
from cachetools import TTLCache
from fastapi import FastAPI, HTTPException, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.status import HTTP_401_UNAUTHORIZED

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Security - MUST be set via environment variable
import os
# Allow placeholder for CI/testing, require in production
_env_key = os.environ.get("JWT_SECRET_KEY", "")
if _env_key and _env_key != "placeholder-for-ci-only":
    SECRET_KEY = _env_key
else:
    # In Lambda production, fail. In local dev, warn but allow.
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        raise ValueError("JWT_SECRET_KEY environment variable is required in production")
    SECRET_KEY = "dev-placeholder-not-for-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

# Rate limiting - API key based (works behind CloudFront/CDN)
def get_rate_limit_key(request: Request) -> str:
    """Get rate limit key from API key or Authorization header"""
    # Check API key first
    api_key = request.headers.get("X-Api-Key")
    if api_key:
        return f"apikey:{api_key}"
    # Fall back to auth token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return f"token:{auth[7:]}"  # Skip "Bearer "
    return f"ip:{get_remote_address(request)}"

limiter = Limiter(key_func=get_rate_limit_key)

app = FastAPI(
    title="Agent Registry Governance Dashboard",
    description="Enterprise AI governance for AWS Bedrock Agents - Production Ready",
    version="2.0.0"
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS - Restricted for production
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://your-production-domain.com"  # TODO: Add your domain
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Caching - 5 minute TTL for agent list
agent_cache = TTLCache(maxsize=100, ttl=300)

# AWS Session (async)
aws_session = aioboto3.Session()

# Models
class Agent(BaseModel):
    agentId: str
    agentName: str
    agentStatus: str
    agentVersion: Optional[str] = None
    foundationModel: Optional[str] = None
    idleSessionTTLInSeconds: int = 1800
    guardrailConfiguration: Optional[Dict[str, Any]] = None
    createdAt: str
    updatedAt: str
    riskScore: float = Field(default=50.0, ge=0, le=100)
    complianceStatus: str = Field(default="YELLOW", pattern="^(GREEN|YELLOW|RED)$")
    owner: str = "Unknown"
    department: Optional[str] = None
    dataClassification: str = "INTERNAL"
    lastAudited: Optional[str] = None
    governanceNotes: Optional[str] = None
    approvedForProduction: bool = False
    version: int = 1  # For optimistic locking

class AgentUpdate(BaseModel):
    owner: Optional[str] = Field(None, min_length=1, max_length=100)
    department: Optional[str] = Field(None, min_length=1, max_length=100)
    dataClassification: Optional[str] = Field(None, pattern="^(PUBLIC|INTERNAL|CONFIDENTIAL|RESTRICTED)$")
    governanceNotes: Optional[str] = Field(None, max_length=1000)
    approvedForProduction: Optional[bool] = None
    complianceStatus: Optional[str] = Field(None, pattern="^(GREEN|YELLOW|RED)$")
    expectedVersion: int = Field(1, ge=1)  # For optimistic locking

class Token(BaseModel):
    access_token: str
    token_type: str

# Authentication
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify JWT token"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return username
    except JWTError:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Decimal serialization
def decimal_default(obj):
    """Convert Decimal to float for JSON serialization"""
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def serialize_for_json(data: Any) -> Any:
    """Recursively serialize data for JSON"""
    if isinstance(data, Decimal):
        return float(data)
    elif isinstance(data, dict):
        return {k: serialize_for_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [serialize_for_json(item) for item in data]
    return data

# Risk Calculation Engine
class RiskCalculator:
    """Calculate governance risk scores for agents"""
    
    @staticmethod
    def calculate(agent_info: Dict, governance: Dict) -> float:
        """Calculate risk score (0-100, lower is better)"""
        score = 50.0  # Baseline
        
        # Critical: No guardrails = +30 risk
        if not agent_info.get('guardrailConfiguration'):
            score += 30
            logger.debug(f"No guardrails - adding 30 risk points")
        
        # High: Long idle session = +15 risk
        idle_ttl = agent_info.get('idleSessionTTLInSeconds', 1800)
        if idle_ttl > 3600:
            score += 15
        elif idle_ttl > 1800:
            score += 5
        
        # High: No owner assigned = +15 risk
        if not governance.get('owner'):
            score += 15
        
        # Medium: Not approved for production = +10 risk
        if not governance.get('approvedForProduction', False):
            score += 10
        
        # Medium: No recent audit (> 90 days) = +10 risk
        last_audited = governance.get('lastAudited')
        if last_audited:
            try:
                audit_date = datetime.fromisoformat(last_audited.replace('Z', '+00:00'))
                days_since = (datetime.utcnow() - audit_date).days
                if days_since > 90:
                    score += 10
            except:
                score += 5
        else:
            score += 10
        
        # Medium: High data classification without protection = +15 risk
        if governance.get('dataClassification') in ['CONFIDENTIAL', 'RESTRICTED']:
            if not agent_info.get('guardrailConfiguration'):
                score += 15
        
        return min(score, 100.0)
    
    @staticmethod
    def get_compliance_status(risk_score: float, agent_info: Dict) -> str:
        """Determine compliance status from risk score"""
        if risk_score >= 75:
            return "RED"
        elif risk_score >= 40:
            return "YELLOW"
        return "GREEN"

# Database Operations (Async)
async def get_dynamodb_table(table_name: str):
    """Get DynamoDB table (create if doesn't exist)"""
    async with aws_session.resource('dynamodb') as dynamodb:
        try:
            table = await dynamodb.Table(table_name)
            # Verify table exists
            await table.load()
            return table
        except Exception as e:
            logger.warning(f"Table {table_name} not found, creating...")
            # Create table
            client = await aws_session.client('dynamodb')
            try:
                if table_name == 'AgentGovernance':
                    await client.create_table(
                        TableName=table_name,
                        KeySchema=[{'AttributeName': 'agentId', 'KeyType': 'HASH'}],
                        AttributeDefinitions=[{'AttributeName': 'agentId', 'AttributeType': 'S'}],
                        BillingMode='PAY_PER_REQUEST'
                    )
                elif table_name == 'AgentAuditLog':
                    await client.create_table(
                        TableName=table_name,
                        KeySchema=[
                            {'AttributeName': 'agentId', 'KeyType': 'HASH'},
                            {'AttributeName': 'timestamp', 'KeyType': 'RANGE'}
                        ],
                        AttributeDefinitions=[
                            {'AttributeName': 'agentId', 'AttributeType': 'S'},
                            {'AttributeName': 'timestamp', 'AttributeType': 'S'}
                        ],
                        BillingMode='PAY_PER_REQUEST'
                    )
                # Wait for table creation
                waiter = await client.get_waiter('table_exists')
                await waiter.wait(TableName=table_name)
                logger.info(f"Created table: {table_name}")
                return await dynamodb.Table(table_name)
            except Exception as create_error:
                logger.error(f"Failed to create table: {create_error}")
                raise

# API Endpoints
@app.get("/api/health")
@limiter.limit("10/second")
async def health_check(request: Request):
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0"
    }

@app.get("/api/agents", response_model=List[Agent])
@limiter.limit("5/second")
async def list_agents(
    request: Request,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: str = Depends(verify_token)
):
    """
    Fetch all agents from Bedrock Agent Registry with governance overlay.
    Supports pagination with skip/limit parameters.
    """
    cache_key = f"agents_{skip}_{limit}"
    
    # Check cache
    if cache_key in agent_cache:
        logger.info(f"Returning cached agents for {current_user}")
        return agent_cache[cache_key]
    
    try:
        async with aws_session.client('bedrock-agent') as bedrock_agent:
            # List agents with proper pagination
            all_agents = []
            next_token = None
            
            while True:
                if next_token:
                    response = await bedrock_agent.list_agents(maxResults=100, nextToken=next_token)
                else:
                    response = await bedrock_agent.list_agents(maxResults=100)
                
                all_agents.extend(response.get('agentSummaries', []))
                next_token = response.get('nextToken')
                
                if not next_token or len(all_agents) >= skip + limit:
                    break
            
            # Apply pagination
            agent_summaries = all_agents[skip:skip+limit]
            
            # Get DynamoDB table
            gov_table = await get_dynamodb_table('AgentGovernance')
            
            # Fetch agent details in parallel
            async def fetch_agent_with_governance(summary):
                agent_id = summary['agentId']
                
                # Get detailed agent info
                try:
                    detail = await bedrock_agent.get_agent(agentId=agent_id)
                    agent_info = detail.get('agent', {})
                except Exception as e:
                    logger.warning(f"Failed to get agent details for {agent_id}: {e}")
                    agent_info = summary
                
                # Get governance data
                try:
                    gov_response = await gov_table.get_item(Key={'agentId': agent_id})
                    governance = gov_response.get('Item', {})
                except Exception as e:
                    logger.warning(f"Failed to get governance for {agent_id}: {e}")
                    governance = {}
                
                # Calculate risk and compliance
                governance = serialize_for_json(governance)
                risk_score = RiskCalculator.calculate(agent_info, governance)
                compliance = governance.get('complianceStatus') or RiskCalculator.get_compliance_status(risk_score, agent_info)
                
                return Agent(
                    agentId=agent_id,
                    agentName=agent_info.get('agentName', 'Unnamed Agent'),
                    agentStatus=agent_info.get('agentStatus', 'DISABLED'),
                    agentVersion=agent_info.get('agentVersion'),
                    foundationModel=agent_info.get('foundationModel'),
                    idleSessionTTLInSeconds=agent_info.get('idleSessionTTLInSeconds', 1800),
                    guardrailConfiguration=agent_info.get('guardrailConfiguration'),
                    createdAt=agent_info.get('createdAt', datetime.utcnow().isoformat()),
                    updatedAt=agent_info.get('updatedAt', datetime.utcnow().isoformat()),
                    riskScore=risk_score,
                    complianceStatus=compliance,
                    owner=governance.get('owner', 'Unknown'),
                    department=governance.get('department'),
                    dataClassification=governance.get('dataClassification', 'INTERNAL'),
                    lastAudited=governance.get('lastAudited'),
                    governanceNotes=governance.get('governanceNotes'),
                    approvedForProduction=governance.get('approvedForProduction', False),
                    version=governance.get('version', 1)
                )
            
            # Execute in parallel
            agents = await asyncio.gather(*[fetch_agent_with_governance(s) for s in agent_summaries])
            
            # Cache result
            agent_cache[cache_key] = agents
            
            logger.info(f"Retrieved {len(agents)} agents for {current_user}")
            return agents
            
    except Exception as e:
        logger.exception("Failed to fetch agents")
        raise HTTPException(status_code=500, detail=f"Failed to fetch agents: {str(e)}")

@app.get("/api/agents/{agent_id}")
@limiter.limit("10/second")
async def get_agent(
    agent_id: str,
    request: Request,
    current_user: str = Depends(verify_token)
):
    """Get detailed agent information"""
    try:
        async with aws_session.client('bedrock-agent') as bedrock_agent:
            detail = await bedrock_agent.get_agent(agentId=agent_id)
            return serialize_for_json(detail.get('agent', {}))
    except Exception as e:
        logger.exception(f"Failed to get agent {agent_id}")
        raise HTTPException(status_code=404, detail=f"Agent not found: {str(e)}")

@app.put("/api/agents/{agent_id}/governance")
@limiter.limit("5/second")
async def update_governance(
    agent_id: str,
    update: AgentUpdate,
    request: Request,
    current_user: str = Depends(verify_token)
):
    """
    Update governance metadata for an agent with optimistic locking.
    Compliance status is ALWAYS recalculated from risk score - cannot be manually overridden.
    """
    """
    Update governance metadata for an agent with optimistic locking.
    Requires expectedVersion to prevent race conditions.
    """
    try:
        # Verify agent exists in Bedrock
        async with aws_session.client('bedrock-agent') as bedrock_agent:
            try:
                agent_detail = await bedrock_agent.get_agent(agentId=agent_id)
                agent_info = agent_detail.get('agent', {})
            except Exception:
                raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found in Bedrock")
        
        # Get DynamoDB table
        gov_table = await get_dynamodb_table('AgentGovernance')
        
        # Get current item with version check
        current_item = await gov_table.get_item(Key={'agentId': agent_id})
        current = serialize_for_json(current_item.get('Item', {}))
        current_version = current.get('version', 0)
        
        # Optimistic locking check
        if current_version != update.expectedVersion:
            raise HTTPException(
                status_code=409,
                detail=f"Version conflict: expected {update.expectedVersion}, found {current_version}. Please refresh and retry."
            )
        
        # Build update
        update_dict = update.dict(exclude_unset=True, exclude={'expectedVersion'})
        new_version = current_version + 1
        
        update_expr = "SET updatedAt = :timestamp, version = :version, lastModifiedBy = :user"
        expr_values = {
            ':timestamp': datetime.utcnow().isoformat(),
            ':version': new_version,
            ':user': current_user
        }
        
        if update.owner is not None:
            update_expr += ", owner = :owner"
            expr_values[':owner'] = update.owner
        
        if update.department is not None:
            update_expr += ", department = :dept"
            expr_values[':dept'] = update.department
        
        if update.dataClassification is not None:
            update_expr += ", dataClassification = :class"
            expr_values[':class'] = update.dataClassification
        
        if update.governanceNotes is not None:
            update_expr += ", governanceNotes = :notes"
            expr_values[':notes'] = update.governanceNotes
        
        if update.approvedForProduction is not None:
            update_expr += ", approvedForProduction = :prod"
            expr_values[':prod'] = update.approvedForProduction
        
        # Compliance status is ALWAYS recalculated from risk score
        # Manual override removed to prevent governance gaps
        new_compliance = RiskCalculator.get_compliance_status(new_risk, agent_info)
        update_expr += ", complianceStatus = :status"
        expr_values[':status'] = new_compliance
        
        # Recalculate risk with new governance
        merged_gov = {**current, **update_dict}
        new_risk = RiskCalculator.calculate(agent_info, merged_gov)
        update_expr += ", riskScore = :risk"
        expr_values[':risk'] = Decimal(str(new_risk))
        
        # Update DynamoDB
        await gov_table.update_item(
            Key={'agentId': agent_id},
            UpdateExpression=update_expr,
            ExpressionAttributeValues=expr_values,
            ReturnValues='ALL_NEW'
        )
        
        # Clear cache
        agent_cache.clear()
        
        # Log audit event
        await log_audit_event(
            agent_id=agent_id,
            event_type="CONFIG_CHANGE",
            details=f"Governance updated by {current_user}: {json.dumps(update_dict)}",
            user_id=current_user
        )
        
        logger.info(f"Updated governance for agent {agent_id} by {current_user}")
        
        return {
            "agentId": agent_id,
            "status": "updated",
            "newRiskScore": new_risk,
            "newVersion": new_version,
            "message": "Governance metadata updated successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to update governance for {agent_id}")
        raise HTTPException(status_code=500, detail=f"Failed to update governance: {str(e)}")

@app.get("/api/agents/{agent_id}/audit")
@limiter.limit("10/second")
async def get_agent_audit(
    agent_id: str,
    request: Request,
    limit: int = Query(100, ge=1, le=1000),
    current_user: str = Depends(verify_token)
):
    """Get audit trail for specific agent"""
    try:
        audit_table = await get_dynamodb_table('AgentAuditLog')
        
        response = await audit_table.query(
            KeyConditionExpression='agentId = :aid',
            ExpressionAttributeValues={':aid': agent_id},
            ScanIndexForward=False,
            Limit=limit
        )
        
        events = serialize_for_json(response.get('Items', []))
        
        return {
            "agentId": agent_id,
            "events": events,
            "count": len(events)
        }
        
    except Exception as e:
        logger.exception(f"Failed to fetch audit log for {agent_id}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch audit log: {str(e)}")

@app.get("/api/stats")
@limiter.limit("5/second")
async def get_dashboard_stats(
    request: Request,
    current_user: str = Depends(verify_token)
):
    """Get aggregated statistics for dashboard"""
    try:
        # Fetch all agents (cached)
        agents = await list_agents(request, 0, 1000, current_user)
        
        total = len(agents)
        if total == 0:
            return {
                "totalAgents": 0,
                "compliance": {"green": 0, "yellow": 0, "red": 0, "percentGreen": 0},
                "averageRiskScore": 0,
                "withGuardrails": 0,
                "withoutGuardrails": 0,
                "approvedForProduction": 0,
                "pendingApproval": 0,
                "highRiskAgents": []
            }
        
        green = sum(1 for a in agents if a.complianceStatus == 'GREEN')
        yellow = sum(1 for a in agents if a.complianceStatus == 'YELLOW')
        red = sum(1 for a in agents if a.complianceStatus == 'RED')
        
        avg_risk = sum(a.riskScore for a in agents) / total
        with_guardrails = sum(1 for a in agents if a.guardrailConfiguration)
        approved_prod = sum(1 for a in agents if a.approvedForProduction)
        
        # High risk agents (top 10)
        high_risk = sorted(
            [a for a in agents if a.riskScore >= 75],
            key=lambda x: x.riskScore,
            reverse=True
        )[:10]
        
        return {
            "totalAgents": total,
            "compliance": {
                "green": green,
                "yellow": yellow,
                "red": red,
                "percentGreen": round((green / total) * 100, 1)
            },
            "averageRiskScore": round(avg_risk, 1),
            "withGuardrails": with_guardrails,
            "withoutGuardrails": total - with_guardrails,
            "approvedForProduction": approved_prod,
            "pendingApproval": total - approved_prod,
            "highRiskAgents": [
                {
                    "agentId": a.agentId,
                    "agentName": a.agentName,
                    "riskScore": a.riskScore,
                    "owner": a.owner,
                    "complianceStatus": a.complianceStatus
                }
                for a in high_risk
            ]
        }
        
    except Exception as e:
        logger.exception("Failed to calculate stats")
        raise HTTPException(status_code=500, detail=f"Failed to calculate stats: {str(e)}")

# Helper functions
async def log_audit_event(agent_id: str, event_type: str, details: str, user_id: str):
    """Log governance audit event to DynamoDB with TTL (1 year retention)"""
    try:
        audit_table = await get_dynamodb_table('AgentAuditLog')
        # Calculate TTL (1 year from now)
        ttl_timestamp = int((datetime.utcnow() + timedelta(days=365)).timestamp())
        
        await audit_table.put_item(Item={
            'agentId': agent_id,
            'timestamp': datetime.utcnow().isoformat(),
            'eventType': event_type,
            'details': details,
            'userId': user_id,
            'ttl': ttl_timestamp  # DynamoDB TTL attribute
        })
        logger.info(f"Audit event logged for agent {agent_id}")
    except Exception as e:
        # Audit logging failure should not break main flow
        logger.error(f"Failed to log audit event: {e}")

# Lambda handler for production
from mangum import Mangum
handler = Mangum(app, lifespan="off")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False,  # Disable reload in production
        workers=1  # Increase for production
    )