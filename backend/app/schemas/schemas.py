from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class MachineOut(BaseModel):
    id: str
    machine_number: str
    machine_name: str
    manufacturer: Optional[str] = None
    specification: Optional[str] = None
    location: Optional[str] = None
    remarks: Optional[str] = None
    critical: bool
    active: bool

    class Config:
        from_attributes = True


class PMPlanOut(BaseModel):
    id: str
    machine_id: str
    planned_date: Optional[date] = None
    planned_week: Optional[str] = None
    month: str
    financial_year: str
    status: str
    low_confidence_actual: bool

    class Config:
        from_attributes = True


class PMCompleteIn(BaseModel):
    actual_date: date
    completed_by: Optional[str] = None
    remarks: Optional[str] = None
    delay_reason: Optional[str] = None
    downtime_minutes: Optional[int] = None


class ImportPreviewIn(BaseModel):
    sheet_name: str
    financial_year: str


class ImportCommitIn(BaseModel):
    sheet_name: str
    financial_year: str
    file_path: str
    original_filename: str
