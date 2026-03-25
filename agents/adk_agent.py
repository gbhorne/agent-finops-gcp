"""
adk_agent.py

ADK Document Analysis Agent with live cost instrumentation.

This agent accepts a text input, classifies the document type and priority,
generates a structured summary, and writes real cost events to BigQuery.

Every Gemini call captures actual token counts from usageMetadata --
the same data Vertex AI uses for billing—and calculates per-step cost.

Launch: adk web (from repo root, with GOOGLE_GENAI_USE_VERTEXAI=true)
"""

import json
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from agents.cost_tracker import RunTracker, gemini_call, write_to_bigquery


def analyze_document(text: str) -> str:
    """
    Analyzes an input document using a two-step pipeline:
    Step 1: classify: document type, priority, topic
    Step 2: summarize: structured summary with key points

    Tracks real Gemini token costs and writes to BigQuery after each run.

    Args:
        text: The document or text to analyze

    Returns:
        JSON string with analysis results and cost summary
    """
    print(f"\nStarting ADK document analysis pipeline...")
    print(f"Input length: {len(text)} characters\n")

    tracker = RunTracker(
        agent_name="adk-doc-analyzer",
        workflow_name="classify-and-summarize",
        environment="production",
    )

    # Step 1: Classify the document
    classify_prompt = f"""You are a document classification assistant.

Analyze the following text and return a JSON object with these fields:
- document_type: one of [business_memo, technical_report, legal_document, news_article, email, contract, other]
- priority: one of [LOW, MEDIUM, HIGH, CRITICAL]
- primary_topic: a 3-5 word description of the main topic
- estimated_read_time_minutes: integer estimate
- language: detected language

Return valid JSON only. No preamble, no markdown.

TEXT:
{text[:3000]}"""

    classification_raw = gemini_call(
        prompt=classify_prompt,
        step_name="classify_document",
        tracker=tracker,
    )

    # Parse classification
    try:
        if "```" in classification_raw:
            classification_raw = classification_raw.split("```")[1]
            if classification_raw.startswith("json"):
                classification_raw = classification_raw[4:]
        classification = json.loads(classification_raw.strip())
        tracker.urgency = classification.get("priority", "MEDIUM")
    except Exception:
        classification = {
            "document_type": "unknown",
            "priority": "MEDIUM",
            "primary_topic": "Unable to classify",
            "estimated_read_time_minutes": 0,
            "language": "unknown"
        }
        tracker.urgency = "MEDIUM"

    # Step 2: Generate structured summary
    summarize_prompt = f"""You are a professional document summarizer.

Document type: {classification.get('document_type', 'unknown')}
Priority: {classification.get('priority', 'MEDIUM')}
Topic: {classification.get('primary_topic', 'unknown')}

Summarize the following text with these sections:
1. EXECUTIVE SUMMARY (2-3 sentences)
2. KEY POINTS (3-5 bullet points)
3. ACTION ITEMS (if any, otherwise state "None identified")
4. RECOMMENDED NEXT STEPS (1-2 sentences)

Be concise and professional.

TEXT:
{text[:3000]}"""

    summary = gemini_call(
        prompt=summarize_prompt,
        step_name="generate_summary",
        tracker=tracker,
    )

    # Write cost events to BigQuery
    write_to_bigquery(tracker)

    # Build result
    cost_summary = tracker.summary()

    result = {
        "status": "success",
        "run_id": tracker.run_id,
        "agent": "adk-doc-analyzer",
        "classification": classification,
        "summary": summary,
        "cost_tracking": {
            "total_tokens": cost_summary["total_tokens"],
            "total_cost_usd": cost_summary["total_cost_usd"],
            "pipeline_latency_ms": cost_summary["pipeline_latency_ms"],
            "steps": len(tracker.steps),
            "bigquery_table": f"finops-gcp-agent.agent_finops_raw.agent_cost_events",
        }
    }

    return json.dumps(result, indent=2)


root_agent = Agent(
    name="adk_document_analyzer",
    model="gemini-2.5-flash",
    description=(
        "A document analysis agent that classifies and summarizes text inputs. "
        "Every run tracks real Gemini token costs and writes cost events to BigQuery "
        "for FinOps observability and cost analysis."
    ),
    instruction="""You are a document analysis agent with built-in cost tracking.

When a user provides text to analyze, call analyze_document with that text.

The pipeline will:
1. Classify the document type, priority, and topic (Gemini call 1)
2. Generate a structured summary with key points and action items (Gemini call 2)
3. Write real token cost data to BigQuery automatically

After the analysis completes, report:
- The document classification results
- The structured summary
- The cost tracking data: total tokens consumed, estimated cost in USD, and pipeline latency

This demonstrates how real Gemini API costs are captured per pipeline run and written
to BigQuery for financial observability.""",
    tools=[FunctionTool(analyze_document)],
)
