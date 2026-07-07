"""BigQuery telemetry exporter configuration.

Port of: src/utils/telemetry/bigqueryExporter.ts
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class BigQueryExporterConfig:
    project_id: str = ""
    dataset: str = ""
    table: str = ""
    credentials_json: str | None = None


def create_bigquery_exporter(_config: BigQueryExporterConfig) -> Any:
    """Stub exporter until GCP client is available."""
    return None
