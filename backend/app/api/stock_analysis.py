"""个股分析 API — 关键价位 + AI 四维分析 + 报告持久化。

路由前缀: /api/stock-analysis

端点:
  GET  /levels?symbol=         11 类关键价位(图表 markLine 数据源)
  POST /analyze                AI 流式四维分析(NDJSON)
  GET  /reports                历史报告列表
  POST /reports                保存一条报告
  DELETE /reports/{report_id}  删除一条报告
"""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, SecretStr

from app.indicators.levels import compute_levels, summarize_levels
from app.market_time import cn_today
from app.services import stock_reports
from app.services.ndjson_heartbeat import with_heartbeat
from app.services.stock_analysis_series import _build_series
from app.services.stock_analyzer import analyze_stock_stream

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stock-analysis", tags=["stock-analysis"])


@router.get('/international-data')
def international_data(symbol: str, force: bool = False):
    from app.services.international_stocks import snapshot
    try:
        return snapshot(symbol,force=force)
    except ValueError as exc:
        from app.data_providers.research_market import ResearchSourceError
        raise HTTPException(502 if isinstance(exc,ResearchSourceError) else 422,str(exc)) from None


class JapanKeyRequest(BaseModel):
    api_key: SecretStr


@router.get('/japan-source')
def japan_source():
    from app import secrets_store
    return {'configured':bool(secrets_store.get_env_backed_secret('jquants_api_key','JQUANTS_API_KEY')),
            'provider':'J-Quants V2','free_delay_weeks':12}


@router.put('/japan-source')
def set_japan_source(req: JapanKeyRequest):
    from app import secrets_store
    value=req.api_key.get_secret_value().strip()
    if len(value)>4096:
        raise HTTPException(422,'密钥长度异常')
    secrets_store.save({'jquants_api_key':value})
    return japan_source()


@router.get('/hk-data')
def hk_data(symbol: str, force: bool = False):
    from app.services.hk_stock_analysis import snapshot
    try:
        return snapshot(symbol, force=force)
    except ValueError as exc:
        from app.data_providers.research_market import ResearchSourceError
        raise HTTPException(502 if isinstance(exc, ResearchSourceError) else 422, str(exc)) from None


@router.get("/levels")
def get_levels(
    request: Request,
    symbol: str = Query(..., description="标的代码,如 000001.SZ"),
    days: int = Query(120, ge=30, le=500, description="计算样本天数"),
):
    """计算 11 类关键价位(成交密集区压力支撑 / 枢轴点 / 前高前低 /
    布林带 / Keltner短中长 / ATR止损 / 缺口 / 斐波那契 / 整数关口)。

    返回 {levels: {sr, pivot, extreme, boll, keltner_s, keltner_m, keltner_l,
    atr_stop, gap, fib, round}, close, summary, dates, series}。
    前端按 levels 的 key 渲染开关按钮,逐组显隐 markLine / 曲线。
    """
    if not symbol:
        raise HTTPException(400, "symbol 不能为空")

    from app.data_providers.international import is_international
    if is_international(symbol):
        return international_data(symbol)
    from app.services.watchlist_hk import is_hk
    if is_hk(symbol):
        return hk_data(symbol)
    repo = request.app.state.repo
    end = cn_today()
    start = end - timedelta(days=days * 2)
    # 按资产类型分流: ETF/指数走独立 enriched 存储, 股票保持原路径
    df = repo.get_daily_asset(repo.resolve_asset_type(symbol), symbol, start, end)
    if df.is_empty():
        return {"levels": {"sr": [], "pivot": [], "extreme": [],
                           "boll": [], "keltner_s": [], "keltner_m": [], "keltner_l": [],
                           "atr_stop": [], "gap": [], "fib": [], "round": []},
                "close": None, "summary": "无数据", "symbol": symbol,
                "dates": [], "series": {}}

    levels = compute_levels(df)
    close = float(df.tail(1)["close"][0]) if "close" in df.columns else None
    # 日期 + 带状曲线序列(供前端画 Keltner/ATR/布林带曲线)
    dates = df["date"].to_list()
    series = _build_series(df)
    return {
        "levels": levels,
        "close": close,
        "summary": summarize_levels(levels, close),
        "symbol": symbol,
        "dates": [str(d) for d in dates],
        "series": series,
    }


class AnalyzeRequest(BaseModel):
    """AI 个股分析请求。"""
    symbol: str
    focus: str = ""  # 可选:用户追加的分析关注点


@router.post("/analyze")
async def analyze_stock(request: Request, req: AnalyzeRequest):
    """AI 个股四维分析 — NDJSON 流式返回。

    组合 K 线(技术指标)+ 财务表 + 关键价位 → 客观技术分析提示词 →
    流式调用 LLM → 逐 chunk 以 NDJSON 推给前端(每行一个 JSON)。
    """
    if not req.symbol:
        raise HTTPException(400, "symbol 不能为空")

    from app.data_providers.international import is_international
    if is_international(req.symbol):
        from app.services.hk_stock_analysis import analyze_stream
        from app.services.international_stocks import snapshot
        async def foreign_stream():
            async for chunk in with_heartbeat(analyze_stream(req.symbol,req.focus,loader=snapshot)):
                yield chunk+'\n'
        return StreamingResponse(foreign_stream(),media_type='application/x-ndjson',
            headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    from app.services.watchlist_hk import is_hk
    if is_hk(req.symbol):
        from app.services.hk_stock_analysis import analyze_stream
        async def hk_stream():
            async for chunk in with_heartbeat(analyze_stream(req.symbol, req.focus)):
                yield chunk + '\n'
        return StreamingResponse(hk_stream(), media_type='application/x-ndjson',
            headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    repo = request.app.state.repo
    data_dir = repo.store.data_dir

    async def stream_gen():
        async for chunk in with_heartbeat(analyze_stock_stream(repo, data_dir, req.symbol, req.focus)):
            yield chunk + "\n"

    return StreamingResponse(
        stream_gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ================================================================
# 报告 CRUD(历史报告持久化)
# ================================================================

class SaveReportRequest(BaseModel):
    """保存一条 AI 个股分析报告。"""
    symbol: str
    name: str = ""
    focus: str = ""
    content: str
    summary: str = ""
    close: float | None = None
    levels: dict | None = None


@router.get("/reports")
def list_reports(request: Request):
    """获取全部历史报告(按时间降序,后端已裁剪到上限)。"""
    return {"reports": stock_reports.list_reports()}


@router.post("/reports")
def save_report(request: Request, req: SaveReportRequest):
    """保存一条报告。"""
    report = stock_reports.save_report({
        "symbol": req.symbol,
        "name": req.name,
        "focus": req.focus,
        "content": req.content,
        "summary": req.summary,
        "close": req.close,
        "levels": req.levels,
    })
    return {"ok": True, "report": report}


@router.delete("/reports/{report_id}")
def delete_report(request: Request, report_id: str):
    """删除一条报告。"""
    ok = stock_reports.delete_report(report_id)
    return {"ok": ok}
