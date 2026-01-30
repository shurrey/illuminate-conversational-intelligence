"""
Validator Agent - LLM-as-a-Judge for Response Validation

This agent validates responses from worker agents to ensure:
1. SQL correctness and safety
2. Data accuracy and consistency
3. FERPA compliance (no PII leakage)
4. Hallucination detection
5. Response quality and relevance

Uses Claude Sonnet for fast, accurate validation.
"""

import logging
import re
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

from agents.shared.llm_client import get_validator_llm, LLMClient
from agents.shared.models import Artifact, QueryResult

logger = logging.getLogger("VALIDATOR")


class ValidationStatus(Enum):
    """Validation result status."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    NEEDS_REVIEW = "needs_review"


class ValidationCategory(Enum):
    """Categories of validation checks."""
    SQL_SAFETY = "sql_safety"
    SQL_CORRECTNESS = "sql_correctness"
    DATA_ACCURACY = "data_accuracy"
    FERPA_COMPLIANCE = "ferpa_compliance"
    HALLUCINATION = "hallucination"
    RESPONSE_QUALITY = "response_quality"
    AGGREGATION_THRESHOLD = "aggregation_threshold"


@dataclass
class ValidationCheck:
    """Result of a single validation check."""
    category: ValidationCategory
    status: ValidationStatus
    message: str
    details: Optional[str] = None
    confidence: float = 1.0


@dataclass
class ValidationResult:
    """Complete validation result for a response."""
    overall_status: ValidationStatus
    confidence_score: float  # 0.0 to 1.0
    checks: list[ValidationCheck] = field(default_factory=list)
    original_response: Optional[str] = None
    validated_response: Optional[str] = None  # May be modified for compliance
    recommendations: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "overall_status": self.overall_status.value,
            "confidence_score": self.confidence_score,
            "checks": [
                {
                    "category": c.category.value,
                    "status": c.status.value,
                    "message": c.message,
                    "details": c.details,
                    "confidence": c.confidence
                }
                for c in self.checks
            ],
            "recommendations": self.recommendations,
            "blocked": self.blocked,
            "block_reason": self.block_reason
        }


# FERPA-protected fields that should never appear in responses
FERPA_PII_PATTERNS = [
    r'\b\d{3}-\d{2}-\d{4}\b',  # SSN
    r'\b\d{9}\b',              # SSN without dashes
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',  # Email (in certain contexts)
    r'\b\d{10}\b',             # Phone numbers
    r'\b\(\d{3}\)\s*\d{3}-\d{4}\b',  # Phone with parentheses
]

# SQL injection and dangerous patterns
DANGEROUS_SQL_PATTERNS = [
    r'\bDROP\s+TABLE\b',
    r'\bDROP\s+DATABASE\b',
    r'\bDELETE\s+FROM\b',
    r'\bTRUNCATE\b',
    r'\bUPDATE\s+.*\s+SET\b',
    r'\bINSERT\s+INTO\b',
    r'\bALTER\s+TABLE\b',
    r'\bCREATE\s+TABLE\b',
    r'\bGRANT\b',
    r'\bREVOKE\b',
    r';\s*--',  # SQL comment injection
    r'\bUNION\s+SELECT\b',  # Union injection
    r'\bEXEC\s*\(',  # Execute
    r'\bxp_\w+',  # Extended stored procedures
]

# Minimum aggregation threshold for FERPA compliance
MIN_AGGREGATION_THRESHOLD = 5


class ValidatorAgent:
    """
    Validator Agent that acts as LLM-as-a-Judge.

    Validates all responses before they are returned to users.
    """

    def __init__(self):
        """Initialize the Validator Agent."""
        self.llm: LLMClient = get_validator_llm(caller="VALIDATOR")
        self._validation_system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build the system prompt for validation."""
        return """You are a Validation Agent for an educational data analytics system.
Your role is to validate responses before they are shown to users.

IMPORTANT CONTEXT: The specialist agents execute SQL queries via MCP tools internally.
You may not always see the SQL queries, but if the response contains specific statistics,
percentages, counts, or structured data tables, ASSUME the data came from real database queries.
Do NOT block responses just because you cannot see the underlying SQL.

You must check for:

1. **SQL Safety** (only if SQL is provided): Ensure no dangerous SQL operations
2. **Data Plausibility**: Check that numeric results are internally consistent
   - Percentages should sum to ~100%
   - Counts should be reasonable for educational data
   - Statistics should be mathematically consistent
3. **FERPA Compliance** (CRITICAL): Ensure no personally identifiable information (PII) is exposed
   - No individual student names in grade contexts
   - No SSNs, phone numbers, or personal emails
   - Aggregations must have at least 5 individuals
4. **Response Quality**: Ensure the response addresses the user's question

DO NOT block responses for:
- Containing specific statistics without visible SQL (the agent queried the database internally)
- Presenting data in table format (this is expected behavior)
- Follow-up questions that reference previous data
- Visualization/formatting requests for previously queried data

ONLY block responses for:
- Clear PII violations (individual student names, SSNs, emails)
- Data that is mathematically impossible or clearly fabricated
- Dangerous SQL if provided

When validating, respond with a JSON object:
{
    "overall_status": "passed" | "failed" | "warning" | "needs_review",
    "confidence_score": 0.0-1.0,
    "checks": [
        {
            "category": "sql_safety" | "data_accuracy" | "ferpa_compliance" | "response_quality" | "aggregation_threshold",
            "status": "passed" | "failed" | "warning",
            "message": "Brief description",
            "details": "Detailed explanation if needed"
        }
    ],
    "recommendations": ["List of suggestions to improve the response"],
    "should_block": true | false,
    "block_reason": "Reason if blocked (only for PII violations or impossible data)",
    "corrected_response": "Modified response if needed for compliance (or null)"
}

Be strict about FERPA/PII compliance. Be lenient about data source verification since agents query internally."""

    async def validate(
        self,
        user_query: str,
        response_text: str,
        sql_query: Optional[str] = None,
        query_result: Optional[QueryResult] = None,
        artifacts: Optional[list[Artifact]] = None
    ) -> ValidationResult:
        """
        Validate a response before returning to user.

        Args:
            user_query: The original user question
            response_text: The generated response text
            sql_query: The SQL query that was executed (if any)
            query_result: The result from the database (if any)
            artifacts: Any data artifacts (tables, charts)

        Returns:
            ValidationResult with status and any modifications
        """
        logger.info("Starting response validation")

        # Run quick rule-based checks first
        rule_checks = self._run_rule_based_checks(response_text, sql_query, query_result)

        # If any rule-based check fails critically, don't even call LLM
        critical_failures = [c for c in rule_checks if c.status == ValidationStatus.FAILED]
        if critical_failures:
            return ValidationResult(
                overall_status=ValidationStatus.FAILED,
                confidence_score=1.0,
                checks=rule_checks,
                original_response=response_text,
                blocked=True,
                block_reason=critical_failures[0].message
            )

        # Run LLM-based validation for deeper analysis
        llm_result = await self._run_llm_validation(
            user_query, response_text, sql_query, query_result, artifacts
        )

        # Combine results
        all_checks = rule_checks + llm_result.checks

        # Determine overall status
        if any(c.status == ValidationStatus.FAILED for c in all_checks):
            overall_status = ValidationStatus.FAILED
        elif any(c.status == ValidationStatus.WARNING for c in all_checks):
            overall_status = ValidationStatus.WARNING
        elif any(c.status == ValidationStatus.NEEDS_REVIEW for c in all_checks):
            overall_status = ValidationStatus.NEEDS_REVIEW
        else:
            overall_status = ValidationStatus.PASSED

        # Calculate confidence
        confidence_scores = [c.confidence for c in all_checks]
        avg_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 1.0

        return ValidationResult(
            overall_status=overall_status,
            confidence_score=avg_confidence,
            checks=all_checks,
            original_response=response_text,
            validated_response=llm_result.validated_response or response_text,
            recommendations=llm_result.recommendations,
            blocked=llm_result.blocked or overall_status == ValidationStatus.FAILED,
            block_reason=llm_result.block_reason
        )

    def _run_rule_based_checks(
        self,
        response_text: str,
        sql_query: Optional[str],
        query_result: Optional[QueryResult]
    ) -> list[ValidationCheck]:
        """Run fast rule-based validation checks."""
        checks = []

        # Check for PII patterns in response
        for pattern in FERPA_PII_PATTERNS:
            if re.search(pattern, response_text, re.IGNORECASE):
                checks.append(ValidationCheck(
                    category=ValidationCategory.FERPA_COMPLIANCE,
                    status=ValidationStatus.FAILED,
                    message="Potential PII detected in response",
                    details=f"Pattern matched: {pattern}",
                    confidence=0.95
                ))
                break
        else:
            checks.append(ValidationCheck(
                category=ValidationCategory.FERPA_COMPLIANCE,
                status=ValidationStatus.PASSED,
                message="No obvious PII patterns detected",
                confidence=0.8  # Rule-based check has lower confidence
            ))

        # Check SQL safety
        if sql_query:
            sql_upper = sql_query.upper()
            for pattern in DANGEROUS_SQL_PATTERNS:
                if re.search(pattern, sql_query, re.IGNORECASE):
                    checks.append(ValidationCheck(
                        category=ValidationCategory.SQL_SAFETY,
                        status=ValidationStatus.FAILED,
                        message="Dangerous SQL pattern detected",
                        details=f"Pattern: {pattern}",
                        confidence=1.0
                    ))
                    break
            else:
                checks.append(ValidationCheck(
                    category=ValidationCategory.SQL_SAFETY,
                    status=ValidationStatus.PASSED,
                    message="SQL query passes safety checks",
                    confidence=0.9
                ))

        # Check aggregation threshold
        if query_result and query_result.row_count > 0:
            # Check if any aggregation group is too small
            if query_result.row_count < MIN_AGGREGATION_THRESHOLD:
                # This might be individual records, not aggregations
                # Flag for LLM review
                checks.append(ValidationCheck(
                    category=ValidationCategory.AGGREGATION_THRESHOLD,
                    status=ValidationStatus.WARNING,
                    message=f"Result has only {query_result.row_count} rows - verify aggregation level",
                    details="Small result sets may reveal individual student data",
                    confidence=0.7
                ))

        return checks

    async def _run_llm_validation(
        self,
        user_query: str,
        response_text: str,
        sql_query: Optional[str],
        query_result: Optional[QueryResult],
        artifacts: Optional[list[Artifact]]
    ) -> ValidationResult:
        """Run LLM-based deep validation."""
        # Build context for LLM
        context_parts = [
            f"## User Query\n{user_query}",
            f"\n## Generated Response\n{response_text}"
        ]

        if sql_query:
            context_parts.append(f"\n## SQL Query Executed\n```sql\n{sql_query}\n```")

        if query_result:
            # Include sample of results (not full data)
            sample_data = query_result.data[:5] if query_result.data else []
            context_parts.append(
                f"\n## Query Result Summary\n"
                f"- Columns: {query_result.columns}\n"
                f"- Row count: {query_result.row_count}\n"
                f"- Sample data (first 5 rows): {sample_data}"
            )

        if artifacts:
            artifact_summary = [
                {"type": a.type, "title": a.title}
                for a in artifacts
            ]
            context_parts.append(f"\n## Artifacts Generated\n{artifact_summary}")

        validation_prompt = "\n".join(context_parts)
        validation_prompt += "\n\n## Task\nValidate this response according to your validation criteria. Return your assessment as JSON."

        try:
            result = await self.llm.invoke_with_json_response(
                system_prompt=self._validation_system_prompt,
                user_message=validation_prompt,
                temperature=0.1  # Very low for consistent validation
            )

            # Parse LLM response
            checks = []
            for check_data in result.get("checks", []):
                try:
                    checks.append(ValidationCheck(
                        category=ValidationCategory(check_data.get("category", "response_quality")),
                        status=ValidationStatus(check_data.get("status", "passed")),
                        message=check_data.get("message", ""),
                        details=check_data.get("details"),
                        confidence=0.85  # LLM checks have good but not perfect confidence
                    ))
                except (ValueError, KeyError) as e:
                    logger.warning(f"Failed to parse check: {e}")

            return ValidationResult(
                overall_status=ValidationStatus(result.get("overall_status", "passed")),
                confidence_score=result.get("confidence_score", 0.8),
                checks=checks,
                validated_response=result.get("corrected_response"),
                recommendations=result.get("recommendations", []),
                blocked=result.get("should_block", False),
                block_reason=result.get("block_reason")
            )

        except Exception as e:
            logger.error(f"LLM validation failed: {e}")
            # Return a conservative result on LLM failure
            return ValidationResult(
                overall_status=ValidationStatus.NEEDS_REVIEW,
                confidence_score=0.5,
                checks=[ValidationCheck(
                    category=ValidationCategory.RESPONSE_QUALITY,
                    status=ValidationStatus.NEEDS_REVIEW,
                    message="LLM validation unavailable - manual review recommended",
                    details=str(e),
                    confidence=0.5
                )],
                recommendations=["Manual review recommended due to validation system error"]
            )

    async def validate_sql_intent(
        self,
        user_query: str,
        generated_sql: str
    ) -> ValidationCheck:
        """
        Validate that generated SQL matches user intent.

        This is a focused check specifically for SQL correctness.
        """
        prompt = f"""Analyze if this SQL query correctly answers the user's question.

User Question: {user_query}

Generated SQL:
```sql
{generated_sql}
```

Respond with JSON:
{{
    "matches_intent": true | false,
    "confidence": 0.0-1.0,
    "issues": ["list of any issues found"],
    "explanation": "brief explanation"
}}"""

        try:
            result = await self.llm.invoke_with_json_response(
                system_prompt="You are a SQL expert validating query correctness.",
                user_message=prompt,
                temperature=0.1
            )

            status = ValidationStatus.PASSED if result.get("matches_intent", False) else ValidationStatus.FAILED
            return ValidationCheck(
                category=ValidationCategory.SQL_CORRECTNESS,
                status=status,
                message=result.get("explanation", "SQL validation complete"),
                details="; ".join(result.get("issues", [])) if result.get("issues") else None,
                confidence=result.get("confidence", 0.8)
            )

        except Exception as e:
            logger.error(f"SQL intent validation failed: {e}")
            return ValidationCheck(
                category=ValidationCategory.SQL_CORRECTNESS,
                status=ValidationStatus.NEEDS_REVIEW,
                message="Could not validate SQL intent",
                details=str(e),
                confidence=0.5
            )


# Singleton instance
_validator_agent: Optional[ValidatorAgent] = None


def get_validator_agent() -> ValidatorAgent:
    """Get or create the Validator Agent singleton."""
    global _validator_agent
    if _validator_agent is None:
        _validator_agent = ValidatorAgent()
    return _validator_agent


async def validate_response(
    user_query: str,
    response_text: str,
    sql_query: Optional[str] = None,
    query_result: Optional[QueryResult] = None,
    artifacts: Optional[list[Artifact]] = None
) -> ValidationResult:
    """
    Convenience function to validate a response.

    Args:
        user_query: The original user question
        response_text: The generated response text
        sql_query: The SQL query that was executed (if any)
        query_result: The result from the database (if any)
        artifacts: Any data artifacts (tables, charts)

    Returns:
        ValidationResult with status and any modifications
    """
    agent = get_validator_agent()
    return await agent.validate(
        user_query=user_query,
        response_text=response_text,
        sql_query=sql_query,
        query_result=query_result,
        artifacts=artifacts
    )
