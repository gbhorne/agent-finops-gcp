"""
cost_tracker.py

Shared cost tracking layer used by both the ADK agent and the
Vertex AI Agent Builder agent. Captures real token counts from
Vertex AI usageMetadata and writes structured cost events to BigQuery.

This is the core instrumentation module for the Agent FinOps build.
"""

import time
import uuid
import datetime
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

import vertexai
from vertexai.generative_models import GenerativeModel
from google.cloud import bigquery

# GCP config
PROJECT_ID = os.environ.get("GCP_PROJECT", "finops-gcp-agent")
LOCATION = os.environ.get("LOCATION", "us-central1")
BQ_DATASET = os.environ.get("BQ_DATASET_RAW", "agent_finops_raw")
BQ_TABLE = os.environ.get("BQ_TABLE_EVENTS", "agent_cost_events")

# Vertex AI pricing—USD per 1,000 tokens (March 2026)
# Source: cloud.google.com/vertex-ai/generative-ai/pricing
PRICING = {
    "gemini-2.5-flash": {
        "input_per_1k": 0.000075,
        "output_per_1k": 0.000300,
    },
    "gemini-2.5-pro": {
        "input_per_1k": 0.001250,
        "output_per_1k": 0.010000,
    },
}
DEFAULT_PRICING = {"input_per_1k": 0.000075, "output_per_1k": 0.000300}

vertexai.init(project=PROJECT_ID, location=LOCATION)


@dataclass
class StepCost:
    step_name: str
    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: int
    status: str
    error_message: Optional[str] = None


@dataclass
class RunTracker:
    """
    Tracks cost across all steps of a single pipeline run.
    Create one per pipeline run. Call add_step() after each LLM call.
    Call to_bq_rows() at the end to get rows ready for BigQuery insert.
    """
    agent_name: str
    workflow_name: str
    environment: str = "production"
    urgency: Optional[str] = None
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    steps: list = field(default_factory=list)
    pipeline_start_ms: int = field(
        default_factory=lambda: int(time.time() * 1000)
    )

    def add_step(self, step: StepCost):
        self.steps.append(step)

    def total_cost(self) -> float:
        return sum(s.estimated_cost_usd for s in self.steps)

    def total_tokens(self) -> int:
        return sum(s.total_tokens for s in self.steps)

    def pipeline_latency_ms(self) -> int:
        return int(time.time() * 1000) - self.pipeline_start_ms

    def to_bq_rows(self) -> list[dict]:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        rows = []
        for step in self.steps:
            rows.append({
                "event_ts": now,
                "run_id": self.run_id,
                "agent_name": self.agent_name,
                "workflow_name": self.workflow_name,
                "step_name": step.step_name,
                "environment": self.environment,
                "project_id": PROJECT_ID,
                "region": LOCATION,
                "model_name": step.model_name,
                "request_type": "generate_content",
                "urgency": self.urgency,
                "input_tokens": step.input_tokens,
                "output_tokens": step.output_tokens,
                "total_tokens": step.total_tokens,
                "estimated_model_cost_usd": round(step.estimated_cost_usd, 8),
                "storage_reads": 0,
                "storage_writes": 0,
                "db_reads": 0,
                "db_writes": 1 if step.step_name == self.steps[-1].step_name else 0,
                "pubsub_messages": 0,
                "dlp_bytes_inspected": 0,
                "latency_ms": step.latency_ms,
                "retry_count": 0,
                "status": step.status,
                "error_message": step.error_message,
                "resource_labels": None,
            })
        return rows

    def summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "agent_name": self.agent_name,
            "workflow_name": self.workflow_name,
            "urgency": self.urgency,
            "total_steps": len(self.steps),
            "total_tokens": self.total_tokens(),
            "total_cost_usd": round(self.total_cost(), 8),
            "pipeline_latency_ms": self.pipeline_latency_ms(),
            "status": "success" if all(s.status == "success" for s in self.steps) else "error",
        }


def gemini_call(
    prompt: str,
    step_name: str,
    tracker: RunTracker,
    model_name: str = "gemini-2.5-flash",
) -> str:
    """
    Makes a Gemini call, captures real token counts from usageMetadata,
    calculates cost, and records the step in the tracker.

    Returns the generated text.
    """
    model = GenerativeModel(model_name)
    pricing = PRICING.get(model_name, DEFAULT_PRICING)

    start_ms = int(time.time() * 1000)
    status = "success"
    error_message = None
    response_text = ""
    input_tokens = 0
    output_tokens = 0

    try:
        response = model.generate_content(prompt)
        response_text = response.text

        # Capture ACTUAL token counts from API response
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = response.usage_metadata.prompt_token_count or 0
            output_tokens = response.usage_metadata.candidates_token_count or 0
        else:
            # Fallback if metadata unavailable
            input_tokens = len(prompt) // 4
            output_tokens = len(response_text) // 4

    except Exception as e:
        status = "error"
        error_message = str(e)
        input_tokens = len(prompt) // 4
        raise
    finally:
        latency_ms = int(time.time() * 1000) - start_ms
        total_tokens = input_tokens + output_tokens
        estimated_cost = (
            (input_tokens / 1000) * pricing["input_per_1k"] +
            (output_tokens / 1000) * pricing["output_per_1k"]
        )

        tracker.add_step(StepCost(
            step_name=step_name,
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost,
            latency_ms=latency_ms,
            status=status,
            error_message=error_message,
        ))

        print(f"  [{step_name}] tokens: {input_tokens}in + {output_tokens}out = {total_tokens} | "
              f"cost: ${estimated_cost:.8f} | latency: {latency_ms}ms")

    return response_text


def write_to_bigquery(tracker: RunTracker) -> bool:
    """
    Writes all cost events from the tracker to BigQuery.
    Returns True on success, False on failure.
    Uses write_safe pattern—never blocks the pipeline on cost logging failure.
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)
        table_ref = f"{PROJECT_ID}.{BQ_DATASET}.{BQ_TABLE}"
        rows = tracker.to_bq_rows()
        errors = client.insert_rows_json(table_ref, rows)
        if errors:
            print(f"  [BigQuery] WARNING: Insert errors: {errors[:1]}")
            return False
        print(f"  [BigQuery] Wrote {len(rows)} cost event rows for run {tracker.run_id[:8]}...")
        return True
    except Exception as e:
        print(f"  [BigQuery] WARNING: Failed to write cost events: {e}")
        return False
