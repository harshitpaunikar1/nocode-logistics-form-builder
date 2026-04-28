"""
Form builder API and submission handler for the no-code logistics form builder.
Manages form registry, submission storage, and export capabilities.
"""
import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from schema import FormSchema, LogisticsFormTemplates

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS form_registry (
    form_id TEXT PRIMARY KEY,
    title TEXT,
    schema_json TEXT,
    created_at REAL,
    updated_at REAL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS form_submissions (
    submission_id TEXT PRIMARY KEY,
    form_id TEXT NOT NULL,
    submitted_at REAL,
    submitted_by TEXT,
    response_json TEXT,
    is_valid INTEGER DEFAULT 1,
    validation_errors TEXT DEFAULT '{}'
);
"""


class FormRegistry:
    """Stores and manages form schemas in a SQLite database."""

    def __init__(self, db_path: str = ":memory:"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(DB_SCHEMA)
        self._conn.commit()

    def register(self, schema: FormSchema) -> bool:
        now = time.time()
        try:
            self._conn.execute(
                "INSERT OR REPLACE INTO form_registry VALUES (?, ?, ?, ?, ?, ?)",
                (schema.form_id, schema.title, schema.to_json(), now, now, 1),
            )
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("Failed to register form %s: %s", schema.form_id, exc)
            return False

    def get(self, form_id: str) -> Optional[FormSchema]:
        row = self._conn.execute(
            "SELECT schema_json FROM form_registry WHERE form_id = ? AND is_active = 1",
            (form_id,)
        ).fetchone()
        if not row:
            return None
        return FormSchema.from_json(row["schema_json"])

    def list_forms(self) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT form_id, title, created_at, is_active FROM form_registry"
        ).fetchall()
        return [dict(r) for r in rows]

    def deactivate(self, form_id: str) -> bool:
        self._conn.execute(
            "UPDATE form_registry SET is_active = 0 WHERE form_id = ?", (form_id,)
        )
        self._conn.commit()
        return True


class SubmissionStore:
    """Stores and queries form submissions."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, form_id: str, submission_id: str, response: Dict[str, Any],
             submitted_by: str, errors: Dict) -> bool:
        try:
            self._conn.execute(
                "INSERT INTO form_submissions VALUES (?, ?, ?, ?, ?, ?, ?)",
                (submission_id, form_id, time.time(), submitted_by,
                 json.dumps(response), int(not errors), json.dumps(errors)),
            )
            self._conn.commit()
            return True
        except Exception as exc:
            logger.error("Submission save failed: %s", exc)
            return False

    def get_submissions(self, form_id: str, valid_only: bool = False) -> List[Dict]:
        sql = "SELECT * FROM form_submissions WHERE form_id = ?"
        params = [form_id]
        if valid_only:
            sql += " AND is_valid = 1"
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def submission_count(self, form_id: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM form_submissions WHERE form_id = ?", (form_id,)
        ).fetchone()[0]

    def to_dataframe(self, form_id: str):
        try:
            import pandas as pd
            submissions = self.get_submissions(form_id)
            rows = []
            for s in submissions:
                response = json.loads(s.get("response_json", "{}"))
                row = {"submission_id": s["submission_id"],
                       "submitted_at": s["submitted_at"],
                       "submitted_by": s["submitted_by"],
                       "is_valid": s["is_valid"]}
                row.update(response)
                rows.append(row)
            return pd.DataFrame(rows)
        except ImportError:
            return submissions


class FormBuilderService:
    """
    End-to-end form builder: register forms, collect submissions, validate, and export.
    """

    def __init__(self, db_path: str = ":memory:"):
        self.registry = FormRegistry(db_path)
        self.submissions = SubmissionStore(self.registry._conn)

    def create_form(self, schema: FormSchema) -> bool:
        return self.registry.register(schema)

    def submit(self, form_id: str, response: Dict[str, Any],
               submitted_by: str = "anonymous") -> Dict:
        schema = self.registry.get(form_id)
        if not schema:
            return {"success": False, "error": f"Form '{form_id}' not found."}
        errors = schema.validate_response(response)
        submission_id = f"{form_id}_{int(time.time() * 1000)}"
        saved = self.submissions.save(form_id, submission_id, response, submitted_by, errors)
        return {
            "success": saved,
            "submission_id": submission_id,
            "is_valid": not bool(errors),
            "validation_errors": errors,
        }

    def export_csv(self, form_id: str, output_path: str) -> bool:
        try:
            df = self.submissions.to_dataframe(form_id)
            if hasattr(df, "to_csv"):
                df.to_csv(output_path, index=False)
                logger.info("Exported %d rows to %s", len(df), output_path)
                return True
            return False
        except Exception as exc:
            logger.error("Export failed: %s", exc)
            return False

    def dashboard_stats(self, form_id: str) -> Dict:
        schema = self.registry.get(form_id)
        if not schema:
            return {}
        total = self.submissions.submission_count(form_id)
        valid_submissions = self.submissions.get_submissions(form_id, valid_only=True)
        return {
            "form_id": form_id,
            "title": schema.title if schema else "",
            "total_submissions": total,
            "valid_submissions": len(valid_submissions),
            "field_count": len(schema.fields) if schema else 0,
        }


if __name__ == "__main__":
    service = FormBuilderService(db_path=":memory:")
    dock_form = LogisticsFormTemplates.dock_inspection_form()
    trailer_form = LogisticsFormTemplates.trailer_intake_form()
    service.create_form(dock_form)
    service.create_form(trailer_form)

    print(f"Registered forms: {[f['title'] for f in service.registry.list_forms()]}")

    test_submissions = [
        {"dock_number": "D-07", "inspection_date": "2024-04-15",
         "dock_status": "clear", "inspector_gps": "28.6139,77.2090"},
        {"dock_number": "", "inspection_date": "2024-04-15",
         "dock_status": "damaged"},
        {"dock_number": "D-12", "inspection_date": "2024-04-15",
         "dock_status": "occupied", "inspector_gps": "28.7,77.1"},
    ]

    for i, resp in enumerate(test_submissions):
        result = service.submit("dock_inspection_v1", resp, submitted_by=f"user_{i+1}")
        print(f"\nSubmission {i+1}: valid={result['is_valid']} errors={result['validation_errors']}")

    print("\nDashboard stats:", service.dashboard_stats("dock_inspection_v1"))
