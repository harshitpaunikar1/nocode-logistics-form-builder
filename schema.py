"""
Form schema definition engine for the no-code logistics form builder.
Defines field types, validation rules, conditional logic, and JSON schema export.
"""
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union


class FieldType(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    DROPDOWN = "dropdown"
    MULTI_SELECT = "multi_select"
    CHECKBOX = "checkbox"
    PHOTO = "photo"
    BARCODE = "barcode"
    SIGNATURE = "signature"
    GPS_LOCATION = "gps_location"
    FILE_UPLOAD = "file_upload"


class ConditionOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    IS_EMPTY = "is_empty"
    IS_NOT_EMPTY = "is_not_empty"


@dataclass
class ValidationRule:
    rule_type: str           # required, min_length, max_length, regex, min_value, max_value
    value: Any = None
    error_message: str = ""


@dataclass
class ConditionalLogic:
    source_field_id: str
    operator: ConditionOperator
    compare_value: Any
    action: str              # show, hide, require, disable


@dataclass
class FormField:
    field_id: str
    label: str
    field_type: FieldType
    placeholder: str = ""
    default_value: Any = None
    options: List[str] = field(default_factory=list)    # for dropdown/multi_select
    validations: List[ValidationRule] = field(default_factory=list)
    conditions: List[ConditionalLogic] = field(default_factory=list)
    help_text: str = ""
    required: bool = False
    order: int = 0

    def to_dict(self) -> Dict:
        return {
            "field_id": self.field_id,
            "label": self.label,
            "type": self.field_type.value,
            "placeholder": self.placeholder,
            "default_value": self.default_value,
            "options": self.options,
            "validations": [{"rule": v.rule_type, "value": v.value, "message": v.error_message}
                            for v in self.validations],
            "conditions": [{"source": c.source_field_id, "operator": c.operator.value,
                             "compare": c.compare_value, "action": c.action}
                           for c in self.conditions],
            "help_text": self.help_text,
            "required": self.required,
            "order": self.order,
        }


class FormSchema:
    """
    Defines a complete logistics form schema with fields, sections, and metadata.
    Supports JSON export, validation, and conditional field rendering.
    """

    def __init__(self, form_id: str, title: str, description: str = "",
                 version: str = "1.0"):
        self.form_id = form_id
        self.title = title
        self.description = description
        self.version = version
        self.fields: List[FormField] = []
        self._field_index: Dict[str, FormField] = {}

    def add_field(self, form_field: FormField) -> "FormSchema":
        form_field.order = form_field.order or len(self.fields)
        self.fields.append(form_field)
        self._field_index[form_field.field_id] = form_field
        return self

    def get_field(self, field_id: str) -> Optional[FormField]:
        return self._field_index.get(field_id)

    def required_fields(self) -> List[FormField]:
        return [f for f in self.fields if f.required]

    def to_json(self, indent: int = 2) -> str:
        schema = {
            "form_id": self.form_id,
            "title": self.title,
            "description": self.description,
            "version": self.version,
            "fields": [f.to_dict() for f in sorted(self.fields, key=lambda x: x.order)],
        }
        return json.dumps(schema, indent=indent, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "FormSchema":
        data = json.loads(json_str)
        schema = cls(
            form_id=data["form_id"],
            title=data["title"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
        )
        for fd in data.get("fields", []):
            validations = [
                ValidationRule(rule_type=v["rule"], value=v.get("value"),
                               error_message=v.get("message", ""))
                for v in fd.get("validations", [])
            ]
            conditions = [
                ConditionalLogic(
                    source_field_id=c["source"],
                    operator=ConditionOperator(c["operator"]),
                    compare_value=c.get("compare"),
                    action=c.get("action", "show"),
                )
                for c in fd.get("conditions", [])
            ]
            schema.add_field(FormField(
                field_id=fd["field_id"],
                label=fd["label"],
                field_type=FieldType(fd["type"]),
                placeholder=fd.get("placeholder", ""),
                default_value=fd.get("default_value"),
                options=fd.get("options", []),
                validations=validations,
                conditions=conditions,
                help_text=fd.get("help_text", ""),
                required=fd.get("required", False),
                order=fd.get("order", 0),
            ))
        return schema

    def validate_response(self, response: Dict[str, Any]) -> Dict[str, List[str]]:
        """Validate a form response dict against field rules. Returns {field_id: [errors]}."""
        errors: Dict[str, List[str]] = {}
        for f in self.fields:
            field_errors = []
            value = response.get(f.field_id)
            if f.required and (value is None or str(value).strip() == ""):
                field_errors.append(f"{f.label} is required.")
            for rule in f.validations:
                if value is None:
                    continue
                if rule.rule_type == "min_length" and len(str(value)) < int(rule.value or 0):
                    field_errors.append(rule.error_message or f"Minimum {rule.value} characters.")
                elif rule.rule_type == "max_length" and len(str(value)) > int(rule.value or 9999):
                    field_errors.append(rule.error_message or f"Maximum {rule.value} characters.")
                elif rule.rule_type == "min_value":
                    try:
                        if float(value) < float(rule.value):
                            field_errors.append(rule.error_message or f"Minimum value is {rule.value}.")
                    except (TypeError, ValueError):
                        pass
                elif rule.rule_type == "max_value":
                    try:
                        if float(value) > float(rule.value):
                            field_errors.append(rule.error_message or f"Maximum value is {rule.value}.")
                    except (TypeError, ValueError):
                        pass
                elif rule.rule_type == "regex" and rule.value:
                    if not re.match(str(rule.value), str(value)):
                        field_errors.append(rule.error_message or "Invalid format.")
            if field_errors:
                errors[f.field_id] = field_errors
        return errors


class LogisticsFormTemplates:
    """Pre-built logistics form schema templates."""

    @staticmethod
    def dock_inspection_form() -> FormSchema:
        schema = FormSchema("dock_inspection_v1", "Dock Inspection Form",
                            "Daily dock inspection checklist for yard operations")
        schema.add_field(FormField(
            field_id="dock_number",
            label="Dock Number",
            field_type=FieldType.TEXT,
            required=True,
            validations=[ValidationRule("required", error_message="Dock number is required.")]
        ))
        schema.add_field(FormField(
            field_id="inspection_date",
            label="Inspection Date",
            field_type=FieldType.DATE,
            required=True,
        ))
        schema.add_field(FormField(
            field_id="dock_status",
            label="Dock Status",
            field_type=FieldType.DROPDOWN,
            options=["clear", "occupied", "damaged", "under_maintenance"],
            required=True,
        ))
        schema.add_field(FormField(
            field_id="damage_photo",
            label="Damage Photo",
            field_type=FieldType.PHOTO,
            help_text="Upload if dock status is damaged.",
            conditions=[ConditionalLogic("dock_status", ConditionOperator.EQUALS,
                                          "damaged", "show")]
        ))
        schema.add_field(FormField(
            field_id="inspector_gps",
            label="Inspector Location",
            field_type=FieldType.GPS_LOCATION,
            required=True,
        ))
        schema.add_field(FormField(
            field_id="notes",
            label="Notes",
            field_type=FieldType.TEXT,
            placeholder="Additional observations...",
        ))
        return schema

    @staticmethod
    def trailer_intake_form() -> FormSchema:
        schema = FormSchema("trailer_intake_v1", "Trailer Intake Form",
                            "Capture trailer details at yard entry")
        schema.add_field(FormField(
            field_id="trailer_barcode",
            label="Trailer Barcode",
            field_type=FieldType.BARCODE,
            required=True,
        ))
        schema.add_field(FormField(
            field_id="carrier_name",
            label="Carrier Name",
            field_type=FieldType.TEXT,
            required=True,
        ))
        schema.add_field(FormField(
            field_id="cargo_type",
            label="Cargo Type",
            field_type=FieldType.DROPDOWN,
            options=["dry", "refrigerated", "hazmat", "oversized", "empty"],
            required=True,
        ))
        schema.add_field(FormField(
            field_id="weight_kg",
            label="Weight (kg)",
            field_type=FieldType.NUMBER,
            validations=[
                ValidationRule("min_value", 0, "Weight cannot be negative."),
                ValidationRule("max_value", 40000, "Weight exceeds truck limit."),
            ]
        ))
        schema.add_field(FormField(
            field_id="arrival_timestamp",
            label="Arrival Time",
            field_type=FieldType.DATETIME,
            required=True,
        ))
        schema.add_field(FormField(
            field_id="driver_signature",
            label="Driver Signature",
            field_type=FieldType.SIGNATURE,
            required=True,
        ))
        return schema


if __name__ == "__main__":
    dock_form = LogisticsFormTemplates.dock_inspection_form()
    print(f"Form: {dock_form.title}")
    print(f"Fields: {len(dock_form.fields)}")
    print(f"Required fields: {[f.field_id for f in dock_form.required_fields()]}")

    json_export = dock_form.to_json()
    print(f"\nJSON schema ({len(json_export)} chars):")
    print(json_export[:500] + "...")

    response = {
        "dock_number": "D-07",
        "inspection_date": "2024-04-15",
        "dock_status": "clear",
        "inspector_gps": {"lat": 28.6139, "lng": 77.2090},
    }
    errors = dock_form.validate_response(response)
    if errors:
        print("\nValidation errors:", errors)
    else:
        print("\nResponse is valid.")

    trailer_form = LogisticsFormTemplates.trailer_intake_form()
    print(f"\nTrailer form fields: {[f.field_id for f in trailer_form.fields]}")
