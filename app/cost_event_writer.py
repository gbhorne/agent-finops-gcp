"""
cost_event_writer.py

Writes accumulated pipeline cost events to BigQuery.
Called at the end of every pipeline run from the final step.

Usage:
    from app.cost_event_writer import CostEventWriter

    writer = CostEventWriter(project_id="finops-demo-2026")
    writer.write(accumulator)
"""

from google.cloud import bigquery
from app.token_instrumentation import RunCostAccumulator


DATASET = "agent_finops_raw"
TABLE = "agent_cost_events"


class CostEventWriter:
    def __init__(self, project_id: str):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)
        self.table_ref = f"{project_id}.{DATASET}.{TABLE}"

    def write(self, accumulator: RunCostAccumulator) -> int:
        """
        Writes all step-level cost events from the accumulator to BigQuery.
        Returns the number of rows inserted.
        Raises on insert error—caller should handle and log.
        """
        events = accumulator.to_cost_events()
        if not events:
            return 0

        errors = self.client.insert_rows_json(self.table_ref, events)
        if errors:
            raise RuntimeError(
                f"BigQuery insert errors for run {accumulator.run_id}: {errors}"
            )

        return len(events)

    def write_safe(self, accumulator: RunCostAccumulator) -> int:
        """
        Same as write() but catches and logs errors rather than raising.
        Use in production pipelines where cost logging should not block
        the primary workflow on failure.
        """
        try:
            return self.write(accumulator)
        except Exception as e:
            print(f"[CostEventWriter] WARNING: Failed to write cost events for "
                  f"run {accumulator.run_id}: {e}")
            return 0
