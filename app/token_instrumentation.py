"""
token_instrumentation.py

Thin wrapper around Vertex AI Gemini calls that captures token usage
from the API response and accumulates cost data into a run-level context.

Usage:
    from app.token_instrumentation import InstrumentedGemini

    gemini = InstrumentedGemini(model_name="gemini-2.5-flash", run_id="abc123")
    response_text = gemini.generate(prompt="Classify this document...", step_name="classify")
    cost_summary = gemini.get_cost_summary()
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
import vertexai
from vertexai.generative_models import GenerativeModel


# Current Vertex AI pricing (USD per 1,000 tokens) -- update as pricing changes
# Source: cloud.google.com/vertex-ai/generative-ai/pricing
PRICING = {
    "gemini-2.5-flash": {
        "input_per_1k":  0.000075,
        "output_per_1k": 0.000300,
    },
    "gemini-2.5-pro": {
        "input_per_1k":  0.001250,
        "output_per_1k": 0.010000,
    },
    "gemini-2.0-flash": {
        "input_per_1k":  0.000075,
        "output_per_1k": 0.000300,
    },
}

DEFAULT_PRICING = {
    "input_per_1k":  0.000075,
    "output_per_1k": 0.000300,
}


@dataclass
class StepCostRecord:
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
class RunCostAccumulator:
    """Accumulates cost data across all steps in a single pipeline run."""
    run_id: str
    agent_name: str
    workflow_name: str
    environment: str
    project_id: str
    region: str
    urgency: Optional[str] = None

    steps: list = field(default_factory=list)
    storage_reads: int = 0
    storage_writes: int = 0
    db_reads: int = 0
    db_writes: int = 0
    pubsub_messages: int = 0
    dlp_bytes_inspected: int = 0
    retry_count: int = 0
    pipeline_start_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def add_step(self, record: StepCostRecord):
        self.steps.append(record)

    def total_input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.steps)

    def total_output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.steps)

    def total_tokens(self) -> int:
        return sum(s.total_tokens for s in self.steps)

    def total_estimated_cost_usd(self) -> float:
        return sum(s.estimated_cost_usd for s in self.steps)

    def pipeline_latency_ms(self) -> int:
        return int(time.time() * 1000) - self.pipeline_start_ms

    def to_cost_events(self) -> list[dict]:
        """
        Returns a list of cost event dicts ready to insert into BigQuery.
        One dict per pipeline step.
        """
        import datetime
        events = []
        now = datetime.datetime.utcnow().isoformat() + "Z"

        for step in self.steps:
            events.append({
                "event_ts": now,
                "run_id": self.run_id,
                "agent_name": self.agent_name,
                "workflow_name": self.workflow_name,
                "step_name": step.step_name,
                "environment": self.environment,
                "project_id": self.project_id,
                "region": self.region,
                "model_name": step.model_name,
                "urgency": self.urgency,
                "input_tokens": step.input_tokens,
                "output_tokens": step.output_tokens,
                "total_tokens": step.total_tokens,
                "estimated_model_cost_usd": round(step.estimated_cost_usd, 8),
                "storage_reads": self.storage_reads,
                "storage_writes": self.storage_writes,
                "db_reads": self.db_reads,
                "db_writes": self.db_writes,
                "pubsub_messages": self.pubsub_messages,
                "dlp_bytes_inspected": self.dlp_bytes_inspected,
                "latency_ms": step.latency_ms,
                "retry_count": self.retry_count,
                "status": step.status,
                "error_message": step.error_message,
            })

        return events


class InstrumentedGemini:
    """
    Wrapper around Vertex AI GenerativeModel that captures token usage
    from usageMetadata after each generate_content call.

    Token counts are taken from the actual API response -- not estimated
    pre-call -- ensuring accuracy for cost accounting purposes.
    """

    def __init__(
        self,
        model_name: str,
        accumulator: RunCostAccumulator,
        project: str = None,
        location: str = "us-central1",
    ):
        self.model_name = model_name
        self.accumulator = accumulator
        self.pricing = PRICING.get(model_name, DEFAULT_PRICING)

        if project:
            vertexai.init(project=project, location=location)

        self.model = GenerativeModel(model_name)

    def generate(self, prompt: str, step_name: str) -> str:
        """
        Calls Gemini and captures token usage from the response.
        Returns the generated text.
        """
        start_ms = int(time.time() * 1000)
        status = "success"
        error_message = None
        response_text = ""
        input_tokens = 0
        output_tokens = 0

        try:
            response = self.model.generate_content(prompt)
            response_text = response.text

            # Capture actual token counts from API response metadata
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                input_tokens = response.usage_metadata.prompt_token_count or 0
                output_tokens = response.usage_metadata.candidates_token_count or 0
            else:
                # Fallback estimation if metadata unavailable
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
                (input_tokens / 1000) * self.pricing["input_per_1k"] +
                (output_tokens / 1000) * self.pricing["output_per_1k"]
            )

            self.accumulator.add_step(StepCostRecord(
                step_name=step_name,
                model_name=self.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            ))

        return response_text
