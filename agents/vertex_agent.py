"""
vertex_agent.py

Vertex AI Agent Builder -- Document Analysis Agent with live cost instrumentation.

This is the same two-step classify-and-summarize pipeline as the ADK agent,
implemented as a standalone Python script that runs against Vertex AI directly.
It is designed to be deployed as a Vertex AI Agent Builder custom tool or
run standalone for cost comparison against the ADK implementation.

Both agents write to the same BigQuery table (agent_finops_raw.agent_cost_events)
with different agent_name values:
  ADK agent:    adk-doc-analyzer
  Vertex agent: vertex-doc-analyzer

This enables side-by-side framework cost comparison in Looker Studio.

Run standalone: python -m agents.vertex_agent
"""

import json
import sys
from agents.cost_tracker import RunTracker, gemini_call, write_to_bigquery


def analyze_document_vertex(text: str, environment: str = "production") -> dict:
    """
    Two-step document analysis pipeline instrumented for cost tracking.
    Identical logic to the ADK agent -- different agent_name tag.

    Args:
        text: Document text to analyze
        environment: production, staging, or development

    Returns:
        Dict with classification, summary, and cost tracking data
    """
    print(f"\nStarting Vertex AI Agent Builder document analysis pipeline...")
    print(f"Input length: {len(text)} characters\n")

    tracker = RunTracker(
        agent_name="vertex-doc-analyzer",
        workflow_name="classify-and-summarize",
        environment=environment,
    )

    # Step 1: Classify
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

    # Step 2: Summarize
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

    cost_summary = tracker.summary()

    return {
        "status": "success",
        "run_id": tracker.run_id,
        "agent": "vertex-doc-analyzer",
        "classification": classification,
        "summary": summary,
        "cost_tracking": {
            "total_tokens": cost_summary["total_tokens"],
            "total_cost_usd": cost_summary["total_cost_usd"],
            "pipeline_latency_ms": cost_summary["pipeline_latency_ms"],
            "steps": len(tracker.steps),
            "bigquery_table": "finops-gcp-agent.agent_finops_raw.agent_cost_events",
        }
    }


# Vertex AI Agent Builder tool schema
# This function signature is used when registering as a custom tool
def run_analysis(text: str) -> str:
    """
    Analyzes a document or text input. Classifies the document type and
    priority, then generates a structured summary with key points and
    action items. Tracks real Gemini token costs in BigQuery.

    Args:
        text: The document or text content to analyze

    Returns:
        JSON string containing classification, summary, and cost data
    """
    result = analyze_document_vertex(text)
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    # Standalone test runner
    sample_texts = [
        {
            "label": "Business memo (LOW priority expected)",
            "text": """
            TO: All Staff
            FROM: Office Manager
            RE: Kitchen Refrigerator Policy

            Please label all food items with your name and the date.
            Items older than one week will be discarded every Friday.
            Please keep the refrigerator clean and organized.
            Thank you for your cooperation.
            """
        },
        {
            "label": "Technical report (MEDIUM priority expected)",
            "text": """
            Q1 2026 Infrastructure Performance Report

            Our cloud infrastructure handled 2.4 million API requests in Q1 2026,
            representing a 34% increase over Q4 2025. Average response latency
            improved from 180ms to 142ms following the CDN optimization deployed
            in February. Uptime achieved 99.97% against a 99.9% SLA target.

            Three incidents occurred during the quarter. The most significant was
            a 45-minute degradation on March 3rd caused by a database connection
            pool exhaustion. Root cause was a misconfigured connection limit
            introduced in the February 28th deployment. The fix was deployed within
            2 hours and a post-mortem was completed on March 10th.

            Recommendations for Q2: increase connection pool limits, implement
            automated connection pool monitoring alerts, and schedule a load test
            before the anticipated Q2 traffic spike.
            """
        },
        {
            "label": "Contract excerpt (HIGH priority expected)",
            "text": """
            SERVICE AGREEMENT

            This Service Agreement is entered into as of January 1, 2026 between
            Acme Corporation and TechVendor Inc.

            1. SERVICES: TechVendor shall provide software development services
            as detailed in Exhibit A, including API integration, testing, and
            documentation.

            2. PAYMENT TERMS: Client shall pay $25,000 per month, due within
            30 days of invoice. Late payments incur 1.5% monthly interest.

            3. INTELLECTUAL PROPERTY: All work product created under this agreement
            is work-for-hire and becomes the sole property of Acme Corporation.

            4. CONFIDENTIALITY: Both parties agree to maintain strict confidentiality
            of proprietary information for 3 years following termination.

            5. TERMINATION: Either party may terminate with 30 days written notice.
            Acme may terminate immediately for material breach.

            6. LIABILITY: TechVendor liability is limited to fees paid in the
            preceding 3 months. Neither party liable for consequential damages.
            """
        }
    ]

    print("=" * 60)
    print("Vertex AI Agent Builder -- Document Analysis Agent")
    print("Cost Instrumentation Demo")
    print("=" * 60)

    total_cost = 0.0
    total_tokens = 0

    for i, sample in enumerate(sample_texts, 1):
        print(f"\nRun {i}/3: {sample['label']}")
        print("-" * 40)

        result = analyze_document_vertex(sample["text"].strip())

        cost = result["cost_tracking"]["total_cost_usd"]
        tokens = result["cost_tracking"]["total_tokens"]
        priority = result["classification"].get("priority", "unknown")
        doc_type = result["classification"].get("document_type", "unknown")

        total_cost += cost
        total_tokens += tokens

        print(f"\n  Classification: {doc_type} | Priority: {priority}")
        print(f"  Tokens: {tokens} | Cost: ${cost:.8f}")
        print(f"  Run ID: {result['run_id']}")

    print("\n" + "=" * 60)
    print("COST SUMMARY -- ALL RUNS")
    print("=" * 60)
    print(f"Total runs:   3")
    print(f"Total tokens: {total_tokens:,}")
    print(f"Total cost:   ${total_cost:.8f}")
    print(f"Cost/run avg: ${total_cost/3:.8f}")
    print(f"\nCost events written to:")
    print(f"  finops-gcp-agent.agent_finops_raw.agent_cost_events")
    print(f"\nQuery in BigQuery console:")
    print(f"  SELECT * FROM `finops-gcp-agent.agent_finops_raw.agent_cost_events`")
    print(f"  ORDER BY event_ts DESC LIMIT 10;")
