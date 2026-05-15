"""
stock_lists.py — Dynamic stock list fetching.

Taiwan : TWSE JSON OpenData API  (no HTML parsing → works on Streamlit Cloud)
         TPEx  JSON OpenData API
US     : S&P 500   from Wikipedia
         NASDAQ-100 static list
         DJIA       static list (30 stocks)
"""

from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ── DJIA (30 stocks, rarely changes) ─────────────────────
DJIA: dict[str, str] = {
    "AAPL":  "Apple",           "AMGN":  "Amgen",
    "AXP":   "American Express","BA":    "Boeing",
    "CAT":   "Caterpillar",     "CRM":   "Salesforce",
    "CSCO":  "Cisco",           "CVX":   "Chevron",
    "DIS":   "Disney",          "GS":    "Goldman Sachs",
    "HD":    "Home Depot",      "HON":   "Honeywell",
    "IBM":   "IBM",             "JNJ":   "Johnson & Johnson",
    "JPM":   "JPMorgan",        "KO":    "Coca-Cola",
    "MCD":   "McDonald's",      "MMM":   "3M",
    "MRK":   "Merck",           "MSFT":  "Microsoft",
    "NKE":   "Nike",            "NVDA":  "NVIDIA",
    "PG":    "Procter & Gamble","SHW":   "Sherwin-Williams",
    "TRV":   "Travelers",       "UNH":   "UnitedHealth",
    "V":     "Visa",            "VZ":    "Verizon",
    "WMT":   "Walmart",         "AMZN":  "Amazon",
}

# ── NASDAQ-100 static list ────────────────────────────────
NASDAQ100: dict[str, str] = {
    "AAPL":"Apple",        "MSFT":"Microsoft",    "NVDA":"NVIDIA",
    "AMZN":"Amazon",       "META":"Meta",          "TSLA":"Tesla",
    "GOOGL":"Alphabet A",  "GOOG":"Alphabet C",    "AVGO":"Broadcom",
    "COST":"Costco",       "NFLX":"Netflix",       "AMD":"AMD",
    "QCOM":"Qualcomm",     "INTU":"Intuit",        "AMAT":"Applied Matl",
    "CSCO":"Cisco",        "AMGN":"Amgen",         "MU":"Micron",
    "ISRG":"Intuitive Surg","TXN":"Texas Instrum", "LRCX":"Lam Research",
    "ADI":"Analog Devices","KLAC":"KLA Corp",      "SNPS":"Synopsys",
    "CDNS":"Cadence",      "REGN":"Regeneron",     "PANW":"Palo Alto",
    "MRVL":"Marvell Tech", "ASML":"ASML",          "AZN":"AstraZeneca",
    "PEP":"PepsiCo",       "SBUX":"Starbucks",     "MDLZ":"Mondelez",
    "GILD":"Gilead",       "VRTX":"Vertex Pharma", "INTC":"Intel",
    "PYPL":"PayPal",       "MAR":"Marriott",       "ORLY":"O'Reilly Auto",
    "MELI":"MercadoLibre", "FTNT":"Fortinet",      "WDAY":"Workday",
    "PCAR":"PACCAR",       "AEP":"AEP",            "NXPI":"NXP Semi",
    "ABNB":"Airbnb",       "TEAM":"Atlassian",     "DXCM":"Dexcom",
    "ODFL":"Old Dominion", "PAYX":"Paychex",       "EXC":"Exelon",
    "MCHP":"Microchip",    "DLTR":"Dollar Tree",   "FAST":"Fastenal",
    "ROST":"Ross Stores",  "VRSK":"Verisk",         "CTSH":"Cognizant",
    "IDXX":"IDEXX Labs",   "BIIB":"Biogen",         "BKR":"Baker Hughes",
    "FANG":"Diamondback E","XEL":"Xcel Energy",    "EA":"Electronic Arts",
    "ON":"ON Semiconductor","ANSS":"Ansys",          "ZS":"Zscaler",
    "CRWD":"CrowdStrike",  "DDOG":"Datadog",        "CCEP":"Coca-Cola Euro",
    "CTAS":"Cintas",       "CEG":"Constellation E", "GEHC":"GE Healthcare",
    "GFS":"GlobalFoundries","TTD":"The Trade Desk", "MNST":"Monster Bev",
    "KDP":"Keurig DrPepper","ROP":"Roper Tech",    "ILMN":"Illumina",
    "WBD":"Warner Bros",   "SIRI":"Sirius XM",     "MRNA":"Moderna",
    "KHC":"Kraft Heinz",   "CHTR":"Charter Comm",  "ADSK":"Autodesk",
    "LULU":"Lululemon",    "EBAY":"eBay",          "LCID":"Lucid Group",
    "RIVN":"Rivian",       "OKTA":"Okta",          "DOCU":"DocuSign",
    "SNOW":"Snowflake",    "NET":"Cloudflare",     "PLTR":"Palantir",
    "ARM":"ARM Holdings",  "SMCI":"Super Micro",   "FICO":"FICO",
}

# ── Taiwan static fallback (≈400 major stocks) ───────────
TW_STATIC: dict[str, str] = {
    # === Semiconductors / Electronics ===
    "2330":"台積電",   "2303":"聯電",     "2344":"華邦電",   "2408":"南亞科",
    "2449":"京元電子", "2454":"聯發科",   "3034":"聯詠",     "3008":"大立光",
    "3711":"日月光投控","2379":"瑞昱",   "2345":"智邦",     "3231":"緯創",
    "2356":"英業達",   "2324":"仁寶",     "2382":"廣達",     "2357":"華碩",
    "2353":"宏碁",     "2317":"鴻海",     "2308":"台達電",   "2327":"國巨",
    "2376":"技嘉",     "2377":"微星",     "3035":"智原",     "3036":"文曄",
    "3037":"欣興",     "3044":"健鼎",     "3443":"創意",     "3481":"群創",
    "2409":"友達",     "2498":"宏達電",   "2478":"大毅",     "2474":"可成",
    "2458":"義隆",     "2439":"美律",     "2421":"建準",     "2395":"研華",
    "2392":"正崴",     "2388":"威盛",     "2385":"群光",     "2383":"台光電",
    "2362":"藍天",     "2360":"致茂",     "2354":"鴻準",     "2351":"順德",
    "2337":"旺宏",     "2332":"友訊",     "2325":"矽品",     "2323":"中環",
    "2321":"東訊",     "2314":"台灣光罩", "2313":"鑽石",     "2312":"金寶",
    "2311":"日月光",   "2309":"台灣晶技", "2305":"全友",     "2302":"麗正",
    "2301":"光寶科",   "3706":"神達",     "3533":"嘉澤",     "3529":"力旺",
    "3526":"凡甲",     "3519":"綠能科技", "3518":"柏騰",     "3515":"華擎",
    "3514":"昱晶",     "3508":"位元組",   "3504":"揚明光學", "3494":"昂寶",
    "3491":"昊翔",     "3489":"康控",     "3488":"通嘉",     "3484":"希華",
    "3483":"力致科技", "3479":"安勒",     "3474":"華亞科",   "3466":"聚積",
    "3465":"昇銳",     "3461":"中信金",   "3456":"奇偶",     "3455":"由田",
    "3454":"晶睿",     "3450":"聯鈞",     "3447":"展達",     "3443":"創意",
    "3432":"工業富聯", "3431":"宏里",     "3428":"崇越電通", "3426":"鈞寶",
    "3413":"京鼎",     "3406":"玉晶光",   "3402":"漢微科",   "3396":"金車",
    "3390":"旭品",     "3388":"崇越",     "3383":"新境界",   "3380":"明泰",
    "3376":"新日興",   "3374":"精材",     "3372":"典範",     "3370":"直得",
    "3363":"上詮",     "3361":"加加",     "3356":"奇偶",     "3355":"明泰",
    "3354":"晶睿通訊", "3353":"錼創",     "3352":"禾瑞亞",   "3350":"東貝",
    "3348":"泰谷",     "3345":"天鈺",     "3344":"威強電",   "3338":"泰碩",
    "3337":"阿思拓",   "3334":"志豐",     "3332":"幸康",     "3330":"金鼎",
    "3324":"雙鴻",     "3323":"加百裕",   "3321":"同泰",     "3317":"繁",
    "3315":"漢達",     "3313":"斐成",     "3311":"閎康",     "3306":"鼎翰",
    "3305":"昇貿",     "3304":"呈杰",     "3303":"岳豐",     "3299":"群聯",
    "3293":"鈊象",     "3292":"連展",     "3291":"達普",     "3289":"宏碁雲創",
    "3288":"點序",     "3287":"廣虹",     "3286":"點晶",     "3285":"微端",
    "3281":"鑫蘭蒂",   "3277":"達廣",     "3276":"宏正",     "3275":"聯誼",
    # === IC Design ===
    "2388":"威盛",     "6202":"盛群",     "6271":"同欣電",   "6285":"啟碁",
    "6286":"立錡",     "6288":"聯合光電", "6289":"華上",     "6290":"良工",
    "6291":"沛亨",     "6292":"迅德",     "6293":"頎邦",     "6294":"智凡迪",
    "6296":"圓展",     "6297":"文曄",     "6298":"崑山",
    # === Telecommunications ===
    "2412":"中華電信", "3045":"台灣大哥大","4904":"遠傳電信",
    # === Financial ===
    "2880":"華南金",   "2881":"富邦金",   "2882":"國泰金",   "2883":"開發金",
    "2884":"玉山金",   "2885":"元大金",   "2886":"兆豐金",   "2887":"台新金",
    "2888":"新光金",   "2889":"國票金",   "2890":"永豐金",   "2891":"中信金",
    "2892":"第一金",   "2897":"王道銀行", "5876":"上海商銀", "5880":"合庫金",
    "2801":"彰化銀行", "2809":"京城銀行", "2812":"台中銀行", "2823":"中壽",
    "2826":"臺灣企銀", "2833":"台灣人壽", "2834":"臺灣企銀", "2836":"台工銀",
    "2838":"聯邦銀行", "2850":"新光人壽", "2851":"中再保",   "2852":"第一保",
    "2855":"統一證",   "2856":"元大證",   "2860":"新光金",   "2862":"群益金鼎",
    # === Plastic / Chemical ===
    "1301":"台塑",     "1303":"南亞",     "1304":"台聚",     "1305":"華夏",
    "1326":"台化",     "1710":"東聯",     "1722":"台肥",     "6505":"台塑化",
    # === Auto / Machinery ===
    "2201":"裕隆",     "2204":"中華汽車", "2207":"和泰車",   "1590":"亞德客",
    "2049":"上銀",
    # === Steel / Metal ===
    "2002":"中鋼",     "2006":"東和",     "2014":"中鴻",     "2015":"豐興",
    "2317":"鴻海",
    # === Shipping / Transport ===
    "2603":"長榮",     "2609":"陽明",     "2615":"萬海",     "2610":"中華航空",
    "2618":"長榮航空", "2606":"裕民",     "2633":"台灣高鐵",
    # === Food / Consumer ===
    "1216":"統一",     "1210":"大成",     "1227":"佳格",     "1229":"聯華",
    "1232":"大統益",   "1234":"黑松",     "2912":"統一超商", "2915":"潤泰全球",
    # === Construction ===
    "2548":"華固",     "2542":"興富發",   "2534":"宏盛",
    # === Biotech / Pharma ===
    "1789":"神隆",     "4726":"永日",     "4718":"大洋",     "6446":"藥華醫藥",
    "1762":"中化生科", "1760":"寶齡富錦",
    # === Retail ===
    "2451":"創見",     "2450":"神腦",
    # === Rental / Leasing ===
    "5871":"中租控股",
    # === OTC (TPEx) Major stocks ===
    "3673":"TPK宸鴻",  "3008":"大立光",   "6669":"緯穎",     "6230":"超眾",
    "6488":"環球晶",   "3514":"昱晶",     "6239":"力成",     "6443":"元晶",
    "6598":"群電",     "3529":"力旺",     "6670":"復盛",     "6120":"輔創",
    "3105":"穩懋",     "3141":"晶宏",     "6409":"旭德",     "6415":"矽力-KY",
    "6427":"詮達",     "6616":"阿碼",     "6510":"精測",     "4966":"瑞鼎",
    "4968":"立積",     "4919":"新唐",     "4916":"事必達",   "4938":"和碩",
    "4927":"泰鼎",     "4967":"十銓",     "4971":"IET-KY",
    # === More important large/mid caps ===
    "2353":"宏碁",     "3714":"富采",     "6743":"廣積",     "6669":"緯穎",
    "2367":"燿華",     "2368":"金像電",   "2369":"菱生",     "2371":"大同",
    "3706":"神達",     "3533":"嘉澤",
}

# ─────────────────────────────────────────────────────────
#  Dynamic fetchers
# ─────────────────────────────────────────────────────────

def _fetch_twse_json() -> dict[str, str]:
    """
    TWSE OpenData JSON API — 上市普通股，回傳 {code.TW: name}。
    Non-trading days or failure → empty dict.
    """
    url = "https://opendata.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, timeout=15, headers=headers)
        data = resp.json()
        result: dict[str, str] = {}
        for item in data:
            code = str(item.get("證券代號", "")).strip()
            name = str(item.get("證券名稱", "")).strip()
            # Only numeric 4-5 digit codes NOT starting with 0 (excludes ETFs)
            if code.isdigit() and not code.startswith("0") and 4 <= len(code) <= 5:
                result[f"{code}.TW"] = name          # 上市 → .TW
        return result
    except Exception as exc:
        logger.warning("TWSE JSON API failed: %s", exc)
        return {}


def _fetch_tpex_json() -> dict[str, str]:
    """
    TPEx OpenData JSON API — 上櫃普通股，回傳 {code.TWO: name}。
    Returns empty dict on failure.
    """
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, timeout=15, headers=headers)
        data = resp.json()
        result: dict[str, str] = {}
        for item in data:
            code = str(item.get("SecuritiesCompanyCode",
                        item.get("Code", ""))).strip()
            name = str(item.get("CompanyName",
                        item.get("Name", code))).strip()
            if code.isdigit() and not code.startswith("0") and 4 <= len(code) <= 5:
                result[f"{code}.TWO"] = name          # 上櫃 → .TWO
        return result
    except Exception as exc:
        logger.warning("TPEx JSON API failed: %s", exc)
        return {}


def fetch_tw_stocks(include_tpex: bool = True) -> dict[str, str]:
    """
    Fetch Taiwan listed stocks.
    Keys are full yfinance tickers:  上市 → XXXX.TW  /  上櫃 → XXXX.TWO

    Strategy:
      1. TWSE JSON OpenData  → {code.TW:  name}
      2. TPEx JSON OpenData  → {code.TWO: name}
      3. TW_STATIC fallback  → add as code.TW if neither suffix is present yet
    """
    result: dict[str, str] = {}

    twse = _fetch_twse_json()
    result.update(twse)
    logger.info("TWSE JSON: %d stocks (.TW)", len(twse))

    if include_tpex:
        tpex = _fetch_tpex_json()
        result.update(tpex)
        logger.info("TPEx JSON: %d stocks (.TWO)", len(tpex))

    # Static fallback: only add if NEITHER suffix is already present
    for code, name in TW_STATIC.items():
        if f"{code}.TW" not in result and f"{code}.TWO" not in result:
            result[f"{code}.TW"] = name   # TW_STATIC 均為上市，用 .TW

    logger.info("Total TW stocks: %d", len(result))
    return result


# ─────────────────────────────────────────────────────────
#  US stock fetchers
# ─────────────────────────────────────────────────────────

def _fetch_sp500_github() -> dict[str, str]:
    """
    Fetch S&P 500 from GitHub datasets CSV (most reliable, no HTML parsing).
    https://github.com/datasets/s-and-p-500-companies
    """
    url = (
        "https://raw.githubusercontent.com/datasets/"
        "s-and-p-500-companies/main/data/constituents.csv"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, timeout=15, headers=headers)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        result: dict[str, str] = {}
        for _, row in df.iterrows():
            sym  = str(row.get("Symbol", "")).strip().replace(".", "-")
            name = str(row.get("Name", "")).strip()
            if sym and sym.lower() not in ("nan", ""):
                result[sym] = name
        logger.info("S&P 500 from GitHub CSV: %d stocks", len(result))
        return result
    except Exception as exc:
        logger.warning("S&P 500 GitHub CSV failed: %s", exc)
        return {}


def _fetch_sp500_wiki() -> dict[str, str]:
    """
    Fetch S&P 500 from Wikipedia.
    Uses requests + StringIO so lxml doesn't need to open the URL itself.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, timeout=20, headers=headers)
        resp.raise_for_status()
        tables = pd.read_html(StringIO(resp.text), attrs={"id": "constituents"})
        df = tables[0]
        result: dict[str, str] = {}
        for _, row in df.iterrows():
            sym  = str(row["Symbol"]).strip().replace(".", "-")
            name = str(row["Security"]).strip()
            if sym and sym.lower() != "nan":
                result[sym] = name
        logger.info("S&P 500 from Wikipedia: %d stocks", len(result))
        return result
    except Exception as exc:
        logger.warning("S&P 500 wiki fetch failed: %s", exc)
        return {}


# ── S&P 500 static fallback (major constituents, ~400 stocks) ────────────────
# Used only when both GitHub CSV and Wikipedia are unreachable.
# Covers the bulk of S&P 500 market cap; updated manually as needed.
SP500_STATIC: dict[str, str] = {
    # Financials
    "JPM":"JPMorgan Chase",    "BAC":"Bank of America",  "WFC":"Wells Fargo",
    "MS":"Morgan Stanley",     "GS":"Goldman Sachs",     "BLK":"BlackRock",
    "SPGI":"S&P Global",       "MCO":"Moody's",          "C":"Citigroup",
    "USB":"U.S. Bancorp",      "PNC":"PNC Financial",    "TFC":"Truist Financial",
    "COF":"Capital One",       "AIG":"AIG",              "MET":"MetLife",
    "PRU":"Prudential",        "AFL":"Aflac",            "ALL":"Allstate",
    "CB":"Chubb",              "MMC":"Marsh McLennan",   "AON":"Aon",
    "ICE":"Intercontinental",  "CME":"CME Group",        "NDAQ":"Nasdaq",
    "SCHW":"Charles Schwab",   "BK":"BNY Mellon",        "STT":"State Street",
    "FITB":"Fifth Third",      "RF":"Regions Financial", "CFG":"Citizens Financial",
    "HBAN":"Huntington",       "MTB":"M&T Bank",         "KEY":"KeyCorp",
    "DFS":"Discover",          "SYF":"Synchrony",        "AMP":"Ameriprise",
    "TROW":"T. Rowe Price",    "IVZ":"Invesco",          "BEN":"Franklin Resources",
    "FDS":"FactSet",           "MSCI":"MSCI",
    # Healthcare
    "LLY":"Eli Lilly",         "JNJ":"Johnson & Johnson","ABT":"Abbott",
    "TMO":"Thermo Fisher",     "DHR":"Danaher",          "PFE":"Pfizer",
    "BMY":"Bristol-Myers",     "CVS":"CVS Health",       "CI":"Cigna",
    "HUM":"Humana",            "ELV":"Elevance Health",  "CNC":"Centene",
    "MOH":"Molina Healthcare", "UHS":"Universal Health", "HCA":"HCA Healthcare",
    "THC":"Tenet Healthcare",  "IQV":"IQVIA",            "A":"Agilent",
    "WAT":"Waters Corp",       "MTD":"Mettler-Toledo",   "BIO":"Bio-Rad",
    "HOLX":"Hologic",          "ALGN":"Align Technology","STE":"STERIS",
    "EW":"Edwards Lifesciences","BSX":"Boston Scientific","MDT":"Medtronic",
    "SYK":"Stryker",           "ZBH":"Zimmer Biomet",    "BDX":"Becton Dickinson",
    "BAX":"Baxter",            "DXCM":"Dexcom",          "PODD":"Insulet",
    "INCY":"Incyte",           "EXAS":"Exact Sciences",  "MASI":"Masimo",
    "PKI":"PerkinElmer",       "DGX":"Quest Diagnostics","LH":"LabCorp",
    "RMD":"ResMed",            "TFX":"Teleflex",         "XRAY":"Dentsply",
    "VTRS":"Viatris",          "OGN":"Organon",          "MHK":"Mohawk Ind",
    "GEHC":"GE HealthCare",    "SOLV":"Solventum",
    # Energy
    "XOM":"ExxonMobil",        "COP":"ConocoPhillips",   "SLB":"Schlumberger",
    "EOG":"EOG Resources",     "PSX":"Phillips 66",      "MPC":"Marathon Petroleum",
    "VLO":"Valero Energy",     "OXY":"Occidental",       "HAL":"Halliburton",
    "BKR":"Baker Hughes",      "DVN":"Devon Energy",     "HES":"Hess",
    "MRO":"Marathon Oil",      "APA":"APA Corp",         "FANG":"Diamondback E",
    "PR":"Permian Resources",  "EQT":"EQT Corp",         "SWN":"Southwest Gas",
    "RRC":"Range Resources",   "CNX":"CNX Resources",    "NOV":"NOV Inc",
    "FTI":"TechnipFMC",        "WHD":"Cactus",           "TRGP":"Targa Resources",
    "WMB":"Williams Companies","OKE":"ONEOK",             "KMI":"Kinder Morgan",
    "LNG":"Cheniere Energy",   "ET":"Energy Transfer",
    # Consumer Staples
    "PG":"Procter & Gamble",   "KO":"Coca-Cola",         "PEP":"PepsiCo",
    "PM":"Philip Morris",      "MO":"Altria",            "MDLZ":"Mondelez",
    "KHC":"Kraft Heinz",       "GIS":"General Mills",    "CPB":"Campbell Soup",
    "HRL":"Hormel Foods",      "SJM":"J.M. Smucker",     "CAG":"Conagra Brands",
    "K":"Kellanova",           "MKC":"McCormick",        "CHD":"Church & Dwight",
    "CL":"Colgate-Palmolive",  "CLX":"Clorox",           "KMB":"Kimberly-Clark",
    "EL":"Estee Lauder",       "KVUE":"Kenvue",          "REVG":"Rev Group",
    "TSN":"Tyson Foods",       "PPC":"Pilgrim's Pride",  "SAFM":"Sanderson Farms",
    "WBA":"Walgreens",         "SYY":"Sysco",            "US":"US Foods",
    "KR":"Kroger",             "ACI":"Albertsons",       "BJ":"BJ's Wholesale",
    # Consumer Discretionary
    "AMZN":"Amazon",           "TSLA":"Tesla",           "HD":"Home Depot",
    "MCD":"McDonald's",        "NKE":"Nike",             "LOW":"Lowe's",
    "TGT":"Target",            "TJX":"TJX Companies",    "ROST":"Ross Stores",
    "BURL":"Burlington",       "GPS":"Gap",              "ANF":"Abercrombie",
    "PVH":"PVH Corp",          "RL":"Ralph Lauren",      "URBN":"Urban Outfitters",
    "HBI":"Hanesbrands",       "VFC":"VF Corp",          "TPR":"Tapestry",
    "CPRI":"Capri Holdings",   "WWW":"Wolverine World",
    "NVR":"NVR Inc",           "PHM":"PulteGroup",       "DHI":"D.R. Horton",
    "LEN":"Lennar",            "TOL":"Toll Brothers",    "MDC":"MDC Holdings",
    "LGIH":"LGI Homes",        "SKY":"Skyline Champion",
    "GM":"General Motors",     "F":"Ford Motor",         "APTV":"Aptiv",
    "LEA":"Lear Corp",         "BWA":"BorgWarner",       "MGA":"Magna Intl",
    "TSCO":"Tractor Supply",   "DG":"Dollar General",    "DLTR":"Dollar Tree",
    "AZO":"AutoZone",          "AAP":"Advance Auto",     "ORLY":"O'Reilly Auto",
    "KMX":"CarMax",            "AN":"AutoNation",
    "PAG":"Penske Auto",       "SAH":"Sonic Automotive",
    "SBUX":"Starbucks",        "YUM":"Yum! Brands",      "QSR":"Restaurant Brands",
    "DPZ":"Domino's Pizza",    "CMG":"Chipotle",         "SHAK":"Shake Shack",
    "TXRH":"Texas Roadhouse",  "DRI":"Darden Restaurants",
    "HLT":"Hilton",            "MAR":"Marriott",         "H":"Hyatt",
    "WH":"Wyndham Hotels",     "IHG":"IHG Hotels",       "CHH":"Choice Hotels",
    "LVS":"Las Vegas Sands",   "MGM":"MGM Resorts",      "WYNN":"Wynn Resorts",
    "CZR":"Caesars",           "PENN":"PENN Entertainment",
    "CCL":"Carnival",          "RCL":"Royal Caribbean",  "NCLH":"Norwegian Cruise",
    "VAC":"Marriott Vacations", "HGV":"Hilton Grand",
    "BKNG":"Booking Holdings", "EXPE":"Expedia",         "TRIP":"TripAdvisor",
    "ABNB":"Airbnb",
    "NWS":"News Corp",         "NWSA":"News Corp A",     "FOX":"Fox Corp",
    "FOXA":"Fox Corp A",       "DIS":"Disney",           "WBD":"Warner Bros",
    "PARA":"Paramount",        "LYV":"Live Nation",      "SEAS":"SeaWorld",
    # Industrials
    "GE":"GE Aerospace",       "RTX":"RTX Corp",         "LMT":"Lockheed Martin",
    "NOC":"Northrop Grumman",  "BA":"Boeing",            "GD":"General Dynamics",
    "LHX":"L3Harris",          "TDG":"TransDigm",        "HWM":"Howmet",
    "AXON":"Axon Enterprise",  "SAIC":"SAIC",            "LDOS":"Leidos",
    "BAH":"Booz Allen",        "DRS":"Leonardo DRS",
    "UPS":"UPS",               "FDX":"FedEx",            "XPO":"XPO",
    "JBHT":"J.B. Hunt",        "ODFL":"Old Dominion",    "SAIA":"Saia",
    "RXO":"RXO Inc",           "CHRW":"C.H. Robinson",   "EXPD":"Expeditors",
    "FWRD":"Forward Air",      "HUBG":"Hub Group",
    "CSX":"CSX",               "UNP":"Union Pacific",    "NSC":"Norfolk Southern",
    "CNI":"Canadian National", "CP":"Canadian Pacific",  "WAB":"Wabtec",
    "TT":"Trane Technologies", "CARR":"Carrier",         "OTIS":"Otis",
    "EMR":"Emerson Electric",  "ETN":"Eaton",            "ROK":"Rockwell Auto",
    "AME":"AMETEK",            "PH":"Parker Hannifin",   "ITW":"Illinois Tool",
    "DOV":"Dover",             "GWW":"W.W. Grainger",    "MSM":"MSC Industrial",
    "FAST":"Fastenal",         "WSO":"Watsco",           "AIT":"Applied Ind",
    "CNXC":"Concentrix",       "CTAS":"Cintas",          "RHI":"Robert Half",
    "MAN":"ManpowerGroup",     "KELYA":"Kelly Services",
    "WM":"Waste Management",   "RSG":"Republic Services","CWST":"Casella Waste",
    "SRCL":"Stericycle",       "CLH":"Clean Harbors",
    "CAT":"Caterpillar",       "DE":"Deere",             "AGCO":"AGCO",
    "CNH":"CNH Industrial",    "PCAR":"PACCAR",          "TEX":"Terex",
    "IR":"Ingersoll Rand",     "GNRC":"Generac",         "FELE":"Franklin Electric",
    "RBC":"RBC Bearings",      "SPX":"SPX Technologies",
    "MMM":"3M",                "HON":"Honeywell",        "GPC":"Genuine Parts",
    "SWK":"Stanley Black&Decker","ALLE":"Allegion",      "AOS":"A.O. Smith",        "LII":"Lennox Intl",      "MAS":"Masco",
    "FBHS":"Fortune Brands",   "TREX":"Trex",
    # Technology (beyond NASDAQ-100)
    "ACN":"Accenture",         "IBM":"IBM",              "HPQ":"HP Inc",
    "HPE":"HP Enterprise",     "DXC":"DXC Technology",   "EPAM":"EPAM",
    "CTSH":"Cognizant",        "IT":"Gartner",           "G":"Genpact",
    "WEX":"WEX Inc",           "FIS":"FIS",              "FISV":"Fiserv",
    "GPN":"Global Payments",   "JKHY":"Jack Henry",      "BR":"Broadridge",
    "ADP":"ADP",               "PAYX":"Paychex",         "INFY":"Infosys",
    "WIT":"Wipro",             "SAP":"SAP",              "ORCL":"Oracle",
    "NOW":"ServiceNow",        "CRM":"Salesforce",       "WDAY":"Workday",
    "VEEV":"Veeva Systems",    "HUBS":"HubSpot",         "ZI":"ZoomInfo",
    "NCNO":"nCino",            "PCOR":"Procore",         "BILL":"Bill.com",
    "TOST":"Toast",            "FOUR":"Shift4 Payments",
    "DELL":"Dell Technologies","STX":"Seagate",
    "WDC":"Western Digital",   "NTAP":"NetApp",          "PSTG":"Pure Storage",
    "CRUS":"Cirrus Logic",     "SWKS":"Skyworks",        "QRVO":"Qorvo",
    "KEYS":"Keysight",         "NATI":"NI Corp",         "TRMB":"Trimble",
    "ITRI":"Itron",            "BDC":"Belden",
    "VIAV":"Viavi Solutions",  "CIEN":"Ciena",           "LITE":"Lumentum",
    "IIVI":"II-VI Incorporated", "COHU":"Cohu",
    "GDDY":"GoDaddy",          "VRT":"Vertiv",           "SMCI":"Super Micro",
    "NTDOY":"Nintendo",
    # Communication Services
    "T":"AT&T",                "VZ":"Verizon",           "TMUS":"T-Mobile",
    "CHTR":"Charter Comm",     "CMCSA":"Comcast",        "DISH":"Dish Network",
    "CABO":"Cable One",        "WOW":"WideOpenWest",
    "OMC":"Omnicom",           "IPG":"Interpublic",      "WPP":"WPP",
    "PUBM":"PubMatic",         "MGNI":"Magnite",         "IAS":"Integral Ad",
    "EA":"Electronic Arts",    "TTWO":"Take-Two Intl",   "RBLX":"Roblox",
    "U":"Unity Software",      "MTCH":"Match Group",     "BMBL":"Bumble",
    "SNAP":"Snap",             "PINS":"Pinterest",       "RDDT":"Reddit",
    # Materials
    "LIN":"Linde",             "APD":"Air Products",     "ECL":"Ecolab",
    "SHW":"Sherwin-Williams",  "PPG":"PPG Industries",   "IFF":"Intl Flavors",
    "RPM":"RPM International", "FMC":"FMC Corp",         "CE":"Celanese",
    "EMN":"Eastman Chemical",  "HUN":"Huntsman",         "CC":"Chemours",
    "OLN":"Olin Corp",         "ASH":"Ashland",          "TROX":"Tronox",
    "NEM":"Newmont",           "FCX":"Freeport-McMoRan", "NUE":"Nucor",
    "STLD":"Steel Dynamics",   "RS":"Reliance Steel",    "CMC":"Commercial Metals",
    "ATI":"ATI Inc",           "X":"U.S. Steel",         "CLF":"Cleveland-Cliffs",
    "AA":"Alcoa",              "CENX":"Century Aluminum",
    "VMC":"Vulcan Materials",  "MLM":"Martin Marietta",  "SUM":"Summit Materials",
    "EXP":"Eagle Materials",   "USG":"USG Corp",
    "IP":"International Paper","PKG":"Packaging Corp",   "SEE":"Sealed Air",
    "SON":"Sonoco Products",   "SLVM":"Sylvamo",         "FIBK":"First Intermountain",
    # Utilities
    "NEE":"NextEra Energy",    "DUK":"Duke Energy",      "SO":"Southern Co",
    "D":"Dominion Energy",     "AEP":"AEP",              "EXC":"Exelon",
    "SRE":"Sempra",            "PCG":"PG&E",             "ED":"Consolidated Edison",
    "ETR":"Entergy",           "FE":"FirstEnergy",       "PPL":"PPL Corp",
    "CMS":"CMS Energy",        "AES":"AES Corp",         "NRG":"NRG Energy",
    "VST":"Vistra",            "CEG":"Constellation",    "LNT":"Alliant Energy",
    "EVRG":"Evergy",           "POR":"Portland General", "NWE":"NorthWestern",
    "EIX":"Edison International","XEL":"Xcel Energy",   "PNW":"Pinnacle West",
    "WEC":"WEC Energy",        "DTE":"DTE Energy",       "CNP":"CenterPoint",
    "AWK":"American Water",    "SJW":"SJW Group",        "MSEX":"Middlesex Water",
    "AWR":"American States",   "CWT":"California Water",
    "ATO":"Atmos Energy",      "NI":"NiSource",          "SR":"Spire",
    "OGS":"ONE Gas",           "UGI":"UGI Corp",
    # Real Estate (REITs)
    "AMT":"American Tower",    "PLD":"Prologis",         "EQIX":"Equinix",
    "CCI":"Crown Castle",      "SPG":"Simon Property",   "O":"Realty Income",
    "PSA":"Public Storage",    "EXR":"Extra Space",      "CUBE":"CubeSmart",
    "LSI":"Life Storage",      "NSA":"National Storage",
    "AVB":"AvalonBay",         "EQR":"Equity Residential","UDR":"UDR Inc",
    "AIV":"Apartment Income",  "NMI":"NMI Holdings",
    "WELL":"Welltower",        "VTR":"Ventas",           "PEAK":"Healthpeak",
    "HR":"Healthcare Realty",  "OHI":"Omega Healthcare", "MPW":"Medical Properties",
    "SBAC":"SBA Communications","UNIT":"Uniti Group",
    "BXP":"BXP Inc",           "VNO":"Vornado",          "KIM":"Kimco Realty",
    "REG":"Regency Centers",   "FRT":"Federal Realty",   "BRX":"Brixmor",
    "RPAI":"InvenTrust",       "ESRT":"Empire State",
    "DLR":"Digital Realty",    "IRM":"Iron Mountain",    "QTS":"QTS Realty",
    "COR":"Coresite",          "CONE":"CyrusOne",        "SWCH":"Switch",
    "GLPI":"Gaming & Leisure", "VICI":"VICI Properties", "MGP":"MGM Growth",
    "EPR":"EPR Properties",    "SRC":"Spirit Realty",    "STOR":"STORE Capital",
    "ADC":"Agree Realty",      "NNN":"NNN REIT",         "WPC":"W. P. Carey",
    "PINE":"Alpine Income",    "NTST":"Netstreit",
    # Additional large caps not in NASDAQ-100/DJIA
    "BRK-B":"Berkshire Hathaway B", "BRK-A":"Berkshire Hathaway A",
    "V":"Visa",                "MA":"Mastercard",        "PYPL":"PayPal",
    "SQ":"Block Inc",          "AFRM":"Affirm",          "SOFI":"SoFi",
    "WEX":"WEX Inc",
    "UNH":"UnitedHealth",      "ABBV":"AbbVie",          "TMO":"Thermo Fisher",
    "ABT":"Abbott",            "DHR":"Danaher",
    "COST":"Costco",           "WMT":"Walmart",          "TGT":"Target",
    "AMGN":"Amgen",            "GILD":"Gilead",          "REGN":"Regeneron",
    "VRTX":"Vertex",           "MRNA":"Moderna",         "BIIB":"Biogen",
    "LLY":"Eli Lilly",         "PFE":"Pfizer",           "BMY":"Bristol-Myers",
    "MRK":"Merck",
    "INTC":"Intel",            "TXN":"Texas Instruments","QCOM":"Qualcomm",
    "AMAT":"Applied Materials","LRCX":"Lam Research",    "KLAC":"KLA",
    "ADI":"Analog Devices",    "MCHP":"Microchip",       "ON":"ON Semi",
    "NXPI":"NXP Semi",         "STM":"STMicro",          "WOLF":"Wolfspeed",
    "ENPH":"Enphase",          "SEDG":"SolarEdge",       "RUN":"Sunrun",
    "FSLR":"First Solar",      "ARRY":"Array Technologies",
    "TSLA":"Tesla",            "GM":"General Motors",    "F":"Ford",
    "RIVN":"Rivian",           "LCID":"Lucid",           "FSR":"Fisker",
    "XYL":"Xylem",             "TRMK":"Trustmark",       "IEX":"IDEX Corp",
    "DHX":"DHI Group",         "POOL":"Pool Corp",       "SSD":"Simpson Mfg",
    "SITE":"SiteOne",          "BECN":"Beacon Roofing",  "IBP":"Install-Base",
    "BLDR":"Builders FirstSource","MAS":"Masco",
}


def _fetch_nasdaq_trader() -> dict[str, str]:
    """
    Fetch all US stocks from NASDAQ Trader FTP symbol directory files.
    Covers ~5 000 stocks across NASDAQ, NYSE, AMEX (excludes ETFs & test issues).
    """
    result: dict[str, str] = {}
    urls = [
        "https://ftp.nasdaqtrader.com/SymbolDirectory/nasdaqlisted.txt",
        "https://ftp.nasdaqtrader.com/SymbolDirectory/otherlisted.txt",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    for url in urls:
        is_nasdaq = "nasdaqlisted" in url
        try:
            resp = requests.get(url, timeout=20, headers=headers)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
            if len(lines) < 2:
                continue

            header = [h.strip() for h in lines[0].split("|")]

            # Column indices (field names differ between the two files)
            try:
                sym_col  = header.index("Symbol"      if is_nasdaq else "ACT Symbol")
                name_col = header.index("Security Name")
                etf_col  = header.index("ETF")
                test_col = header.index("Test Issue")
            except ValueError as exc:
                logger.warning("Header parse error (%s): %s", url, exc)
                continue

            for line in lines[1:]:
                parts = line.strip().split("|")
                needed = max(sym_col, name_col, etf_col, test_col)
                if len(parts) <= needed:
                    continue

                sym  = parts[sym_col].strip()
                name = parts[name_col].strip()
                etf  = parts[etf_col].strip().upper()
                test = parts[test_col].strip().upper()

                # Skip ETFs, test issues, and the trailing metadata line
                if etf == "Y" or test == "Y":
                    continue
                if not sym or sym.lower().startswith("file"):
                    continue

                # Normalise dots → dashes (yfinance convention: BRK.B → BRK-B)
                sym = sym.replace(".", "-")

                # Accept 1–5 char purely alphabetic symbols (+ dash for class shares)
                if not (1 <= len(sym) <= 6):
                    continue
                if not all(c.isalpha() or c == "-" for c in sym):
                    continue

                result[sym] = name

        except Exception as exc:
            logger.warning("NASDAQ Trader fetch failed (%s): %s", url, exc)

    logger.info("NASDAQ Trader total: %d stocks", len(result))
    return result


def fetch_us_stocks(
    include_sp500:   bool = True,
    include_nasdaq:  bool = True,
    include_djia:    bool = True,
    include_all:     bool = False,
) -> dict[str, str]:
    """
    Fetch US stocks based on selected indices.

    include_all=True  → NASDAQ Trader full list (~5 000 stocks, slower)
    Otherwise         → S&P 500 (Wikipedia) + NASDAQ-100 + DJIA static lists
    """
    result: dict[str, str] = {}

    if include_all:
        full = _fetch_nasdaq_trader()
        if full:
            result.update(full)
        else:
            logger.warning("NASDAQ Trader fetch failed; falling back to index lists")
            include_sp500 = include_nasdaq = include_djia = True

    if not include_all:
        if include_djia:
            result.update(DJIA)

        if include_nasdaq:
            result.update(NASDAQ100)

        if include_sp500:
            # Try 3 sources in order: GitHub CSV → Wikipedia → embedded static
            sp500 = _fetch_sp500_github()
            if not sp500:
                logger.warning("S&P 500 GitHub failed; trying Wikipedia…")
                sp500 = _fetch_sp500_wiki()
            if sp500:
                result.update(sp500)
                logger.info("S&P 500 loaded: %d stocks", len(sp500))
            else:
                logger.warning("S&P 500 all fetches failed; using static fallback")
                result.update(SP500_STATIC)

    logger.info("Total US stocks: %d", len(result))
    return result
