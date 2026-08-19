"""Small deterministic ledger double for focused memory-operation tests."""

import copy
import time

from core.operation_ledger import (
    OperationConflictError,
    OperationRecord,
    OperationStatus,
    QuarantineReason,
    canonical_plan_json,
)


class InMemoryOperationLedger:
    def __init__(self):
        self.records = {}

    @staticmethod
    def _replace(record, **changes):
        values = {
            "schema_version": record.schema_version,
            "op_id": record.op_id,
            "op_type": record.op_type,
            "status": record.status,
            "revision": record.revision,
            "plan": copy.deepcopy(record.plan),
            "plan_json": record.plan_json,
            "plan_sha256": record.plan_sha256,
            "created_at_ns": record.created_at_ns,
            "updated_at_ns": record.updated_at_ns,
            "quarantine_reason": record.quarantine_reason,
        }
        values.update(changes)
        return OperationRecord(**values)

    def create_or_get_plan(self, op_id, op_type, plan):
        detached, plan_json = canonical_plan_json(plan)
        existing = self.records.get(op_id)
        if existing is not None:
            if existing.op_type != op_type or existing.plan_json != plan_json:
                raise OperationConflictError("test operation plan conflict")
            return existing
        now = time.time_ns()
        record = OperationRecord(
            schema_version=1,
            op_id=op_id,
            op_type=op_type,
            status=OperationStatus.PLANNED,
            revision=0,
            plan=detached,
            plan_json=plan_json,
            plan_sha256="0" * 64,
            created_at_ns=now,
            updated_at_ns=now,
        )
        self.records[op_id] = record
        return record

    def get(self, op_id):
        return self.records.get(op_id)

    def compare_and_swap(
        self,
        op_id,
        *,
        expected_revision,
        expected_status,
        new_status,
    ):
        record = self.records[op_id]
        expected_status = OperationStatus(expected_status)
        new_status = OperationStatus(new_status)
        if (
            record.revision != expected_revision
            or record.status is not expected_status
        ):
            return False
        self.records[op_id] = self._replace(
            record,
            status=new_status,
            revision=record.revision + 1,
            updated_at_ns=record.updated_at_ns + 1,
        )
        return True

    def list_recoverable(self, *, op_type=None, limit=1000):
        return [
            record
            for record in self.records.values()
            if record.status in {OperationStatus.PLANNED, OperationStatus.APPLYING}
            and (op_type is None or record.op_type == op_type)
        ][:limit]

    def quarantine(
        self,
        op_id,
        *,
        reason,
        expected_revision=None,
        expected_status=None,
    ):
        record = self.records[op_id]
        if expected_revision is not None and record.revision != expected_revision:
            return False
        if (
            expected_status is not None
            and record.status is not OperationStatus(expected_status)
        ):
            return False
        self.records[op_id] = self._replace(
            record,
            status=OperationStatus.QUARANTINED,
            revision=record.revision + 1,
            updated_at_ns=record.updated_at_ns + 1,
            quarantine_reason=QuarantineReason(reason),
        )
        return True
