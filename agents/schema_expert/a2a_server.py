#!/usr/bin/env python3
"""
Schema Expert Agent - Self-contained A2A server for AgentCore deployment.

Deep knowledge of the CDM (Common Data Model) schema. Given a natural language
question, identifies the specific tables, columns, and joins needed and returns
a focused "mini-schema" so the SQL agent doesn't have to reason over the entire
database.

Loaded with CDM domain knowledge: table relationships, column meanings, common
join patterns, and Illuminate-specific concepts (enrollment, terms, GPA, etc.).
"""
import json
import os
import sys
from pathlib import Path


def log(msg):
    print(msg, file=sys.stderr, flush=True)


# Load .env.agentcore
env_file = Path(__file__).parent / ".env.agentcore"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        if key and value and key not in os.environ:
            os.environ[key] = value
    log(f"Loaded {env_file}")

log("Importing dependencies ...")
from strands import Agent, tool
from strands.models import BedrockModel
from strands.multiagent.a2a.executor import StrandsA2AExecutor
from bedrock_agentcore.runtime.a2a import build_a2a_app


# --- CDM Schema Knowledge Base ---
# This is the embedded knowledge of the CDM data model. In production, this
# could be loaded from the data dictionary API at startup.

CDM_SCHEMA_KNOWLEDGE = {
    "CDM_LMS": {
        "description": "Learning Management System common data model — core educational data",
        "tables": {
            "PERSON": {
                "description": "All people in the system (students, instructors, admins)",
                "key_columns": {
                    "PERSON_ID": "Primary key — unique identifier for a person",
                    "INSTITUTION_ROLE": "Role: 'S' = Student, 'I' = Instructor, 'A' = Admin",
                    "FIRST_NAME": "Person's first name (PII — never expose in results)",
                    "LAST_NAME": "Person's last name (PII — never expose in results)",
                    "EMAIL": "Email address (PII — never expose in results)",
                    "STATUS": "Active/Inactive status",
                },
                "common_filters": [
                    "INSTITUTION_ROLE = 'S'  -- filter to students only",
                    "INSTITUTION_ROLE = 'I'  -- filter to instructors only",
                    "STATUS = 'ACTIVE'       -- active persons only",
                ],
                "pii_columns": ["FIRST_NAME", "LAST_NAME", "EMAIL", "PHONE", "SSN", "DATE_OF_BIRTH"],
            },
            "COURSE": {
                "description": "Course catalog — all courses offered",
                "key_columns": {
                    "COURSE_ID": "Primary key — unique identifier for a course",
                    "NAME": "Course display name",
                    "COURSE_NUMBER": "Catalog number (e.g., CS101)",
                    "DEPARTMENT": "Academic department",
                    "TERM_ID": "Foreign key to TERM — which term this course offering belongs to",
                    "STATUS": "Course status (Active, Inactive, Completed)",
                },
                "common_filters": [
                    "STATUS = 'ACTIVE'  -- active courses only",
                ],
            },
            "PERSON_COURSE": {
                "description": "Enrollment records — links persons to courses (many-to-many)",
                "key_columns": {
                    "PERSON_COURSE_ID": "Primary key",
                    "PERSON_ID": "Foreign key to PERSON",
                    "COURSE_ID": "Foreign key to COURSE",
                    "TERM_ID": "Foreign key to TERM",
                    "ROLE": "Role in this course: 'S' = Student, 'I' = Instructor",
                    "STATUS": "Enrollment status: ENROLLED, COMPLETED, WITHDRAWN, DROPPED",
                    "ENROLLMENT_DATE": "When the person enrolled",
                },
                "common_joins": [
                    "JOIN PERSON ON PERSON_COURSE.PERSON_ID = PERSON.PERSON_ID",
                    "JOIN COURSE ON PERSON_COURSE.COURSE_ID = COURSE.COURSE_ID",
                    "JOIN TERM ON PERSON_COURSE.TERM_ID = TERM.TERM_ID",
                ],
                "common_filters": [
                    "ROLE = 'S'           -- student enrollments only",
                    "STATUS = 'COMPLETED' -- completed enrollments",
                    "STATUS = 'ENROLLED'  -- currently enrolled",
                ],
            },
            "GRADE": {
                "description": "Grade records — grades assigned to students in courses",
                "key_columns": {
                    "GRADE_ID": "Primary key",
                    "PERSON_ID": "Foreign key to PERSON (student)",
                    "COURSE_ID": "Foreign key to COURSE",
                    "TERM_ID": "Foreign key to TERM",
                    "GRADE_LETTER": "Letter grade (A, B, C, D, F, W, I, P, etc.)",
                    "GRADE_NUMERIC": "*** USE THIS FOR GPA *** Numeric GPA value on 4.0 scale. ALWAYS use this column for GPA calculations, never use normalized or percentage-based score columns.",
                    "GRADE_TYPE": "Type of grade (FINAL, MIDTERM, etc.)",
                },
                "warnings": [
                    "CRITICAL: For GPA calculations, ALWAYS use GRADE_NUMERIC (4.0 scale). The table may also have normalized score columns (0-1 scale) — do NOT use those for GPA. GPA must be on a 4.0 scale.",
                ],
                "common_joins": [
                    "JOIN PERSON ON GRADE.PERSON_ID = PERSON.PERSON_ID",
                    "JOIN COURSE ON GRADE.COURSE_ID = COURSE.COURSE_ID",
                    "JOIN TERM ON GRADE.TERM_ID = TERM.TERM_ID",
                ],
                "common_filters": [
                    "GRADE_NUMERIC IS NOT NULL  -- exclude non-numeric grades",
                    "GRADE_TYPE = 'FINAL'       -- final grades only",
                ],
            },
            "TERM": {
                "description": "Academic terms/semesters",
                "key_columns": {
                    "TERM_ID": "Primary key",
                    "NAME": "Term display name (e.g., 'Fall 2024', 'Spring 2025')",
                    "START_DATE": "Term start date",
                    "END_DATE": "Term end date",
                    "TERM_TYPE": "Type: SEMESTER, QUARTER, etc.",
                },
                "common_filters": [
                    "START_DATE <= CURRENT_DATE() AND END_DATE >= CURRENT_DATE()  -- current term",
                ],
            },
            "ASSIGNMENT": {
                "description": "Course assignments/assessments",
                "key_columns": {
                    "ASSIGNMENT_ID": "Primary key",
                    "COURSE_ID": "Foreign key to COURSE",
                    "NAME": "Assignment title",
                    "DUE_DATE": "When the assignment is due",
                    "POINTS_POSSIBLE": "Maximum points for the assignment",
                    "ASSIGNMENT_TYPE": "Type: HOMEWORK, EXAM, QUIZ, PROJECT, etc.",
                },
            },
            "SUBMISSION": {
                "description": "Student submissions for assignments",
                "key_columns": {
                    "SUBMISSION_ID": "Primary key",
                    "ASSIGNMENT_ID": "Foreign key to ASSIGNMENT",
                    "PERSON_ID": "Foreign key to PERSON (student who submitted)",
                    "SUBMITTED_DATE": "When the submission was made",
                    "SCORE": "Points earned",
                    "STATUS": "Submission status: SUBMITTED, GRADED, LATE, MISSING",
                },
                "common_joins": [
                    "JOIN ASSIGNMENT ON SUBMISSION.ASSIGNMENT_ID = ASSIGNMENT.ASSIGNMENT_ID",
                    "JOIN PERSON ON SUBMISSION.PERSON_ID = PERSON.PERSON_ID",
                ],
            },
        },
        "common_join_patterns": {
            "enrollment_with_details": {
                "description": "Full enrollment record with person, course, and term details",
                "sql_pattern": (
                    "FROM PERSON_COURSE pc "
                    "JOIN PERSON p ON pc.PERSON_ID = p.PERSON_ID "
                    "JOIN COURSE c ON pc.COURSE_ID = c.COURSE_ID "
                    "JOIN TERM t ON pc.TERM_ID = t.TERM_ID"
                ),
            },
            "grades_with_context": {
                "description": "Grade records with course and term information",
                "sql_pattern": (
                    "FROM GRADE g "
                    "JOIN COURSE c ON g.COURSE_ID = c.COURSE_ID "
                    "JOIN TERM t ON g.TERM_ID = t.TERM_ID"
                ),
            },
            "submissions_with_assignments": {
                "description": "Submission records with assignment and course details",
                "sql_pattern": (
                    "FROM SUBMISSION s "
                    "JOIN ASSIGNMENT a ON s.ASSIGNMENT_ID = a.ASSIGNMENT_ID "
                    "JOIN COURSE c ON a.COURSE_ID = c.COURSE_ID"
                ),
            },
        },
        "domain_concepts": {
            "enrollment": "A PERSON_COURSE record where a student is linked to a course. Count enrollments = COUNT(*) or COUNT(DISTINCT PERSON_ID) from PERSON_COURSE.",
            "student_count": "COUNT of PERSON records with INSTITUTION_ROLE = 'S'.",
            "instructor_count": "COUNT of PERSON records with INSTITUTION_ROLE = 'I'.",
            "GPA": "Average of GRADE_NUMERIC from GRADE table. GRADE_NUMERIC is on a 4.0 scale (0.0-4.0). NEVER use normalized score columns for GPA — always use GRADE_NUMERIC. Filter with GRADE_NUMERIC IS NOT NULL.",
            "completion_rate": "Percentage of enrollments with STATUS = 'COMPLETED' out of all enrollments.",
            "retention": "Students who enroll in consecutive terms. Requires self-join on PERSON_COURSE across terms.",
            "grade_distribution": "COUNT of each GRADE_LETTER grouped by letter grade.",
            "course_load": "Number of courses per student per term — COUNT(DISTINCT COURSE_ID) from PERSON_COURSE grouped by PERSON_ID and TERM_ID.",
        },
    },
}


# --- System Prompt ---
SCHEMA_EXPERT_SYSTEM_PROMPT = """You are the Schema Expert Agent for an educational data analytics system.
You have deep knowledge of the CDM (Common Data Model) schema used in Illuminate.

## Your Role
Given a natural language question, you identify the specific tables, columns, and joins needed
to answer it. You return a focused "mini-schema" — just the relevant parts — so the SQL agent
doesn't have to reason over the entire database.

## Your Knowledge
You know:
- Every table in the CDM_LMS schema, its purpose, and its columns
- How tables relate to each other (foreign keys, join patterns)
- Illuminate-specific domain concepts (enrollment, GPA, completion rate, retention)
- Which columns are PII and must never appear in SELECT output
- Common join patterns for typical educational analytics queries

## How to Respond
Use the `get_schema_guidance` tool to receive the question, then return:
1. **Relevant Tables**: Which tables are needed and why
2. **Key Columns**: The specific columns to SELECT, JOIN on, or filter by
3. **Join Pattern**: The exact JOIN clauses needed
4. **PII Warning**: Which columns are PII and must be excluded from results
5. **FERPA Notes**: Aggregation requirements (minimum group size of 5)
6. **Domain Notes**: Any domain-specific knowledge relevant to the question

## FERPA Compliance
- ALWAYS flag PII columns (FIRST_NAME, LAST_NAME, EMAIL, PHONE, SSN, DATE_OF_BIRTH)
- Remind that results must be aggregated (minimum 5 individuals per group)
- PERSON_ID should be used only for JOINs, never in final SELECT output

## Important
- Be specific about column names — use the exact CDM column names
- Include the full join path if multiple tables are needed
- Mention common pitfalls (e.g., PERSON has both students and instructors, filter by INSTITUTION_ROLE)
- If you're not sure about a table/column, say so — don't guess"""


@tool
def get_schema_guidance(question: str, context: str = "") -> str:
    """Receive a question and return relevant schema information from the CDM knowledge base.

    Args:
        question: The natural language question to find schema information for.
        context: Optional additional context (e.g., from the planner or previous steps).

    Returns:
        CDM schema knowledge base as structured context for the agent to reason over.
    """
    # Return the full schema knowledge base — the agent reasons over it
    # to produce a focused mini-schema for the specific question
    knowledge_text = json.dumps(CDM_SCHEMA_KNOWLEDGE, indent=2)

    parts = [
        f"## User Question\n{question}",
    ]
    if context:
        parts.append(f"\n## Additional Context\n{context}")
    parts.append(f"\n## CDM Schema Knowledge Base\n```json\n{knowledge_text}\n```")
    parts.append(
        "\n## Your Task\n"
        "Based on the question, identify the specific tables, columns, and joins needed. "
        "Return a focused mini-schema with:\n"
        "1. Tables needed and why\n"
        "2. Key columns (for SELECT, JOIN, WHERE, GROUP BY)\n"
        "3. Exact JOIN pattern SQL\n"
        "4. PII columns to avoid\n"
        "5. FERPA aggregation notes\n"
        "6. Any domain-specific guidance for this question"
    )

    return "\n".join(parts)


# --- Create Strands Agent ---
log("Creating Bedrock model + Strands Agent ...")
model_id = os.environ.get(
    "BEDROCK_MODEL_ID",
    "us.anthropic.claude-sonnet-4-6",
)

# Bedrock Guardrails — FERPA compliance filter runs before/after LLM inference
guardrail_id = os.environ.get("BEDROCK_GUARDRAIL_ID", "")
guardrail_version = os.environ.get("BEDROCK_GUARDRAIL_VERSION", "")
guardrail_config = None
if guardrail_id and guardrail_version:
    guardrail_config = {
        "guardrailIdentifier": guardrail_id,
        "guardrailVersion": guardrail_version,
        "trace": "enabled",
    }
    log(f"  Guardrail: {guardrail_id} v{guardrail_version}")

bedrock_model = BedrockModel(
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    model_id=model_id,
    additional_model_request_fields={
        "inferenceConfig": {"temperature": 0.0},
        **({"amazon-bedrock-guardrailConfig": guardrail_config} if guardrail_config else {}),
    },
)
log(f"  Model: {model_id} (temperature=0.0)")

strands_agent = Agent(
    name="Illuminate Schema Expert Agent",
    description="Identifies relevant CDM tables, columns, and joins for a given question. Returns focused mini-schemas for the SQL agent.",
    model=bedrock_model,
    tools=[get_schema_guidance],
    system_prompt=SCHEMA_EXPERT_SYSTEM_PROMPT,
    callback_handler=None,
)

executor = StrandsA2AExecutor(strands_agent)
log("DONE: Agent initialized")

# Build the Starlette app with /ping and A2A routes
app = build_a2a_app(executor)
log("App built (Starlette with /ping + A2A routes)")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "9000"))
    log(f"Starting uvicorn on 0.0.0.0:{port} ...")
    uvicorn.run(app, host="0.0.0.0", port=port)
