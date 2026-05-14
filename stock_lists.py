"""
stock_lists.py — Dynamic stock list fetching.

Taiwan : TWSE + TPEx from ISIN page (ETFs excluded)
US     : S&P 500 from Wikipedia
"""

from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── Static fallback (used if network fails) ───────────────

TW_FALLBACK: dict[str, str] = {
    "2330": "台積電", "2317": "鴻海", "2454": "聯發科", "2412": "中華電",
    "2882": "國泰金", "2881": "富邦金", "2886": "兆豐金", "2891": "中信金",
    "2303": "聯電",   "2002": "中鋼",   "1301": "台塑",   "1303": "南亞",
    "2308": "台達電", "2382": "廣達",   "3711": "日月光投控", "2357": "華碩",
    "1216": "統一",   "2207": "和泰車", "2885": "元大金", "2884": "玉山金",
    "5880": "合庫金", "2892": "第一金", "2887": "台新金", "3045": "台灣大",
    "2883": "開發金", "2880": "華南金", "2327": "國巨",   "2912": "統一超",
    "6505": "台塑化", "1101": "台泥",   "1326": "台化",   "2395": "研華",
    "1402": "遠東新", "2301": "光寶科", "3008": "大立光", "2379": "瑞昱",
    "2376": "技嘉",   "2474": "可成",   "6669": "緯穎",   "3034": "聯詠",
    "3037": "欣興",   "2356": "英業達", "5871": "中租控股","2353": "宏碁",
    "2609": "陽明",   "2615": "萬海",   "2603": "長榮",   "2610": "華航",
    "5876": "上海商銀","2049": "上銀",  "4904": "遠傳",   "2408": "南亞科",
    "1590": "亞德客", "2347": "聯強",   "3231": "緯創",   "2345": "智邦",
}

US_FALLBACK: dict[str, str] = {
    "AAPL": "Apple",       "MSFT": "Microsoft",  "NVDA": "NVIDIA",
    "GOOGL": "Alphabet",   "AMZN": "Amazon",      "META": "Meta",
    "TSLA": "Tesla",       "AVGO": "Broadcom",    "AMD": "AMD",
    "QCOM": "Qualcomm",    "MU": "Micron",         "INTC": "Intel",
    "AMAT": "Applied Matl","KLAC": "KLA Corp",    "LRCX": "Lam Research",
    "ORCL": "Oracle",      "CRM": "Salesforce",   "ADBE": "Adobe",
    "NOW": "ServiceNow",   "INTU": "Intuit",       "PANW": "Palo Alto",
    "CRWD": "CrowdStrike", "DDOG": "Datadog",      "ZS": "Zscaler",
    "JPM": "JPMorgan",     "BAC": "BofA",          "GS": "Goldman",
    "V": "Visa",           "MA": "Mastercard",     "WMT": "Walmart",
    "COST": "Costco",      "HD": "Home Depot",     "UNH": "UnitedHealth",
    "LLY": "Eli Lilly",    "ABBV": "AbbVie",       "MRK": "Merck",
    "XOM": "ExxonMobil",   "CVX": "Chevron",       "NFLX": "Netflix",
    "BA": "Boeing",        "CAT": "Caterpillar",   "TMUS": "T-Mobile",
}


# ── Dynamic fetchers ───────────────────────────────────────

def fetch_tw_stocks(include_tpex: bool = True) -> dict[str, str]:
    """
    Fetch all Taiwan listed stocks from TWSE (+ optionally TPEx).
    Excludes ETFs (codes starting with '0').
    Falls back to TW_FALLBACK on network error.
    """
    modes   = ["2"] + (["4"] if include_tpex else [])   # 2=TWSE, 4=TPEx
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    result  : dict[str, str] = {}

    for mode in modes:
        url = f"https://isin.twse.com.tw/isin/C_public.jsp?strMode={mode}"
        try:
            resp = requests.get(url, timeout=20, headers=headers)
            resp.encoding = "big5"
            tables = pd.read_html(StringIO(resp.text))
            if not tables:
                continue

            df = tables[0]
            for _, row in df.iterrows():
                cell = str(row.iloc[0]).strip()
                if "　" not in cell:          # 　 = ideographic space
                    continue
                code, *rest = cell.split("　")
                code = code.strip()
                name = rest[0].strip() if rest else code

                # Keep 4-5 digit numeric codes NOT starting with '0'
                if code.isdigit() and not code.startswith("0") and 4 <= len(code) <= 5:
                    result[code] = name

        except Exception as exc:
            logger.warning("TW fetch failed (mode=%s): %s", mode, exc)

    if not result:
        logger.warning("Using TW fallback list (%d stocks)", len(TW_FALLBACK))
        return dict(TW_FALLBACK)

    logger.info("Fetched %d TW stocks", len(result))
    return result


def fetch_us_stocks() -> dict[str, str]:
    """
    Fetch S&P 500 constituents from Wikipedia.
    Falls back to US_FALLBACK on network error.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url, attrs={"id": "constituents"})
        df     = tables[0]
        result : dict[str, str] = {}
        for _, row in df.iterrows():
            sym  = str(row["Symbol"]).strip().replace(".", "-")
            name = str(row["Security"]).strip()
            if sym and sym.lower() != "nan":
                result[sym] = name
        logger.info("Fetched %d US stocks (S&P 500)", len(result))
        return result
    except Exception as exc:
        logger.warning("US fetch failed: %s", exc)
        return dict(US_FALLBACK)
