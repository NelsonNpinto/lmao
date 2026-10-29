"""Aligned dataset export for the desk's own spreadsheets."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, Query
from fastapi.responses import Response, StreamingResponse

from app.api.v1.convert import records
from app.api.v1.params import ScopeDep
from app.schemas.common import Envelope

router = APIRouter(tags=["export"])

EXPORT_COLS = [
    "start_time",
    "delivery_date",
    "period",
    "cutoff",
    "publish_time",
    "lead_time_h",
    "vintage_age_h",
    "stale",
    "forecast_mw",
    "actual_mw",
    "error_mw",
    "persistence_mw",
]
XLSX_MAX_ROWS = 50_000


def _filename(sc: ScopeDep, ext: str) -> str:
    w = sc.window
    return f"windsight_{w.day_from}_{w.day_to}_cutoff{sc.rule.local_time:%H%M}.{ext}"


@router.get(
    "/export",
    responses={
        200: {
            "content": {
                "text/csv": {},
                "application/json": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            }
        }
    },
)
async def export(
    sc: ScopeDep,
    format: Annotated[Literal["csv", "json", "xlsx"], Query()] = "csv",
) -> Response:
    """Aligned half-hourly dataset (UTC timestamps, raw unrounded MW)."""
    al = (await sc.analysis.aligned(sc.window, sc.rule))[EXPORT_COLS]
    m = await sc.analysis.summary(sc.window, sc.rule)

    if format == "json":
        env = Envelope[list[dict[str, object]]](
            data=records(al, EXPORT_COLS), meta=sc.meta(m.completeness)
        )
        return Response(env.model_dump_json(), media_type="application/json")

    disposition = {"Content-Disposition": f'attachment; filename="{_filename(sc, format)}"'}
    if format == "xlsx":
        notes = []
        if len(al) > XLSX_MAX_ROWS:
            notes.append(f"Truncated to {XLSX_MAX_ROWS:,} rows; use CSV for the full set.")
            al = al.head(XLSX_MAX_ROWS)
        xl = al.copy()
        for c in ("start_time", "cutoff", "publish_time"):
            xl[c] = xl[c].dt.tz_localize(None)  # Excel has no timezones; columns are UTC
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            xl.rename(
                columns={c: f"{c}_utc" for c in ("start_time", "cutoff", "publish_time")}
            ).to_excel(w, sheet_name="aligned", index=False)
            pd.DataFrame({"note": [sc.rule.label, *notes]}).to_excel(
                w, sheet_name="about", index=False
            )
        return Response(
            buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers=disposition,
        )

    if len(al) <= XLSX_MAX_ROWS:
        body = al.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
        return Response(body, media_type="text/csv", headers=disposition)

    def rows() -> Iterator[str]:  # large exports stream in chunks
        yield ",".join(EXPORT_COLS) + "\n"
        for start in range(0, len(al), 5_000):
            chunk = al.iloc[start : start + 5_000]
            yield chunk.to_csv(header=False, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")

    return StreamingResponse(rows(), media_type="text/csv", headers=disposition)
