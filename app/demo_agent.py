"""
demo_agent.py

Simulates agent pipeline runs with realistic token and cost data.
Use this to populate BigQuery with demo data before connecting Looker Studio.

Simulates three agent types across three urgency levels:
- document-classifier (STANDARD / COMPLEX)
- contract-analyzer (ROUTINE / COMPLEX / LEGAL_REVIEW)
- support-router (LOW / MEDIUM / HIGH)

Run: python -m app.demo_agent --runs 500 --project finops-demo-2026
"""

import argparse
import random
import time
import uuid
import datetime
from google.cloud import bigquery

PROJECT_ID = "finops-demo-2026"
DATASET = "agent_finops_raw"
TABLE = "agent_cost_events"

# Gemini 2.5 Flash pricing
INPUT_COST_PER_1K = 0.000075
OUTPUT_COST_PER_1K = 0.000300

AGENTS = {
    "document-classifier": {
        "workflow": "classify-and-route",
        "steps": [
            {"name": "extract_metadata", "input_range": (300, 600), "output_range": (50, 120)},
            {"name": "classify_document", "input_range": (600, 1200), "output_range": (80, 200)},
            {"name": "write_audit_record", "input_range": (0, 0), "output_range": (0, 0)},
        ],
        "urgency_levels": ["STANDARD", "COMPLEX"],
        "urgency_weights": [0.70, 0.30],
        "complex_multiplier": 1.6,
    },
    "contract-analyzer": {
        "workflow": "analyze-and-summarize",
        "steps": [
            {"name": "load_document", "input_range": (0, 0), "output_range": (0, 0)},
            {"name": "classify_contract_type", "input_range": (800, 1500), "output_range": (100, 250)},
            {"name": "extract_obligations", "input_range": (3000, 6000), "output_range": (400, 800)},
            {"name": "generate_summary", "input_range": (4000, 8000), "output_range": (600, 1200)},
            {"name": "write_audit_record", "input_range": (0, 0), "output_range": (0, 0)},
        ],
        "urgency_levels": ["ROUTINE", "COMPLEX", "LEGAL_REVIEW"],
        "urgency_weights": [0.55, 0.30, 0.15],
        "complex_multiplier": 1.8,
    },
    "support-router": {
        "workflow": "triage-and-route",
        "steps": [
            {"name": "classify_inquiry", "input_range": (400, 800), "output_range": (60, 150)},
            {"name": "extract_context", "input_range": (1500, 3000), "output_range": (200, 400)},
            {"name": "generate_recommendation", "input_range": (2000, 4000), "output_range": (300, 600)},
            {"name": "route_case", "input_range": (0, 0), "output_range": (0, 0)},
        ],
        "urgency_levels": ["LOW", "MEDIUM", "HIGH"],
        "urgency_weights": [0.60, 0.30, 0.10],
        "complex_multiplier": 1.4,
    },
}


def estimate_cost(input_tokens: int, output_tokens: int) -> float:
    return (
        (input_tokens / 1000) * INPUT_COST_PER_1K +
        (output_tokens / 1000) * OUTPUT_COST_PER_1K
    )


def simulate_run(agent_name: str, agent_config: dict, environment: str, run_date: datetime.date) -> list[dict]:
    run_id = str(uuid.uuid4())
    urgency = random.choices(
        agent_config["urgency_levels"],
        weights=agent_config["urgency_weights"]
    )[0]

    is_complex = urgency in ["COMPLEX", "LEGAL_REVIEW", "HIGH"]
    multiplier = agent_config["complex_multiplier"] if is_complex else 1.0

    # Occasional retry spike (2% of runs)
    retry_count = random.choices([0, 1, 2, 3], weights=[0.94, 0.04, 0.015, 0.005])[0]

    # Occasional error (1% of runs)
    status = random.choices(["success", "error"], weights=[0.99, 0.01])[0]

    base_latency = random.randint(8000, 45000)
    events = []

    for step in agent_config["steps"]:
        in_lo, in_hi = step["input_range"]
        out_lo, out_hi = step["output_range"]

        if in_hi == 0:
            input_tokens = 0
            output_tokens = 0
        else:
            input_tokens = int(random.randint(in_lo, in_hi) * multiplier)
            output_tokens = int(random.randint(out_lo, out_hi) * multiplier)

        total_tokens = input_tokens + output_tokens
        estimated_cost = estimate_cost(input_tokens, output_tokens)
        step_latency = int(random.randint(500, 8000) * multiplier)

        # Simulate a timestamp spread across the run date
        hour = random.randint(0, 23)
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        event_ts = datetime.datetime.combine(
            run_date,
            datetime.time(hour, minute, second)
        ).isoformat() + "Z"

        events.append({
            "event_ts": event_ts,
            "run_id": run_id,
            "agent_name": agent_name,
            "workflow_name": agent_config["workflow"],
            "step_name": step["name"],
            "environment": environment,
            "project_id": PROJECT_ID,
            "region": "us-central1",
            "model_name": "gemini-2.5-flash" if total_tokens > 0 else "none",
            "request_type": "generate_content" if total_tokens > 0 else "service_call",
            "urgency": urgency,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "estimated_model_cost_usd": round(estimated_cost, 8),
            "storage_reads": random.randint(1, 5) if step["name"] in ["load_document", "extract_context"] else 0,
            "storage_writes": 1 if step["name"] == "write_audit_record" else 0,
            "db_reads": random.randint(1, 3),
            "db_writes": 1 if step["name"] == "write_audit_record" else 0,
            "pubsub_messages": 1 if step["name"] in ["route_case", "write_audit_record"] else 0,
            "dlp_bytes_inspected": len("sample content") * output_tokens if output_tokens > 0 else 0,
            "latency_ms": step_latency,
            "retry_count": retry_count if step["name"] == agent_config["steps"][-1]["name"] else 0,
            "status": status,
            "error_message": "Transient API error" if status == "error" and step["name"] == agent_config["steps"][-1]["name"] else None,
            "resource_labels": None,
        })

    return events


def load_demo_data(num_runs: int, project_id: str, days_back: int = 30):
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{DATASET}.{TABLE}"

    all_events = []
    today = datetime.date.today()

    print(f"Generating {num_runs} simulated pipeline runs across {days_back} days...")

    for i in range(num_runs):
        agent_name = random.choice(list(AGENTS.keys()))
        agent_config = AGENTS[agent_name]
        environment = random.choices(["production", "staging"], weights=[0.85, 0.15])[0]
        run_date = today - datetime.timedelta(days=random.randint(0, days_back - 1))

        events = simulate_run(agent_name, agent_config, environment, run_date)
        all_events.extend(events)

        if (i + 1) % 100 == 0:
            print(f"  Generated {i + 1} runs ({len(all_events)} events)...")

    # Insert in batches of 500
    batch_size = 500
    total_inserted = 0
    for i in range(0, len(all_events), batch_size):
        batch = all_events[i:i + batch_size]
        errors = client.insert_rows_json(table_ref, batch)
        if errors:
            print(f"  WARNING: Insert errors in batch {i // batch_size}: {errors[:2]}")
        else:
            total_inserted += len(batch)

    print(f"\nInserted {total_inserted} cost events into {table_ref}")
    print(f"Runs: {num_runs} | Agents: {len(AGENTS)} | Days: {days_back}")
    print("\nRun the BigQuery views in sql/03_runtime_views.sql to verify the data.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load demo agent cost data into BigQuery")
    parser.add_argument("--runs", type=int, default=500, help="Number of simulated pipeline runs")
    parser.add_argument("--project", type=str, default=PROJECT_ID, help="GCP project ID")
    parser.add_argument("--days", type=int, default=30, help="Days of historical data to simulate")
    args = parser.parse_args()

    load_demo_data(args.runs, args.project, args.days)
