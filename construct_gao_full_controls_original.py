#!/usr/bin/env python3
"""Construct Gao-style firm-year controls with low-memory, checkpointed parsing.

This program does not read or modify treatment, SYN, stack, or regression files.
It streams CSMAR XLSX XML into a local SQLite checkpoint database, constructs
unique firm-year variables, and writes data plus audit artifacts.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable
from xml.etree.ElementTree import iterparse
from zipfile import ZipFile

import numpy as np
import pandas as pd


RAW = Path("/Users/macpro/Desktop/控制变量")
PROJECT = Path("/Users/macpro/Desktop/毕业论文/堆叠DID重跑")
WORK = Path("/Users/macpro/Documents/New project/gao_full_controls_work")
OUT = WORK / "outputs"
DB = WORK / "gao_controls_staging.sqlite"
INDUSTRY_DTA = Path("/Users/macpro/Desktop/毕业论文/原始数据/行业分类_新下载.dta")
AR_INVENTORY = PROJECT / "年报指引识别/output/annual_report_inventory.csv"
MDA_STATUS = PROJECT / "output/mda_all_years_match_status.csv"
GAO_PDF = Path("/Users/macpro/Desktop/毕业论文/参考文献/Gao et al., 2024 - Disclosure Regulation and Price Informativeness.pdf")
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
YEARS = list(range(2009, 2026))
CODE_RE = re.compile(r"^\d{6}$")
YEAR_RE = re.compile(r"^(19\d{2}|20\d{2})")


SOURCES = {
    "balance": RAW / "资产合计负债合计所有者权益合计/FS_Combas.xlsx",
    "income": RAW / "营业利润净利润/FS_Comins.xlsx",
    "cfo": RAW / "经营活动产生的现金流量净额/FS_Comscfd.xlsx",
    "eps": RAW / "每股收益/FI_T9.xlsx",
    "loss": RAW / "归属于股东的扣非净利润/FI_T2.xlsx",
    "market": RAW / "总市值/TRD_Year.xlsx",
    "monthly": RAW / "月个股收益率/TRD_Mnth.xlsx",
    "inst": RAW / "机构投资者持股比例_两职合一_独立董事占比/BDT_ManaGovAbil.xlsx",
    "top": RAW / "第一大股东持股比例/EN_EquityNatureAll.xlsx",
    "analyst": RAW / "分析师数量/AF_CFEATUREPROFILE.xlsx",
    "subs1": RAW / "子公司/FN_Fn061.xlsx",
    "subs2": RAW / "子公司/FN_Fn0611.xlsx",
    "auditor": RAW / "审计机构/AR_LISTCOMPAUDIT.xlsx",
}


BIG4_RAW_NAMES = {
    "安永华明会计师事务所(特殊普通合伙)": "EY",
    "安永华明会计师事务所": "EY",
    "安永大华会计师事务所有限责任公司": "EY",
    "安永华明会计师事务所有限责任公司": "EY",
    "安永华明会计师事务所上海分所": "EY",
    "普华永道中天会计师事务所(特殊普通合伙)": "PwC",
    "普华永道中天会计师事务所有限公司": "PwC",
    "普华永道中天会计师事务所": "PwC",
    "毕马威华振会计师事务所(特殊普通合伙)": "KPMG",
    "毕马威华振会计师事务所": "KPMG",
    "德勤华永会计师事务所(特殊普通合伙)": "Deloitte",
    "德勤华永会计师事务所有限公司": "Deloitte",
    "德勤华永会计师事务所有限公司深圳分所": "Deloitte",
    "德勤华永会计师事务所": "Deloitte",
}


def log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    with (WORK / "construction.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def norm_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", "", text)


def stock_code(value: object) -> str:
    text = str(value or "").strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if text.isdigit() and len(text) <= 6:
        text = text.zfill(6)
    return text if CODE_RE.fullmatch(text) else ""


def get_year(value: object) -> int | None:
    match = YEAR_RE.match(str(value or "").strip())
    return int(match.group(1)) if match else None


def is_year_end(value: object) -> bool:
    text = str(value or "").strip()
    return bool(re.match(r"^\d{4}-?12-?31", text))


def to_float(value: object) -> float | None:
    text = str(value or "").strip()
    if text == "":
        return None
    try:
        number = float(text)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def code_is(value: object, target: str) -> bool:
    text = str(value or "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text == target


def cell_text(cell, shared_strings: list[str]) -> str:
    kind = cell.attrib.get("t", "")
    if kind == "inlineStr":
        inline = cell.find(NS + "is")
        return "" if inline is None else "".join(node.text or "" for node in inline.iter(NS + "t"))
    value = cell.find(NS + "v")
    if value is None or value.text is None:
        return ""
    if kind == "s":
        try:
            return shared_strings[int(value.text)]
        except (ValueError, IndexError):
            return value.text
    return value.text


def load_shared_strings(book: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    output: list[str] = []
    with book.open("xl/sharedStrings.xml") as stream:
        for _, elem in iterparse(stream, events=("end",)):
            if elem.tag == NS + "si":
                output.append("".join(node.text or "" for node in elem.iter(NS + "t")))
                elem.clear()
    return output


def iter_xlsx_records(path: Path) -> Iterable[tuple[int, dict[str, str]]]:
    """Yield data rows keyed by row-1 field codes; ignore broken dimensions."""
    with ZipFile(path) as book:
        shared = load_shared_strings(book)
        sheets = sorted(name for name in book.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
        if not sheets:
            return
        # All CSMAR inputs in scope contain one actual data sheet.
        with book.open(sheets[0]) as stream:
            headers: dict[str, str] = {}
            for _, elem in iterparse(stream, events=("end",)):
                if elem.tag != NS + "row":
                    continue
                row_number = int(elem.attrib.get("r", "0"))
                values: dict[str, str] = {}
                for cell in elem.findall(NS + "c"):
                    ref = cell.attrib.get("r", "")
                    col_match = re.match(r"[A-Z]+", ref)
                    if col_match:
                        values[col_match.group()] = cell_text(cell, shared)
                if row_number == 1:
                    headers = {col: value.strip() for col, value in values.items() if value.strip()}
                elif row_number >= 4 and headers and values:
                    yield row_number, {headers[col]: values.get(col, "") for col in headers}
                elem.clear()


def signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def init_db() -> sqlite3.Connection:
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=FILE")
    conn.execute("PRAGMA cache_size=-64000")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_done(
          source_id TEXT PRIMARY KEY, path TEXT, signature TEXT, rows_seen INTEGER,
          rows_kept INTEGER, completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS num_values(
          variable TEXT, firm_id TEXT, year INTEGER, value REAL, conflict INTEGER DEFAULT 0,
          rows_seen INTEGER DEFAULT 1, source_id TEXT,
          PRIMARY KEY(variable,firm_id,year)
        );
        CREATE TABLE IF NOT EXISTS monthly_year(
          firm_id TEXT, year INTEGER, n INTEGER, sum_x REAL, sum_x2 REAL,
          PRIMARY KEY(firm_id,year)
        );
        CREATE TABLE IF NOT EXISTS subsidiaries(
          firm_id TEXT, year INTEGER, normalized_name TEXT, raw_name TEXT,
          PRIMARY KEY(firm_id,year,normalized_name)
        );
        CREATE TABLE IF NOT EXISTS auditors(
          firm_id TEXT, year INTEGER, normalized_name TEXT, raw_name TEXT,
          big4_group TEXT,
          PRIMARY KEY(firm_id,year,normalized_name)
        );
        CREATE TABLE IF NOT EXISTS industry(
          firm_id TEXT, year INTEGER, standard_id TEXT, standard_name TEXT,
          industry_code TEXT, industry_name TEXT, conflict INTEGER DEFAULT 0,
          PRIMARY KEY(firm_id,year)
        );
        CREATE TABLE IF NOT EXISTS audit_metrics(key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX IF NOT EXISTS idx_num_variable ON num_values(variable,year);
        CREATE INDEX IF NOT EXISTS idx_sub_year ON subsidiaries(year,firm_id);
        CREATE INDEX IF NOT EXISTS idx_aud_year ON auditors(year,firm_id);
        CREATE INDEX IF NOT EXISTS idx_ind_year ON industry(year,industry_code);
        """
    )
    conn.commit()
    return conn


def already_done(conn: sqlite3.Connection, source_id: str, path: Path) -> bool:
    row = conn.execute("SELECT signature FROM source_done WHERE source_id=?", (source_id,)).fetchone()
    if not row:
        return False
    if row[0] != signature(path):
        raise RuntimeError(f"Checkpoint source changed: {source_id}. Delete {DB} before a clean rebuild.")
    log(f"Checkpoint hit, skip {source_id}: {path.name}")
    return True


def mark_done(conn: sqlite3.Connection, source_id: str, path: Path, rows_seen: int, rows_kept: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO source_done VALUES(?,?,?,?,?,?)",
        (source_id, str(path), signature(path), rows_seen, rows_kept, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()


NUM_UPSERT = """
INSERT INTO num_values(variable,firm_id,year,value,conflict,rows_seen,source_id)
VALUES(?,?,?,?,0,1,?)
ON CONFLICT(variable,firm_id,year) DO UPDATE SET
  conflict=CASE WHEN abs(num_values.value-excluded.value)>max(1e-9,1e-10*max(abs(num_values.value),abs(excluded.value))) THEN 1 ELSE num_values.conflict END,
  rows_seen=num_values.rows_seen+1
"""


def put_num(conn: sqlite3.Connection, variable: str, firm: str, year: int, value: float | None, source_id: str) -> bool:
    if value is None:
        return False
    conn.execute(NUM_UPSERT, (variable, firm, year, float(value), source_id))
    return True


def parse_xlsx_source(conn: sqlite3.Connection, source_id: str, path: Path) -> None:
    if already_done(conn, source_id, path):
        return
    log(f"Stream parse {source_id}: {path}")
    seen = kept = 0
    conn.execute("BEGIN")
    for rownum, r in iter_xlsx_records(path):
        seen += 1
        firm = stock_code(r.get("Stkcd", r.get("Symbol", "")))
        if not firm:
            continue
        n_before = kept
        if source_id == "balance":
            y = get_year(r.get("Accper"))
            if y in range(2007, 2026) and is_year_end(r.get("Accper")) and r.get("Typrep", "").strip() == "A":
                kept += put_num(conn, "total_assets", firm, y, to_float(r.get("A001000000")), source_id)
                kept += put_num(conn, "total_liabilities", firm, y, to_float(r.get("A002000000")), source_id)
                kept += put_num(conn, "equity_parent", firm, y, to_float(r.get("A003100000")), source_id)
                kept += put_num(conn, "equity_total", firm, y, to_float(r.get("A003000000")), source_id)
        elif source_id == "income":
            y = get_year(r.get("Accper"))
            if y in range(2007, 2026) and is_year_end(r.get("Accper")) and r.get("Typrep", "").strip() == "A":
                kept += put_num(conn, "operating_income", firm, y, to_float(r.get("B001300000")), source_id)
                kept += put_num(conn, "net_profit", firm, y, to_float(r.get("B002000000")), source_id)
        elif source_id == "cfo":
            y = get_year(r.get("Accper"))
            if y in range(2008, 2026) and is_year_end(r.get("Accper")) and r.get("Typrep", "").strip() == "A":
                kept += put_num(conn, "operating_cash_flow", firm, y, to_float(r.get("C001000000")), source_id)
        elif source_id == "eps":
            y = get_year(r.get("Accper"))
            if y in range(2008, 2026) and is_year_end(r.get("Accper")) and r.get("Typrep", "").strip() == "A" and code_is(r.get("Source"), "0"):
                kept += put_num(conn, "eps", firm, y, to_float(r.get("F090101B")), source_id)
        elif source_id == "loss":
            y = get_year(r.get("Accper"))
            if y in YEARS and is_year_end(r.get("Accper")):
                kept += put_num(conn, "adjusted_net_profit", firm, y, to_float(r.get("F020102")), source_id)
        elif source_id == "market":
            y = get_year(r.get("Trdynt"))
            if y in YEARS:
                raw = to_float(r.get("Ysmvttl"))
                kept += put_num(conn, "market_value_thousand", firm, y, raw, source_id)
        elif source_id == "inst":
            y = get_year(r.get("Enddate"))
            if y in range(2008, 2026) and is_year_end(r.get("Enddate")):
                kept += put_num(conn, "institutional_hold_percent", firm, y, to_float(r.get("InsInvestorProp")), source_id)
        elif source_id == "top":
            y = get_year(r.get("EndDate"))
            if y in YEARS and is_year_end(r.get("EndDate")):
                kept += put_num(conn, "top1_percent", firm, y, to_float(r.get("LargestHolderRate")), source_id)
        elif source_id == "analyst":
            y = get_year(r.get("Accper"))
            if y in YEARS:
                kept += put_num(conn, "analyst_count", firm, y, to_float(r.get("AnaAttention")), source_id)
        elif source_id == "monthly":
            ym = str(r.get("Trdmnt", "")).strip()
            y = get_year(ym)
            value = to_float(r.get("Mretwd"))
            if y in range(2007, 2026) and re.match(r"^\d{4}-?\d{2}$", ym) and value is not None:
                conn.execute(
                    """INSERT INTO monthly_year VALUES(?,?,?,?,?)
                    ON CONFLICT(firm_id,year) DO UPDATE SET
                    n=monthly_year.n+1,sum_x=monthly_year.sum_x+excluded.sum_x,
                    sum_x2=monthly_year.sum_x2+excluded.sum_x2""",
                    (firm, y, 1, value, value * value),
                )
                kept += 1
        elif source_id.startswith("subs"):
            y = get_year(r.get("EndDate"))
            raw_name = str(r.get("FN_Fn06101", "")).strip()
            normalized = norm_text(raw_name).casefold()
            if y in YEARS and is_year_end(r.get("EndDate")) and normalized:
                conn.execute("INSERT OR IGNORE INTO subsidiaries VALUES(?,?,?,?)", (firm, y, normalized, raw_name))
                kept += conn.execute("SELECT changes()").fetchone()[0]
        elif source_id == "auditor":
            y = get_year(r.get("EndDate"))
            raw_name = str(r.get("AccountingFirmName", "")).strip()
            normalized = norm_text(raw_name)
            # Source=0 periodic report; TerritoryForeignIdentity=1 domestic auditor.
            if y in YEARS and is_year_end(r.get("EndDate")) and code_is(r.get("Source"), "0") and code_is(r.get("TerritoryForeignIdentity"), "1") and normalized:
                group = BIG4_RAW_NAMES.get(normalized, "")
                conn.execute("INSERT OR IGNORE INTO auditors VALUES(?,?,?,?,?)", (firm, y, normalized, raw_name, group))
                kept += conn.execute("SELECT changes()").fetchone()[0]
        if seen % 100000 == 0:
            conn.commit()
            conn.execute("BEGIN")
            log(f"  {source_id}: rows={seen:,}, kept values/records={kept:,}")
    conn.commit()
    mark_done(conn, source_id, path, seen, kept)
    log(f"Done {source_id}: rows={seen:,}, kept values/records={kept:,}")


def parse_industry(conn: sqlite3.Connection) -> None:
    source_id = "industry_dta"
    path = INDUSTRY_DTA
    if already_done(conn, source_id, path):
        return
    log(f"Chunk-read industry: {path}")
    seen = kept = 0
    reader = pd.read_stata(path, iterator=True, convert_categoricals=False)
    while True:
        try:
            chunk = reader.read(100000)
        except StopIteration:
            break
        if chunk.empty:
            break
        seen += len(chunk)
        chunk["year"] = pd.to_numeric(chunk["EndDate"].astype(str).str.slice(0, 4), errors="coerce")
        chunk = chunk[chunk["year"].isin(YEARS)].copy()
        chunk["wanted"] = np.select(
            [chunk["year"].between(2009, 2011), chunk["year"].between(2012, 2022), chunk["year"].between(2023, 2025)],
            ["P0201", "P0207", "P0221"], default=""
        )
        chunk = chunk[chunk["IndustryClassificationID"].astype(str) == chunk["wanted"]]
        conn.execute("BEGIN")
        for row in chunk.itertuples(index=False):
            firm = stock_code(getattr(row, "Symbol"))
            if not firm:
                continue
            y = int(getattr(row, "year"))
            std = str(getattr(row, "IndustryClassificationID") or "")
            stdname = str(getattr(row, "IndustryClassification") or "")
            indcode = str(getattr(row, "IndustryCode2") or "").strip()
            indname = str(getattr(row, "IndustryName2") or "").strip()
            if not indcode:
                continue
            conn.execute(
                """INSERT INTO industry VALUES(?,?,?,?,?,?,0)
                ON CONFLICT(firm_id,year) DO UPDATE SET
                conflict=CASE WHEN industry.standard_id<>excluded.standard_id OR industry.industry_code<>excluded.industry_code THEN 1 ELSE industry.conflict END""",
                (firm, y, std, stdname, indcode, indname),
            )
            kept += 1
        conn.commit()
        log(f"  industry: rows={seen:,}, selected={kept:,}")
        if len(chunk) < 100000 and seen > 0:
            # Reader may still have data even if a filtered chunk is short; no break.
            pass
    mark_done(conn, source_id, path, seen, kept)
    log(f"Done industry: rows={seen:,}, selected={kept:,}")


def parse_ar_inventory(conn: sqlite3.Connection) -> None:
    source_id = "annual_report_inventory"
    path = AR_INVENTORY
    if already_done(conn, source_id, path):
        return
    log(f"Chunk-read existing annual report inventory (no report rescan): {path}")
    seen = kept = 0
    for chunk in pd.read_csv(path, chunksize=50000, low_memory=False):
        seen += len(chunk)
        for row in chunk.itertuples(index=False):
            y = int(row.report_year) if pd.notna(row.report_year) else None
            firm = stock_code(row.stock_code)
            preferred = int(row.preferred_version) == 1 if pd.notna(row.preferred_version) else False
            full = int(row.is_full_annual_report) == 1 if pd.notna(row.is_full_annual_report) else False
            length = to_float(row.text_length)
            if y in YEARS and firm and preferred and full and length is not None:
                kept += put_num(conn, "length_ar_chars", firm, y, length, source_id)
        conn.commit()
        log(f"  annual inventory: rows={seen:,}, kept={kept:,}")
    mark_done(conn, source_id, path, seen, kept)


def audit_stock_code_changes() -> dict[str, object]:
    """Use stable CSMAR InstitutionID to flag entities observed under >1 stock code."""
    mapping: dict[str, set[str]] = {}
    reader = pd.read_stata(INDUSTRY_DTA, iterator=True, convert_categoricals=False)
    while True:
        try:
            chunk = reader.read(100000)
        except StopIteration:
            break
        if chunk.empty:
            break
        years = pd.to_numeric(chunk["EndDate"].astype(str).str.slice(0, 4), errors="coerce")
        wanted = np.select(
            [years.between(2009, 2011), years.between(2012, 2022), years.between(2023, 2025)],
            ["P0201", "P0207", "P0221"], default=""
        )
        chunk = chunk[(years.isin(YEARS)) & (chunk["IndustryClassificationID"].astype(str) == wanted)]
        for inst, symbol in zip(chunk["InstitutionID"], chunk["Symbol"]):
            firm = stock_code(symbol)
            if firm and pd.notna(inst):
                mapping.setdefault(str(inst), set()).add(firm)
    changed = {inst: sorted(codes) for inst, codes in mapping.items() if len(codes) > 1}
    return {
        "institution_ids_with_multiple_stock_codes": len(changed),
        "stock_code_change_examples": dict(list(sorted(changed.items()))[:20]),
    }


def load_num(conn: sqlite3.Connection, variable: str, out_name: str | None = None) -> pd.DataFrame:
    frame = pd.read_sql_query(
        "SELECT firm_id,year,value,conflict,rows_seen FROM num_values WHERE variable=?",
        conn, params=(variable,)
    )
    name = out_name or variable
    if frame.empty:
        return pd.DataFrame(columns=["firm_id", "year", name])
    frame.loc[frame["conflict"] == 1, "value"] = np.nan
    return frame[["firm_id", "year", "value"]].rename(columns={"value": name})


def merge_num(base: pd.DataFrame, conn: sqlite3.Connection, variable: str, out_name: str | None = None) -> pd.DataFrame:
    return base.merge(load_num(conn, variable, out_name), on=["firm_id", "year"], how="left", validate="one_to_one")


def exact_lag(frame: pd.DataFrame, column: str, lag: int = 1) -> pd.Series:
    lookup = frame.set_index(["firm_id", "year"])[column]
    keys = pd.MultiIndex.from_arrays([frame["firm_id"], frame["year"] - lag])
    return pd.Series(lookup.reindex(keys).to_numpy(), index=frame.index)


def add_stdroa(frame: pd.DataFrame) -> None:
    r0 = frame["ROA"]
    r1 = exact_lag(frame, "ROA", 1)
    r2 = exact_lag(frame, "ROA", 2)
    values = np.column_stack([r2, r1, r0])
    good = np.isfinite(values).all(axis=1)
    frame["Stdroa"] = np.nan
    frame.loc[good, "Stdroa"] = np.std(values[good], axis=1, ddof=1)
    frame["Stdroa_years"] = np.where(good, 3, np.sum(np.isfinite(values), axis=1)).astype(np.int16)


def add_stdret(frame: pd.DataFrame, conn: sqlite3.Connection) -> None:
    annual = pd.read_sql_query("SELECT firm_id,year,n,sum_x,sum_x2 FROM monthly_year", conn)
    comp = {(r.firm_id, int(r.year)): (int(r.n), float(r.sum_x), float(r.sum_x2)) for r in annual.itertuples(index=False)}
    values: list[float] = []
    counts: list[int] = []
    years_present: list[int] = []
    for firm, y in zip(frame["firm_id"], frame["year"]):
        parts = [comp.get((firm, int(y) - k)) for k in (2, 1, 0)]
        years_present.append(sum(p is not None for p in parts))
        if any(p is None for p in parts):
            counts.append(sum(p[0] for p in parts if p is not None))
            values.append(np.nan)
            continue
        n = sum(p[0] for p in parts)
        sx = sum(p[1] for p in parts)
        sx2 = sum(p[2] for p in parts)
        counts.append(n)
        if n < 24:
            values.append(np.nan)
            continue
        variance = max(0.0, (sx2 - sx * sx / n) / (n - 1))
        values.append(math.sqrt(variance))
    frame["Stdret"] = values
    frame["Stdret_months"] = np.array(counts, dtype=np.int16)
    frame["Stdret_years"] = np.array(years_present, dtype=np.int8)


def qstats(series: pd.Series) -> tuple[float, float]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return np.nan, np.nan
    return float(clean.quantile(0.01)), float(clean.quantile(0.99))


def winsorize(frame: pd.DataFrame, columns: list[str]) -> dict[str, dict[str, float]]:
    audit: dict[str, dict[str, float]] = {}
    for col in columns:
        if col not in frame:
            continue
        lo, hi = qstats(frame[col])
        target = col + "_w"
        frame[target] = frame[col].clip(lower=lo, upper=hi)
        changed = int(((frame[target] != frame[col]) & frame[col].notna()).sum())
        audit[col] = {"p1": lo, "p99": hi, "winsorized_count": changed}
    return audit


def construct(conn: sqlite3.Connection) -> tuple[pd.DataFrame, dict[str, dict[str, float]], dict[str, object]]:
    universe = pd.read_sql_query(
        """SELECT firm_id,year,value AS total_assets FROM num_values
        WHERE variable='total_assets' AND conflict=0 AND year BETWEEN 2009 AND 2025""", conn
    )
    universe = universe.drop_duplicates(["firm_id", "year"]).sort_values(["firm_id", "year"]).reset_index(drop=True)
    frame = universe
    for variable in [
        "total_liabilities", "equity_parent", "equity_total", "operating_income",
        "net_profit", "operating_cash_flow", "eps", "adjusted_net_profit",
        "market_value_thousand", "institutional_hold_percent", "top1_percent",
        "analyst_count", "length_ar_chars",
    ]:
        frame = merge_num(frame, conn, variable)

    metrics: dict[str, object] = {}
    metrics["universe_rows"] = len(frame)
    metrics["universe_firms"] = frame["firm_id"].nunique()
    metrics["nonpositive_assets"] = int((frame["total_assets"] <= 0).sum())
    metrics["nonpositive_parent_equity"] = int((frame["equity_parent"] <= 0).sum())
    metrics["nonpositive_total_equity"] = int((frame["equity_total"] <= 0).sum())
    metrics["inst_outside_0_100"] = int(((frame["institutional_hold_percent"] < 0) | (frame["institutional_hold_percent"] > 100)).sum())
    metrics["top1_outside_0_100"] = int(((frame["top1_percent"] < 0) | (frame["top1_percent"] > 100)).sum())
    metrics["analyst_negative"] = int((frame["analyst_count"] < 0).sum())
    metrics["market_value_nonpositive"] = int((frame["market_value_thousand"] <= 0).sum())
    metrics["liabilities_negative"] = int((frame["total_liabilities"] < 0).sum())

    frame["Size"] = np.where(frame["total_assets"] > 0, np.log(frame["total_assets"]), np.nan)
    frame["market_value"] = frame["market_value_thousand"] * 1000.0
    frame["MB_parent"] = np.where(frame["equity_parent"] > 0, frame["market_value"] / frame["equity_parent"], np.nan)
    frame["MB_total_equity"] = np.where(frame["equity_total"] > 0, frame["market_value"] / frame["equity_total"], np.nan)
    frame["MB"] = frame["MB_parent"]
    frame["Lev"] = np.where(frame["total_assets"] > 0, frame["total_liabilities"] / frame["total_assets"], np.nan)
    frame["ROA"] = np.where(frame["total_assets"] > 0, frame["operating_income"] / frame["total_assets"], np.nan)
    add_stdroa(frame)
    eps_lag = exact_lag(frame, "eps", 1)
    frame["eps_lag"] = eps_lag
    frame["abs_dEPS"] = np.where(frame["eps"].notna() & eps_lag.notna(), (frame["eps"] - eps_lag).abs(), np.nan)
    assets_lag = exact_lag(frame, "total_assets", 1)
    frame["total_assets_lag"] = assets_lag
    frame["abs_Accruals"] = np.where(
        frame["operating_income"].notna() & frame["operating_cash_flow"].notna() & (assets_lag > 0),
        (frame["operating_income"] - frame["operating_cash_flow"]).abs() / assets_lag,
        np.nan,
    )
    frame["Loss"] = np.where(frame["adjusted_net_profit"].notna(), (frame["adjusted_net_profit"] < 0).astype(float), np.nan)
    add_stdret(frame, conn)
    frame["Instihold"] = np.where(frame["institutional_hold_percent"].between(0, 100), frame["institutional_hold_percent"] / 100.0, np.nan)
    inst_lag = exact_lag(frame, "Instihold", 1)
    frame["Instihold_lag"] = inst_lag
    frame["d_Instihold"] = np.where(frame["Instihold"].notna() & inst_lag.notna(), frame["Instihold"] - inst_lag, np.nan)
    frame["Analyst"] = np.where(frame["analyst_count"] >= 0, np.log1p(frame["analyst_count"]), np.nan)
    frame["Tophold"] = np.where(frame["top1_percent"].between(0, 100), frame["top1_percent"] / 100.0, np.nan)
    frame["Tophold2"] = frame["Tophold"] ** 2

    metrics["lev_negative"] = int((frame["Lev"] < 0).sum())
    metrics["lev_above_one"] = int((frame["Lev"] > 1).sum())
    metrics["lev_above_ten"] = int((frame["Lev"] > 10).sum())
    metrics["roa_abs_above_one"] = int((frame["ROA"].abs() > 1).sum())
    metrics["eps_abs_above_100"] = int((frame["eps"].abs() > 100).sum())
    metrics["abs_deps_above_100"] = int((frame["abs_dEPS"] > 100).sum())
    metrics["accruals_above_one"] = int((frame["abs_Accruals"] > 1).sum())

    subs = pd.read_sql_query("SELECT firm_id,year,count(*) AS subs_count FROM subsidiaries GROUP BY firm_id,year", conn)
    frame = frame.merge(subs, on=["firm_id", "year"], how="left", validate="one_to_one")
    # No record is not assumed to mean zero subsidiaries.
    frame["Subs"] = np.where(frame["subs_count"].notna(), np.log1p(frame["subs_count"]), np.nan)

    aud = pd.read_sql_query(
        """SELECT firm_id,year,count(*) AS auditor_name_count,
        max(CASE WHEN big4_group<>'' THEN 1 ELSE 0 END) AS Big4,
        group_concat(DISTINCT raw_name) AS auditor_names,
        group_concat(DISTINCT CASE WHEN big4_group<>'' THEN big4_group END) AS big4_groups
        FROM auditors GROUP BY firm_id,year""", conn
    )
    frame = frame.merge(aud, on=["firm_id", "year"], how="left", validate="one_to_one")

    ind = pd.read_sql_query(
        """SELECT firm_id,year,standard_id AS industry_standard_id,
        standard_name AS industry_standard_name,industry_code,industry_name
        FROM industry WHERE conflict=0""", conn
    )
    if not ind.empty:
        ind["industry_firm_count"] = ind.groupby(["year", "industry_standard_id", "industry_code"])["firm_id"].transform("nunique")
        ind["Indsize_candidate"] = np.log(ind["industry_firm_count"])
    frame = frame.merge(ind, on=["firm_id", "year"], how="left", validate="one_to_one")
    frame = frame.rename(columns={"length_ar_chars": "Length_AR_chars"})

    continuous = [
        "Size", "MB", "MB_parent", "MB_total_equity", "Lev", "ROA", "Stdroa",
        "abs_dEPS", "abs_Accruals", "Stdret", "Instihold", "d_Instihold",
        "Analyst", "Tophold", "Tophold2", "Subs", "Indsize_candidate", "Length_AR_chars",
    ]
    win = winsorize(frame, continuous)
    frame["year"] = frame["year"].astype(np.int16)
    frame = frame.sort_values(["firm_id", "year"]).reset_index(drop=True)
    metrics["duplicate_firm_year_final"] = int(frame.duplicated(["firm_id", "year"]).sum())
    metrics["subs_records"] = int(conn.execute("SELECT count(*) FROM subsidiaries").fetchone()[0])
    metrics["auditor_records"] = int(conn.execute("SELECT count(*) FROM auditors").fetchone()[0])
    metrics["industry_conflicts"] = int(conn.execute("SELECT count(*) FROM industry WHERE conflict=1").fetchone()[0])
    metrics["numeric_conflict_keys"] = int(conn.execute("SELECT count(*) FROM num_values WHERE conflict=1").fetchone()[0])
    return frame, win, metrics


CORE_VARIABLES = [
    "Size", "MB", "MB_parent", "MB_total_equity", "Lev", "ROA", "Stdroa",
    "abs_dEPS", "abs_Accruals", "Loss", "Stdret", "Instihold", "d_Instihold",
    "Analyst", "Tophold", "Tophold2", "Subs", "Big4", "Indsize_candidate", "Length_AR_chars",
]


FORMULAS = {
    "Size": ("ln(资产总计)", "FS_Combas:A001000000", "合并报表A；12月31日；资产>0", "元取自然对数"),
    "MB": ("年末总市值/归属于母公司所有者权益；主口径", "TRD_Year:Ysmvttl; FS_Combas:A003100000", "市值千元×1000；权益>0", "倍"),
    "MB_parent": ("年末总市值/归属于母公司所有者权益", "TRD_Year:Ysmvttl; FS_Combas:A003100000", "市值千元×1000；权益>0", "倍"),
    "MB_total_equity": ("年末总市值/所有者权益合计；备选口径", "TRD_Year:Ysmvttl; FS_Combas:A003000000", "市值千元×1000；权益>0", "倍"),
    "Lev": ("负债合计/资产总计", "FS_Combas:A002000000/A001000000", "合并报表A；12月31日；资产>0", "比例0-1通常范围"),
    "ROA": ("营业利润/资产总计", "FS_Comins:B001300000; FS_Combas:A001000000", "合并报表A；12月31日；资产>0", "比例"),
    "Stdroa": ("样本标准差(ROA[t-2],ROA[t-1],ROA[t])", "由ROA机械计算", "连续3年全部存在；ddof=1", "比例的标准差"),
    "abs_dEPS": ("abs(EPS[t]-EPS[t-1])", "FI_T9:F090101B", "合并报表A；Source=0；连续年度", "元/股的绝对变化"),
    "abs_Accruals": ("abs(营业利润-经营活动现金流量净额)/上一年资产", "B001300000; C001000000; lag A001000000", "本年流量完整；严格上一年资产>0", "比例"),
    "Loss": ("1[归属于上市公司股东的扣非净利润<0]", "FI_T2:F020102", "12月31日；不插补", "0/1"),
    "Stdret": ("过去3个日历年(t-2至t)月收益率样本标准差", "TRD_Mnth:Mretwd", "三个年度均出现；至少24个有效月份；ddof=1", "月收益率标准差"),
    "Instihold": ("机构投资者持股比例/100", "BDT_ManaGovAbil:InsInvestorProp", "12月31日；原值0-100", "比例0-1"),
    "d_Instihold": ("Instihold[t]-Instihold[t-1]", "由Instihold机械计算", "严格连续年度", "比例变化"),
    "Analyst": ("ln(1+分析师关注数量)", "AF_CFEATUREPROFILE:AnaAttention", "CSMAR直接数量；分析师团队按1名计", "自然对数"),
    "Tophold": ("第一大股东持股比例/100", "EN_EquityNatureAll:LargestHolderRate", "12月31日；原值0-100", "比例0-1"),
    "Tophold2": ("Tophold平方", "由Tophold机械计算", "Tophold非缺失", "比例平方"),
    "Subs": ("ln(1+同年披露子公司名称去重数)", "FN_Fn061:FN_Fn06101", "12月31日；NFKC/空白标准化去重；无合并范围标志", "自然对数"),
    "Big4": ("境内年报审计事务所是否属于审定四大会计师事务所名称", "AR_LISTCOMPAUDIT:AccountingFirmName", "Source=0；TerritoryForeignIdentity=1；精确名称表", "0/1"),
    "Indsize_candidate": ("ln(同年同二级行业公司数)", "行业分类_新下载:IndustryCode2", "2009-11 P0201；2012-22 P0207；2023-25 P0221", "自然对数；候选口径"),
    "Length_AR_chars": ("现有完整年报首选版本文本字符数", "annual_report_inventory:text_length", "preferred_version=1；full annual report=1；不重扫年报", "字符数"),
    "Length_MDA": ("待构造：管理层讨论与分析文本长度", "现有MDA匹配仅候选公司/年份", "未进行全样本年报重扫", "不可用"),
}


FORMULA_SOURCE_FILES = {
    "Size": str(SOURCES["balance"]),
    "MB": f"{SOURCES['market']}; {SOURCES['balance']}",
    "MB_parent": f"{SOURCES['market']}; {SOURCES['balance']}",
    "MB_total_equity": f"{SOURCES['market']}; {SOURCES['balance']}",
    "Lev": str(SOURCES["balance"]),
    "ROA": f"{SOURCES['income']}; {SOURCES['balance']}",
    "Stdroa": f"{SOURCES['income']}; {SOURCES['balance']}",
    "abs_dEPS": str(SOURCES["eps"]),
    "abs_Accruals": f"{SOURCES['income']}; {SOURCES['cfo']}; {SOURCES['balance']}",
    "Loss": str(SOURCES["loss"]),
    "Stdret": str(SOURCES["monthly"]),
    "Instihold": str(SOURCES["inst"]),
    "d_Instihold": str(SOURCES["inst"]),
    "Analyst": str(SOURCES["analyst"]),
    "Tophold": str(SOURCES["top"]),
    "Tophold2": str(SOURCES["top"]),
    "Subs": f"{SOURCES['subs1']}; {SOURCES['subs2']}",
    "Big4": str(SOURCES["auditor"]),
    "Indsize_candidate": str(INDUSTRY_DTA),
    "Length_AR_chars": str(AR_INVENTORY),
    "Length_MDA": str(MDA_STATUS),
}


def coverage_table(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    variables = CORE_VARIABLES + [c + "_w" for c in CORE_VARIABLES if c not in {"Loss", "Big4"} and c + "_w" in frame]
    for y in YEARS:
        subset = frame[frame["year"] == y]
        denom = subset["firm_id"].nunique()
        for var in variables:
            available = subset.loc[subset[var].notna(), "firm_id"].nunique() if var in subset else 0
            rows.append({"year": y, "variable": var, "firms_available": available, "total_firms": denom, "coverage_rate": available / denom if denom else np.nan})
    return pd.DataFrame(rows)


def formula_audit(frame: pd.DataFrame, win: dict[str, dict[str, float]]) -> pd.DataFrame:
    rows = []
    for var, (definition, source, filt, unit) in FORMULAS.items():
        exists = var in frame
        years = sorted(frame.loc[frame[var].notna(), "year"].unique()) if exists else []
        q = win.get(var, {})
        rows.append({
            "Gao_variable": var,
            "constructed": int(exists and frame[var].notna().any()),
            "definition": definition,
            "source_file": FORMULA_SOURCE_FILES[var],
            "source_fields": source,
            "filters_and_window": filt,
            "unit": unit,
            "nonmissing_firm_years": int(frame[var].notna().sum()) if exists else 0,
            "first_year": min(years) if years else np.nan,
            "last_year": max(years) if years else np.nan,
            "coverage_2009_2022": float(frame.loc[frame["year"].between(2009, 2022), var].notna().mean()) if exists else 0.0,
            "coverage_2009_2025": float(frame[var].notna().mean()) if exists else 0.0,
            "p1_winsor_cut": q.get("p1", np.nan),
            "p99_winsor_cut": q.get("p99", np.nan),
            "winsorized_observations": int(q.get("winsorized_count", 0)),
            "raw_retained": int(exists),
            "winsorized_copy_retained": int(var + "_w" in frame),
        })
    return pd.DataFrame(rows)


def close(a: object, b: object, tol: float = 1e-10) -> bool:
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False
    return bool(np.isclose(float(a), float(b), rtol=tol, atol=tol, equal_nan=True))


def make_spotcheck(frame: pd.DataFrame) -> pd.DataFrame:
    score_vars = ["Size", "MB", "Lev", "ROA", "Stdroa", "abs_dEPS", "abs_Accruals", "Loss", "Stdret", "Instihold", "Analyst", "Tophold", "Subs", "Big4"]
    eligible = frame.copy()
    eligible["_score"] = eligible[score_vars].notna().sum(axis=1)
    pool = eligible[eligible["_score"] >= eligible["_score"].quantile(0.75)]
    sample = pool.sample(n=min(20, len(pool)), random_state=20240815).copy().sort_values(["firm_id", "year"])
    rows = []
    for r in sample.itertuples(index=False):
        expected_size = math.log(r.total_assets) if pd.notna(r.total_assets) and r.total_assets > 0 else np.nan
        expected_mb = r.market_value_thousand * 1000 / r.equity_parent if pd.notna(r.market_value_thousand) and pd.notna(r.equity_parent) and r.equity_parent > 0 else np.nan
        expected_lev = r.total_liabilities / r.total_assets if pd.notna(r.total_liabilities) and r.total_assets > 0 else np.nan
        expected_roa = r.operating_income / r.total_assets if pd.notna(r.operating_income) and r.total_assets > 0 else np.nan
        expected_deps = abs(r.eps - r.eps_lag) if pd.notna(r.eps) and pd.notna(r.eps_lag) else np.nan
        expected_acc = abs(r.operating_income - r.operating_cash_flow) / r.total_assets_lag if pd.notna(r.operating_income) and pd.notna(r.operating_cash_flow) and pd.notna(r.total_assets_lag) and r.total_assets_lag > 0 else np.nan
        expected_loss = float(r.adjusted_net_profit < 0) if pd.notna(r.adjusted_net_profit) else np.nan
        expected_inst = r.institutional_hold_percent / 100 if pd.notna(r.institutional_hold_percent) and 0 <= r.institutional_hold_percent <= 100 else np.nan
        expected_top = r.top1_percent / 100 if pd.notna(r.top1_percent) and 0 <= r.top1_percent <= 100 else np.nan
        expected_analyst = math.log1p(r.analyst_count) if pd.notna(r.analyst_count) and r.analyst_count >= 0 else np.nan
        expected_subs = math.log1p(r.subs_count) if pd.notna(r.subs_count) else np.nan
        checks = {
            "Size": close(expected_size, r.Size), "MB": close(expected_mb, r.MB),
            "Lev": close(expected_lev, r.Lev), "ROA": close(expected_roa, r.ROA),
            "abs_dEPS": close(expected_deps, r.abs_dEPS), "abs_Accruals": close(expected_acc, r.abs_Accruals),
            "Loss": close(expected_loss, r.Loss), "Instihold": close(expected_inst, r.Instihold),
            "Tophold": close(expected_top, r.Tophold), "Analyst": close(expected_analyst, r.Analyst),
            "Subs": close(expected_subs, r.Subs),
        }
        rows.append({
            "firm_id": r.firm_id, "year": r.year,
            "total_assets": r.total_assets, "total_liabilities": r.total_liabilities,
            "equity_parent": r.equity_parent, "market_value_thousand": r.market_value_thousand,
            "operating_income": r.operating_income, "operating_cash_flow": r.operating_cash_flow,
            "eps": r.eps, "eps_lag": r.eps_lag, "adjusted_net_profit": r.adjusted_net_profit,
            "institutional_hold_percent": r.institutional_hold_percent, "analyst_count": r.analyst_count,
            "top1_percent": r.top1_percent, "subs_count": r.subs_count,
            "auditor_names": r.auditor_names, "Stdroa_years": r.Stdroa_years,
            "Stdret_months": r.Stdret_months, "Stdret_years": r.Stdret_years,
            "Size_result": r.Size, "Size_expected": expected_size,
            "MB_result": r.MB, "MB_expected": expected_mb,
            "Lev_result": r.Lev, "Lev_expected": expected_lev,
            "ROA_result": r.ROA, "ROA_expected": expected_roa,
            "abs_dEPS_result": r.abs_dEPS, "abs_dEPS_expected": expected_deps,
            "abs_Accruals_result": r.abs_Accruals, "abs_Accruals_expected": expected_acc,
            "Loss_result": r.Loss, "Loss_expected": expected_loss,
            "Instihold_result": r.Instihold, "Instihold_expected": expected_inst,
            "Analyst_result": r.Analyst, "Analyst_expected": expected_analyst,
            "Tophold_result": r.Tophold, "Tophold_expected": expected_top,
            "Subs_result": r.Subs, "Subs_expected": expected_subs,
            "all_recomputed_formula_checks_pass": int(all(checks.values())),
            "formula_checks_json": json.dumps(checks, ensure_ascii=False, sort_keys=True),
        })
    return pd.DataFrame(rows)


def make_big4_mapping(conn: sqlite3.Connection) -> pd.DataFrame:
    observed = pd.read_sql_query(
        "SELECT raw_name,count(*) AS firm_year_name_records,min(year) AS first_year,max(year) AS last_year FROM auditors GROUP BY raw_name",
        conn,
    )
    base = pd.DataFrame([{"raw_auditor_name": name, "normalized_name": norm_text(name), "Big4": 1, "Big4_group": group} for name, group in BIG4_RAW_NAMES.items()])
    return base.merge(observed, left_on="raw_auditor_name", right_on="raw_name", how="left").drop(columns=["raw_name"]).sort_values(["Big4_group", "raw_auditor_name"])


def md_report(frame: pd.DataFrame, coverage: pd.DataFrame, formula: pd.DataFrame, spot: pd.DataFrame, big4: pd.DataFrame, metrics: dict[str, object], conn: sqlite3.Connection) -> str:
    constructed = [v for v in FORMULAS if v in frame and frame[v].notna().any()]
    missing = [v for v in FORMULAS if v not in frame or not frame[v].notna().any()]
    cov_09_22 = formula.set_index("Gao_variable")["coverage_2009_2022"].to_dict()
    source_rows = pd.read_sql_query("SELECT source_id,path,rows_seen,rows_kept,completed_at FROM source_done ORDER BY source_id", conn)
    conflicts = pd.read_sql_query("SELECT variable,count(*) AS conflicting_keys FROM num_values WHERE conflict=1 GROUP BY variable", conn)
    month_dist = frame.loc[frame["Stdret"].notna(), "Stdret_months"].describe(percentiles=[.01,.25,.5,.75,.99]).to_dict()
    lines = [
        "# Gao et al. (2024) 完整控制变量构造审计",
        "",
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}（Asia/Shanghai）",
        "",
        "## 执行边界",
        "",
        "本次只读取控制变量原始数据、行业分类和既有年报清单；未读取或修改 Treat、policy timing、SYN、stack，未运行任何DID、事件研究或其他回归。原始文件均未修改。",
        "",
        "## 构造结果",
        "",
        f"- 公司—年度唯一观测：{len(frame):,}；唯一公司：{frame.firm_id.nunique():,}；年份：{frame.year.min()}—{frame.year.max()}。",
        f"- 已构造：{', '.join(constructed)}。",
        f"- 未能完整构造：{', '.join(missing) if missing else '无'}。Length_MDA仅有特定候选样本匹配结果，不能作为全A股公司年度控制变量。",
        f"- 主键为 `firm_id+fiscal_year`（同时保留同值的 `year` 便于现有数据连接）；最终重复键：{metrics['duplicate_firm_year_final']}。",
        "- 年度覆盖率分母为当年能够在合并年末资产负债表中形成公司—年度键的公司数。",
        "- 连续变量同时保留原始值与全样本1%/99%缩尾值（后缀 `_w`）；Loss和Big4未缩尾。",
        "",
        "## 关键口径",
        "",
        "- 财务报表统一为12月31日合并报表（Typrep=A）；Typrep代码由CSMAR本地字段说明确认，A为合并报表。",
        "- MB主口径使用归属于母公司所有者权益；同时保留 `MB_total_equity` 备选口径。总市值原始单位为千元，先乘1000与财务报表元统一。权益≤0时MB设为缺失，不改变原始权益。",
        "- Stdroa采用t-2、t-1、t连续三年ROA样本标准差（ddof=1），三年缺一不可。",
        "- Stdret采用t-2至t月收益率样本标准差（ddof=1），三个日历年均须出现且总有效月数至少24；不使用周收益率。",
        "- Loss严格来自归属于上市公司股东的扣除非经常性损益后净利润F020102。",
        "- Analyst来自CSMAR AnaAttention直接数量；本字段定义为公司年度被关注的分析师数量，分析师团队按1名计，不是根据研报行数推算。",
        "- Subs为同一公司年度披露的子公司名称经NFKC、去空白、大小写标准化后的唯一名称数。原表没有“纳入合并范围”标志，因此不得表述为仅合并范围子公司。没有记录时保留缺失，不视为0。",
        "- Big4只用Source=0的定期报告审计记录且TerritoryForeignIdentity=1的境内事务所，按本报告附录中的原始名称精确映射。",
        "- Indsize_candidate为候选口径：2009—2011用P0201、2012—2022用P0207、2023—2025用P0221的二级行业；跨标准拼接已保留standard_id，不应误称为单一不变分类标准。",
        "- Length_AR_chars直接使用既有年报清单中的首选完整年报文本字符数，没有重新扫描年报。Length_MDA尚不具备完整公司年度覆盖。",
        "",
        "## 覆盖率（2009—2022）",
        "",
        "|变量|非缺失比例|",
        "|---|---:|",
    ]
    for v in FORMULAS:
        lines.append(f"|{v}|{cov_09_22.get(v, 0):.2%}|")
    lines += [
        "",
        "## 质量检查",
        "",
        f"- 资产≤0：{metrics['nonpositive_assets']:,}；母公司权益≤0：{metrics['nonpositive_parent_equity']:,}；总权益≤0：{metrics['nonpositive_total_equity']:,}。相关对数/分母变量按定义置缺失。",
        f"- 机构持股原始比例超出0—100：{metrics['inst_outside_0_100']:,}；第一大股东持股原始比例超出0—100：{metrics['top1_outside_0_100']:,}；这些异常值不进入比例变量。",
        f"- 分析师数量为负：{metrics['analyst_negative']:,}。",
        f"- 市值≤0：{metrics['market_value_nonpositive']:,}；负债<0：{metrics['liabilities_negative']:,}；Lev<0：{metrics['lev_negative']:,}；Lev>1：{metrics['lev_above_one']:,}；Lev>10：{metrics['lev_above_ten']:,}。这些原始极端值保留，正式连续变量另有1%/99%缩尾副本。",
        f"- |ROA|>1：{metrics['roa_abs_above_one']:,}；|EPS|>100：{metrics['eps_abs_above_100']:,}；abs_dEPS>100：{metrics['abs_deps_above_100']:,}；abs_Accruals>1：{metrics['accruals_above_one']:,}。未按结果删除，均通过 `_w` 提供预定缩尾版本。",
        f"- 原始数值来源冲突的公司年度键：{metrics['numeric_conflict_keys']:,}；行业冲突键：{metrics['industry_conflicts']:,}。冲突数值不凭猜测选取，置缺失。",
        f"- 子公司唯一名称记录：{metrics['subs_records']:,}；境内定期报告审计机构唯一名称记录：{metrics['auditor_records']:,}。",
        f"- 利用行业表稳定InstitutionID检查股票代码变化：{metrics['institution_ids_with_multiple_stock_codes']:,}个机构ID在2009—2025出现多个六位代码；主键仍按原始公司代码—年度保留，不跨代码擅自回填。示例见 construction_metrics.json。",
        f"- 确定性抽查：{len(spot)}条；机械公式重算全部通过：{int(spot['all_recomputed_formula_checks_pass'].sum())}/{len(spot)}。",
        f"- 可用Stdret的月数分布：{json.dumps(month_dist, ensure_ascii=False, default=float)}。",
        "",
        "### 冲突键按来源变量",
        "",
    ]
    if conflicts.empty:
        lines.append("无。")
    else:
        lines += ["|原始变量|冲突键数|", "|---|---:|"]
        for r in conflicts.itertuples(index=False):
            lines.append(f"|{r.variable}|{r.conflicting_keys:,}|")
    lines += [
        "",
        "### 输入读取记录",
        "",
        "|来源|读取行数|保留值/记录数|",
        "|---|---:|---:|",
    ]
    for r in source_rows.itertuples(index=False):
        lines.append(f"|{r.source_id}|{r.rows_seen:,}|{r.rows_kept:,}|")
    lines += [
        "",
        "## Big4精确名称映射",
        "",
        "|组别|原始事务所名称|样本记录数|覆盖年份|",
        "|---|---|---:|---|",
    ]
    for r in big4.itertuples(index=False):
        count = 0 if pd.isna(r.firm_year_name_records) else int(r.firm_year_name_records)
        period = "未观察到" if pd.isna(r.first_year) else f"{int(r.first_year)}—{int(r.last_year)}"
        lines.append(f"|{r.Big4_group}|{r.raw_auditor_name}|{count:,}|{period}|")
    lines += [
        "",
        "## 输出可用性结论",
        "",
        "可将本公司年度文件与回归样本按 `firm_id+fiscal_year`（或同值的 `year`）合并后，再按预先规定的完整案例样本运行Gao全控制模型。正式回归前应先固定是使用MB母公司权益主口径还是备选总权益口径；不得按显著性选择。Length_MDA仍应保持待补，不应以当前候选样本数据填充全样本。",
        "",
        f"Gao原文核对来源：{GAO_PDF}",
        "",
    ]
    return "\n".join(lines)


def write_outputs(frame: pd.DataFrame, win: dict[str, dict[str, float]], metrics: dict[str, object], conn: sqlite3.Connection) -> None:
    coverage = coverage_table(frame)
    formula = formula_audit(frame, win)
    spot = make_spotcheck(frame)
    big4 = make_big4_mapping(conn)
    report = md_report(frame, coverage, formula, spot, big4, metrics, conn)

    # Keep informative raw components, helper counts, raw and winsorized variables.
    core_first = ["firm_id", "year"] + CORE_VARIABLES
    win_cols = [c + "_w" for c in CORE_VARIABLES if c + "_w" in frame]
    helper = [c for c in frame.columns if c not in core_first + win_cols]
    output = frame[core_first + win_cols + helper].copy()
    output.insert(2, "fiscal_year", output["year"].astype(np.int16))

    csv_path = OUT / "gao_controls_firm_year_2009_2025.csv"
    dta_path = OUT / "gao_controls_firm_year_2009_2025.dta"
    output.to_csv(csv_path, index=False, encoding="utf-8-sig", float_format="%.12g")
    dta = output.copy()
    for col in dta.select_dtypes(include=["object"]).columns:
        dta[col] = dta[col].fillna("").astype(str)
    labels = {
        "firm_id": "Six-digit stock code", "year": "Fiscal year",
        "Size": "ln(total assets)", "MB": "Market value / parent equity (primary)",
        "Lev": "Total liabilities / total assets", "ROA": "Operating income / total assets",
        "Stdroa": "SD ROA over t-2..t, 3 years required", "abs_dEPS": "Absolute EPS change",
        "abs_Accruals": "Abs(op income-CFO)/lag assets", "Loss": "Adjusted net profit below zero",
        "Stdret": "Monthly return SD over t-2..t, >=24 months", "Instihold": "Institutional ownership 0-1",
        "Analyst": "ln(1+analyst count; team counted as one)", "Tophold": "Largest holder share 0-1",
        "Subs": "ln(1+unique disclosed subsidiary names)", "Big4": "Domestic annual-report auditor is Big4",
    }
    dta.to_stata(dta_path, write_index=False, version=118, variable_labels={k: v[:80] for k, v in labels.items() if k in dta})
    coverage.to_csv(OUT / "gao_control_coverage_by_year.csv", index=False, encoding="utf-8-sig", float_format="%.12g")
    formula.to_csv(OUT / "gao_control_formula_audit.csv", index=False, encoding="utf-8-sig", float_format="%.12g")
    big4.to_csv(OUT / "big4_name_mapping.csv", index=False, encoding="utf-8-sig")
    spot.to_csv(OUT / "gao_manual_spotcheck.csv", index=False, encoding="utf-8-sig", float_format="%.12g")
    (OUT / "gao_control_construction_audit.md").write_text(report, encoding="utf-8")
    (OUT / "construction_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=float), encoding="utf-8")
    log(f"Outputs written: {OUT}")


def verify_outputs() -> None:
    csv_path = OUT / "gao_controls_firm_year_2009_2025.csv"
    dta_path = OUT / "gao_controls_firm_year_2009_2025.dta"
    csv_df = pd.read_csv(csv_path, dtype={"firm_id": str})
    dta_df = pd.read_stata(dta_path, convert_categoricals=False)
    problems = []
    if "fiscal_year" not in csv_df or not csv_df["fiscal_year"].equals(csv_df["year"]):
        problems.append("fiscal_year missing or differs from year")
    if csv_df.duplicated(["firm_id", "fiscal_year"]).any():
        problems.append("CSV duplicate firm-year")
    if dta_df.duplicated(["firm_id", "fiscal_year"]).any():
        problems.append("DTA duplicate firm-year")
    if len(csv_df) != len(dta_df):
        problems.append("CSV/DTA row count mismatch")
    if set(CORE_VARIABLES) - set(csv_df.columns):
        problems.append("core variable missing")
    spot = pd.read_csv(OUT / "gao_manual_spotcheck.csv")
    if len(spot) < 20 or not spot["all_recomputed_formula_checks_pass"].eq(1).all():
        problems.append("manual spotcheck failed")
    if problems:
        raise RuntimeError("; ".join(problems))
    log(f"Verification passed: {len(csv_df):,} rows, {csv_df.firm_id.nunique():,} firms, no duplicate firm-year")


def main() -> None:
    missing = [str(path) for path in list(SOURCES.values()) + [INDUSTRY_DTA, AR_INVENTORY] if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing inputs:\n" + "\n".join(missing))
    conn = init_db()
    for source_id in ["balance", "income", "cfo", "eps", "loss", "market", "inst", "top", "analyst", "monthly", "subs1", "subs2", "auditor"]:
        parse_xlsx_source(conn, source_id, SOURCES[source_id])
    parse_industry(conn)
    parse_ar_inventory(conn)
    frame, win, metrics = construct(conn)
    metrics.update(audit_stock_code_changes())
    write_outputs(frame, win, metrics, conn)
    verify_outputs()
    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        raise
