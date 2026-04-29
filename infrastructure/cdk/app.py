#!/usr/bin/env python3
"""
AWS CDK Stack for Agent Registry Governance Dashboard
Production-ready infrastructure with security hardening
"""
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_lambda as lambda_,
    aws_apigateway as apigw,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_iam as iam,
    aws_wafv2 as wafv2,
    aws_cloudwatch as cloudwatch,
    aws_logs as logs,
    RemovalPolicy,
    CfnOutput,
    Duration,
    Size,
)
from constructs import Construct


class AgentRegistryGovernanceStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Tags for cost tracking
        cdk.Tags.of(self).add("Project", "AgentRegistryGovernance")
        cdk.Tags.of(self).add("Environment", "Production")

        # ============================================
        # DYNAMODB TABLES
        # ============================================
        
        # Agent Governance table
        governance_table = dynamodb.Table(
            self, "AgentGovernance",
            table_name="AgentGovernance",
            partition_key=dynamodb.Attribute(
                name="agentId", 
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
        )
        
        # Enable CloudWatch contributor insights
        cdk.CfnResource(
            self, "GovernanceContributorInsights",
            type="AWS::DynamoDB::ContributorInsights",
            properties={
                "TableName": governance_table.table_name,
                "Enabled": True
            }
        )

        # Audit Log table with TTL
        audit_table = dynamodb.Table(
            self, "AgentAuditLog",
            table_name="AgentAuditLog",
            partition_key=dynamodb.Attribute(
                name="agentId", 
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            point_in_time_recovery=True,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
        )
        
        # Add TTL for audit logs (auto-delete after 1 year)
        audit_table.enable_ttl(attribute_name="ttl")

        # ============================================
        # LAMBDA FUNCTION (Backend API)
        # ============================================
        
        # Create Lambda execution role with least privilege
        lambda_role = iam.Role(
            self, "LambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole"),
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaVPCAccessExecutionRole"),
            ]
        )
        
        # Grant specific permissions
        governance_table.grant_read_write_data(lambda_role)
        audit_table.grant_read_write_data(lambda_role)
        
        # Bedrock permissions
        lambda_role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=[
                "bedrock:ListAgents",
                "bedrock:GetAgent",
                "bedrock:InvokeAgent",
            ],
            resources=["*"]
        ))

        # Lambda function
        backend_lambda = lambda_.Function(
            self, "BackendFunction",
            function_name="agent-registry-backend",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="main.handler",
            code=lambda_.Code.from_asset(
                "../../backend",
                exclude=["venv", "__pycache__", "*.pyc", ".env"]
            ),
            timeout=Duration.seconds(30),
            memory_size=1024,
            environment={
                "GOVERNANCE_TABLE": governance_table.table_name,
                "AUDIT_TABLE": audit_table.table_name,
                "LOG_LEVEL": "INFO",
                "POWERTOOLS_SERVICE_NAME": "agent-registry-governance",
            },
            role=lambda_role,
            tracing=lambda_.Tracing.ACTIVE,  # X-Ray tracing
            log_retention=logs.RetentionDays.ONE_WEEK,
            architecture=lambda_.Architecture.ARM_64,  # Graviton2 for cost savings
        )
        
        # Enable provisioned concurrency for production
        lambda_.Version(
            self, "BackendVersion",
            lambda_=backend_lambda,
            provisioned_concurrent_executions=2,
        )

        # ============================================
        # WAF (Web Application Firewall)
        # ============================================
        
        waf = wafv2.CfnWebACL(
            self, "ApiGatewayWAF",
            name="AgentRegistryApiWAF",
            description="WAF for Agent Registry API",
            scope="REGIONAL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name="AgentRegistryWAF"
            ),
            rules=[
                # AWS Managed Rules - Common
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=1,
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet"
                        )
                    ),
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSCommonRules"
                    )
                ),
                # Rate limiting
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitRule",
                    priority=2,
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=2000,  # 2000 requests per 5 minutes per IP
                            aggregate_key_type="IP"
                        )
                    ),
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="RateLimit"
                    )
                ),
            ]
        )

        # ============================================
        # API GATEWAY
        # ============================================
        
        api = apigw.RestApi(
            self, "AgentRegistryApi",
            rest_api_name="agent-registry-governance-api",
            description="Agent Registry Governance API",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                throttling_burst_limit=100,
                throttling_rate_limit=50,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                metrics_enabled=True,
                tracing_enabled=True,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=["*"],  # Restrict in production
                allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                allow_headers=["Authorization", "Content-Type", "X-Api-Key"],
                max_age=Duration.days(1),
            ),
        )
        
        # Associate WAF
        wafv2.CfnWebACLAssociation(
            self, "WafAssociation",
            resource_arn=api.deployment_stage.stage_arn,
            web_acl_arn=waf.attr_arn
        )

        # Lambda integration
        lambda_integration = apigw.LambdaIntegration(
            backend_lambda,
            proxy=True,
            integration_responses=[{
                "statusCode": "200",
                "responseParameters": {
                    "method.response.header.Access-Control-Allow-Origin": "'*'"
                }
            }]
        )
        
        # API Routes with usage plans
        api.root.add_method("GET", lambda_integration)  # Health check
        
        agents = api.root.add_resource("agents")
        agents.add_method("GET", lambda_integration, api_key_required=False)
        
        agent = agents.add_resource("{agent_id}")
        agent.add_method("GET", lambda_integration)
        agent.add_method("PUT", lambda_integration)  # Requires auth in Lambda
        
        agent_audit = agent.add_resource("audit")
        agent_audit.add_method("GET", lambda_integration)
        
        stats = api.root.add_resource("stats")
        stats.add_method("GET", lambda_integration)
        
        # Deploy API
        deployment = apigw.Deployment(
            self, "ApiDeployment",
            api=api,
            retain_deployments=False
        )

        # ============================================
        # S3 BUCKET (Frontend Hosting)
        # ============================================
        
        website_bucket = s3.Bucket(
            self, "WebsiteBucket",
            bucket_name=f"agent-registry-governance-{self.account}-{self.region}",
            website_index_document="index.html",
            website_error_document="index.html",
            public_read_access=False,  # Use CloudFront OAI
            removal_policy=RemovalPolicy.RETAIN,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=True,
        )
        
        # Grant CloudFront access
        origin_access_identity = cloudfront.OriginAccessIdentity(
            self, "CloudFrontOAI",
            comment="OAI for Agent Registry Website"
        )
        website_bucket.grant_read(origin_access_identity)

        # ============================================
        # CLOUDFRONT DISTRIBUTION
        # ============================================
        
        distribution = cloudfront.Distribution(
            self, "CloudFrontDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3Origin(
                    website_bucket,
                    origin_access_identity=origin_access_identity
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                cached_methods=cloudfront.CachedMethods.CACHE_GET_HEAD,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                origin_request_policy=cloudfront.OriginRequestPolicy.CORS_S3_ORIGIN,
            ),
            default_root_object="index.html",
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5)
                ),
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.minutes(5)
                )
            ],
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # North America/Europe
web_acl_id=cloudfront_waf.attr_arn,  # Attach WAF to CloudFront
        )
        
        # ============================================
        # CLOUDFRONT WAF (Global scope required)
        # ============================================
        
        cloudfront_waf = wafv2.CfnWebACL(
            self, "CloudFrontWAF",
            name="AgentRegistryCloudFrontWAF",
            description="WAF for CloudFront distribution",
            scope="CLOUDFRONT",  # Global scope required for CloudFront
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                sampled_requests_enabled=True,
                cloud_watch_metrics_enabled=True,
                metric_name="AgentRegistryCloudFrontWAF"
            ),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=1,
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet"
                        )
                    ),
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="CloudFrontCommonRules"
                    )
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitRule",
                    priority=2,
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=3000,  # Higher limit for web traffic
                            aggregate_key_type="IP"
                        )
                    ),
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        sampled_requests_enabled=True,
                        cloud_watch_metrics_enabled=True,
                        metric_name="CloudFrontRateLimit"
                    )
                ),
            ]
        )

        # ============================================
        # CLOUDWATCH ALARMS
        # ============================================
        
        # Lambda error alarm
        lambda_error_alarm = cloudwatch.Alarm(
            self, "LambdaErrorAlarm",
            metric=backend_lambda.metric_errors(),
            threshold=5,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            alarm_description="Alarm when lambda errors exceed threshold",
        )
        
        # API Gateway 5xx alarm
        api_5xx_alarm = cloudwatch.Alarm(
            self, "Api5xxAlarm",
            metric=api.metric_server_side_error_error(),
            threshold=10,
            evaluation_periods=2,
            datapoints_to_alarm=2,
            alarm_description="Alarm when API 5xx errors exceed threshold",
        )
        
        # DynamoDB throttling alarm
        dynamodb_throttle_alarm = cloudwatch.Alarm(
            self, "DynamoDBThrottleAlarm",
            metric=governance_table.metric_throttled_requests_for_operations(),
            threshold=1,
            evaluation_periods=1,
            alarm_description="Alarm when DynamoDB throttles requests",
        )

        # ============================================
        # OUTPUTS
        # ============================================
        
        CfnOutput(
            self, "ApiUrl",
            value=api.url,
            description="Backend API Gateway URL",
            export_name="AgentRegistryApiUrl"
        )
        
        CfnOutput(
            self, "CloudFrontUrl",
            value=f"https://{distribution.distribution_domain_name}",
            description="CloudFront Distribution URL (Frontend)",
            export_name="AgentRegistryFrontendUrl"
        )
        
        CfnOutput(
            self, "WebsiteBucket",
            value=website_bucket.bucket_name,
            description="S3 Bucket for Frontend",
            export_name="AgentRegistryWebsiteBucket"
        )
        
        CfnOutput(
            self, "CloudFrontDistributionId",
            value=distribution.distribution_id,
            description="CloudFront Distribution ID for invalidation",
            export_name="AgentRegistryDistributionId"
        )
        
        CfnOutput(
            self, "GovernanceTable",
            value=governance_table.table_name,
            description="DynamoDB Governance Table",
            export_name="AgentRegistryGovernanceTable"
        )
        
        CfnOutput(
            self, "AuditTable",
            value=audit_table.table_name,
            description="DynamoDB Audit Table",
            export_name="AgentRegistryAuditTable"
        )


# Stack entry point
app = cdk.App()
AgentRegistryGovernanceStack(
    app, 
    "AgentRegistryGovernanceStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account") or app.account,
        region=app.node.try_get_context("region") or "us-east-1"
    ),
    tags={
        "Project": "AgentRegistryGovernance",
        "Owner": "PlatformTeam",
        "CostCenter": "Engineering"
    }
)
app.synth()