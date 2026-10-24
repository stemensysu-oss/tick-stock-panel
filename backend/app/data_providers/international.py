"""International daily contracts, isolated from mainland storage and trading rules."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.data_providers.research_market import ResearchSourceError, number

NAMES = {
    "AAPL.US": "Apple 苹果",
    "MSFT.US": "Microsoft 微软",
    "NVDA.US": "NVIDIA 英伟达",
    "7203.JP": "トヨタ自動車 丰田汽车",
    "6758.JP": "ソニーグループ 索尼",
}


def normalize(value):
    value = value.strip().upper()
    aliases = {
        "苹果": "AAPL.US",
        "APPLE": "AAPL.US",
        "丰田": "7203.JP",
        "丰田汽车": "7203.JP",
        "TOYOTA": "7203.JP",
    }
    value = aliases.get(value, value)
    if re.fullmatch(r"\d{4}(?:\.T|\.JP)?", value):
        return value[:4] + ".JP"
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}(?:\.US)?", value):
        return value if value.endswith(".US") else value + ".US"
    raise ValueError("请输入美股代码（AAPL.US）或四位日股代码（7203.JP）")


def is_international(symbol):
    return isinstance(symbol, str) and bool(
        re.fullmatch(r"(?:[A-Z][A-Z0-9.-]{0,14}\.US|\d{4}\.JP)", symbol)
    )


def market(symbol):
    if not is_international(symbol):
        raise ValueError("无效的国际证券代码")
    return (
        ("us", "USD", "America/New_York") if symbol.endswith(".US") else ("jp", "JPY", "Asia/Tokyo")
    )


def validate(rows, symbol):
    zone = ZoneInfo(market(symbol)[2])
    today = datetime.now(zone).date()
    seen, output = set(), []
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ResearchSourceError("国际日K为空或条数异常")
    for row in rows:
        day = date.fromisoformat(row["date"])
        if day in seen or day > today:
            raise ResearchSourceError("日K存在重复或未来交易日期")
        seen.add(day)
        prices = {k: number(row.get(k), positive=True) for k in ("open", "high", "low", "close")}
        if (
            any(v is None for v in prices.values())
            or prices["low"] > min(prices["open"], prices["close"])
            or prices["high"] < max(prices["open"], prices["close"])
        ):
            raise ResearchSourceError("国际日K价格关系异常")
        volume = number(row.get("volume"))
        if volume is not None and volume < 0:
            raise ResearchSourceError("国际成交量异常")
        if day < today:
            output.append(dict(symbol=symbol, date=day.isoformat(), **prices, volume=volume))
    output.sort(key=lambda r: r["date"])
    if len(output) < 30:
        raise ResearchSourceError("已完成日K不足30条，不能生成分析")
    return output


class TickflowDaily:
    def __init__(self, public=False):
        self.public = public
        self.name = "tickflow_public" if public else "tickflow"

    def fetch(self, symbol):
        if market(symbol)[0] != "us":
            raise NotImplementedError
        from tickflow import TickFlow

        from app import secrets_store
        from app.config import settings

        key = secrets_store.get_tickflow_key()
        if not self.public and not key:
            raise PermissionError
        # Explicit empty key prevents the SDK inheriting unrelated environment credentials.
        client = TickFlow(
            api_key="" if self.public else key,
            base_url="https://free-api.tickflow.org"
            if self.public
            else (secrets_store.load().get("tickflow_base_url") or "https://api.tickflow.org"),
            timeout=12,
            max_retries=0,
            cache_dir=str(settings.data_dir / "cache/international"),
        )
        try:
            data = client.klines.get(symbol, period="1d", count=320, adjust="none")
        finally:
            client.close()
        fields = ("timestamp", "open", "high", "low", "close", "volume")
        if not isinstance(data, dict) or any(not isinstance(data.get(k), list) for k in fields):
            raise ResearchSourceError("主API日K格式异常")
        if len({len(data[k]) for k in fields}) != 1:
            raise ResearchSourceError("日K列长度不一致")
        zone = ZoneInfo(market(symbol)[2])
        rows = []
        for i, stamp in enumerate(data["timestamp"]):
            if (
                isinstance(stamp, bool)
                or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp)
            ):
                raise ResearchSourceError("日K时间异常")
            rows.append(
                dict(
                    date=datetime.fromtimestamp(stamp / 1000, zone).date().isoformat(),
                    **{k: data[k][i] for k in fields[1:]},
                )
            )
        return validate(rows, symbol)


class FuyaoDaily:
    name = "fuyao"

    def fetch(self, symbol):
        # No published US/JP historical contract: never guess mainland-style paths.
        raise NotImplementedError


class JQuantsDaily:
    name = "jquants"

    def fetch(self, symbol):
        if market(symbol)[0] != "jp":
            raise NotImplementedError
        import httpx

        from app import secrets_store

        key = secrets_store.get_env_backed_secret("jquants_api_key", "JQUANTS_API_KEY")
        if not key:
            raise PermissionError
        rows = []
        params = {"code": symbol[:4]}
        with httpx.Client(timeout=12, follow_redirects=False, trust_env=False) as client:
            for _ in range(8):
                response = client.get(
                    "https://api.jquants.com/v2/equities/bars/daily",
                    params=params,
                    headers={"x-api-key": key},
                )
                response.raise_for_status()
                data = response.json()
                for item in data.get("data", []):
                    if str(item.get("Code")) not in {symbol[:4], symbol[:4] + "0"}:
                        raise ResearchSourceError("日股响应代码不一致")
                    rows.append(
                        dict(
                            date=item["Date"],
                            open=item.get("O"),
                            high=item.get("H"),
                            low=item.get("L"),
                            close=item.get("C"),
                            volume=item.get("Vo"),
                        )
                    )
                token = data.get("pagination_key")
                if not token:
                    break
                params["pagination_key"] = token
            else:
                raise ResearchSourceError("日股响应分页超限")
        return validate(rows[-320:], symbol)


class YahooDaily:
    """Global public chart, not Yahoo Japan; no login, tokens or access-control bypass."""

    name = "yahoo_public"

    def fetch(self, symbol):
        if market(symbol)[0] != "jp":
            raise NotImplementedError
        from app.data_providers.research_market import PublicHTTP

        code = symbol[:4] + ".T"
        payload = (
            PublicHTTP()
            .get(
                "https://query1.finance.yahoo.com/v8/finance/chart/" + code,
                {"range": "1y", "interval": "1d"},
            )
            .json()
        )
        chart = payload.get("chart") or {}
        if (
            chart.get("error")
            or not isinstance(chart.get("result"), list)
            or len(chart["result"]) != 1
        ):
            raise ResearchSourceError("日股公开图表为空")
        data = chart["result"][0]
        info = data.get("meta") or {}
        if (
            info.get("symbol") != code
            or info.get("currency") != "JPY"
            or info.get("exchangeTimezoneName") != "Asia/Tokyo"
            or info.get("exchangeName") not in {"JPX", "TYO"}
            or info.get("instrumentType") != "EQUITY"
        ):
            raise ResearchSourceError("日股公开图表市场、币种或证券身份异常")
        quote = (data.get("indicators") or {}).get("quote")
        stamps = data.get("timestamp")
        if not isinstance(quote, list) or len(quote) != 1 or not isinstance(stamps, list):
            raise ResearchSourceError("日股图表格式异常")
        fields = quote[0]
        if any(
            not isinstance(fields.get(k), list) or len(fields[k]) != len(stamps)
            for k in ("open", "high", "low", "close", "volume")
        ):
            raise ResearchSourceError("日股图表列长度不一致")
        rows = []
        for i, stamp in enumerate(stamps):
            values = {k: fields[k][i] for k in ("open", "high", "low", "close", "volume")}
            if all(values[k] is None for k in ("open", "high", "low", "close")):
                continue
            day = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Tokyo")).date().isoformat()
            rows.append(dict(date=day, **values))
        stamp = number(info.get("regularMarketTime"), positive=True)
        price = number(info.get("regularMarketPrice"), positive=True)
        if stamp is None or price is None:
            raise ResearchSourceError("日股快照缺失价格或时点")
        quote_at = datetime.fromtimestamp(stamp, ZoneInfo("Asia/Tokyo"))
        if quote_at > datetime.now(quote_at.tzinfo):
            raise ResearchSourceError("日股报价时点异常")
        self.metadata = dict(
            currency="JPY",
            timezone="Asia/Tokyo",
            name=info.get("longName") or code,
            quote_at=quote_at.isoformat(timespec="seconds"),
            price=price,
            delay_minutes=20,
        )
        return validate(rows, symbol)


def fetch_daily(symbol, providers=None):
    market(symbol)
    attempts = []
    chain = (
        providers
        if providers is not None
        else [
            TickflowDaily(),
            FuyaoDaily(),
            TickflowDaily(public=True) if symbol.endswith(".US") else JQuantsDaily(),
            *([] if symbol.endswith(".US") else [YahooDaily()]),
        ]
    )
    for provider in chain:
        try:
            rows = provider.fetch(symbol)
            if not rows:
                raise ResearchSourceError("日K为空")
            attempts.append(dict(provider=provider.name, status="success", rows=len(rows)))
            return dict(
                rows=rows,
                source=provider.name,
                attempts=attempts,
                price_basis="source_unspecified"
                if provider.name == "yahoo_public"
                else "unadjusted",
                metadata=getattr(provider, "metadata", {}),
            )
        except PermissionError:
            status = "unconfigured"
        except NotImplementedError:
            status = "unsupported"
        except Exception:  # noqa: BLE001 -- isolate providers and never expose credential-bearing errors
            status = "failed"
        attempts.append(dict(provider=provider.name, status=status))
    raise ResearchSourceError(
        "原API与公开补充源暂未返回有效国际日K；原资料保留。也可配置个人J-Quants日股源。"
    )


def search(query, limit=10):
    try:
        symbol = normalize(query)
    except ValueError:
        return {"results": []}
    if symbol in NAMES or symbol.endswith(".US"):
        if symbol not in NAMES:
            # Validate arbitrary US symbols against provider metadata; no invented securities.
            from tickflow import TickFlow

            from app.config import settings

            client = TickFlow(
                api_key="",
                base_url="https://free-api.tickflow.org",
                timeout=8,
                max_retries=0,
                cache_dir=str(settings.data_dir / "cache/international"),
            )
            try:
                info = client.instruments.get(symbol)
            except Exception:  # noqa: BLE001 -- isolate providers and never expose credential-bearing errors
                return {"results": []}
            finally:
                client.close()
            if not info or info.get("symbol") != symbol or info.get("region") != "US":
                return {"results": []}
            name = info.get("name") or symbol
        else:
            name = NAMES[symbol]
        kind, currency, _ = market(symbol)
        return {
            "results": [
                dict(
                    symbol=symbol,
                    code=symbol.rsplit(".", 1)[0],
                    name=name,
                    asset_type=kind,
                    currency=currency,
                    metadata_source="directory",
                    data_status="historical",
                )
            ][:limit]
        }
    return {"results": [], "warnings": ["日股目前支持7203丰田、6758索尼；行情需个人J-Quants密钥。"]}


def paid_quote(symbol):
    """Only the documented US quote contract; failures preserve dated history."""
    if market(symbol)[0] != "us":
        return None
    from tickflow import TickFlow

    from app import secrets_store

    key = secrets_store.get_tickflow_key()
    if not key:
        return None
    try:
        with TickFlow(
            api_key=key,
            base_url=secrets_store.load().get("tickflow_base_url") or "https://api.tickflow.org",
            timeout=8,
            max_retries=0,
        ) as client:
            quotes = client.quotes.get(symbols=[symbol])
        row = next(q for q in quotes if q.get("symbol") == symbol)
        price = number(row.get("last_price"), positive=True)
        stamp = number(row.get("timestamp"), positive=True)
        if price is None or stamp is None or row.get("currency") not in {None, "USD"}:
            return None
        moment = datetime.fromtimestamp(stamp / 1000, ZoneInfo("America/New_York"))
        if moment > datetime.now(moment.tzinfo):
            return None
        return dict(
            symbol=symbol,
            name=NAMES.get(symbol, symbol),
            asset_type="us",
            currency="USD",
            close=price,
            change_pct=None,
            quote_at=moment.isoformat(timespec="seconds"),
            quote_source="TickFlow",
            quote_status="source_timestamp",
            quote_warnings=[
                "账户API返回的价格快照，以所列美国当地时点为准；不保证实时性。",
                "日K与关键价位仍以已完成日线为准，盘前盘后报价不写入历史日K。",
            ],
        )
    except Exception:  # noqa: BLE001 -- never expose authentication-bearing exceptions
        return None
