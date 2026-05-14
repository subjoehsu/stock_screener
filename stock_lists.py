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
    TWSE OpenData JSON API — returns all listed stocks for today.
    Works from any server (no HTML/Big5 parsing needed).
    Returns empty dict on non-trading days or failure.
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
                result[code] = name
        return result
    except Exception as exc:
        logger.warning("TWSE JSON API failed: %s", exc)
        return {}


def _fetch_tpex_json() -> dict[str, str]:
    """
    TPEx OpenData JSON API — OTC (上櫃) listed stocks.
    Returns empty dict on failure.
    """
    url = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get(url, timeout=15, headers=headers)
        data = resp.json()
        result: dict[str, str] = {}
        for item in data:
            # Try different possible field names
            code = str(item.get("SecuritiesCompanyCode",
                        item.get("Code", ""))).strip()
            name = str(item.get("CompanyName",
                        item.get("Name", code))).strip()
            if code.isdigit() and not code.startswith("0") and 4 <= len(code) <= 5:
                result[code] = name
        return result
    except Exception as exc:
        logger.warning("TPEx JSON API failed: %s", exc)
        return {}


def fetch_tw_stocks(include_tpex: bool = True) -> dict[str, str]:
    """
    Fetch Taiwan listed stocks.
    Strategy:
      1. Try TWSE JSON OpenData  (works every trading day)
      2. Try TPEx JSON OpenData  (works every trading day)
      3. Merge with static TW_STATIC for any missing stocks
    Returns the most comprehensive list available.
    """
    result: dict[str, str] = {}

    twse = _fetch_twse_json()
    result.update(twse)
    logger.info("TWSE JSON: %d stocks", len(twse))

    if include_tpex:
        tpex = _fetch_tpex_json()
        result.update(tpex)
        logger.info("TPEx JSON: %d stocks", len(tpex))

    # Always merge in static list to fill gaps (non-trading days, etc.)
    for code, name in TW_STATIC.items():
        if code not in result:
            result[code] = name

    logger.info("Total TW stocks: %d", len(result))
    return result


# ─────────────────────────────────────────────────────────
#  US stock fetchers
# ─────────────────────────────────────────────────────────

def _fetch_sp500_wiki() -> dict[str, str]:
    """Fetch S&P 500 from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        tables = pd.read_html(url, attrs={"id": "constituents"})
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


def fetch_us_stocks(
    include_sp500:   bool = True,
    include_nasdaq:  bool = True,
    include_djia:    bool = True,
) -> dict[str, str]:
    """
    Fetch US stocks based on selected indices.
    S&P 500 is fetched dynamically from Wikipedia;
    NASDAQ-100 and DJIA are from static lists.
    """
    result: dict[str, str] = {}

    if include_djia:
        result.update(DJIA)

    if include_nasdaq:
        result.update(NASDAQ100)

    if include_sp500:
        sp500 = _fetch_sp500_wiki()
        if sp500:
            result.update(sp500)
        else:
            # Minimal fallback — static dict already covers most NASDAQ/DJIA
            logger.warning("S&P 500 fallback: using NASDAQ-100 + DJIA only")

    logger.info("Total US stocks: %d", len(result))
    return result
