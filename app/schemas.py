from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=3, max_length=500)


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["pdf", "xlsx"]
    page: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    cell: str | None = Field(default=None, pattern=r"^[A-Z]{1,3}\d+(:[A-Z]{1,3}\d+)?$")
    excerpt: str | None = None

    @model_validator(mode="after")
    def _location_matches_type(self):
        if self.type == "pdf" and (self.page is None or self.sheet or self.cell):
            raise ValueError("a pdf source needs a page and no sheet/cell")
        if self.type == "xlsx" and (not self.sheet or not self.cell or self.page is not None):
            raise ValueError("an xlsx source needs a sheet and cell and no page")
        return self


class AskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str
    answer: str
    method: Literal["query", "retrieval"]
    sources: list[Source]
    value: float | None = Field(default=None, description="raw number for query answers")
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _query_has_cell(self):
        if self.method == "query" and (self.value is None or not any(s.type == "xlsx" for s in self.sources)):
            raise ValueError("query answers must carry a value and a workbook cell source")
        return self
