"""Single catalog for import fields, UI columns and honest source availability."""
from __future__ import annotations

from copy import deepcopy

COMMON = ['code', 'name', 'currency', 'source_name', 'as_of', 'source_url', 'price',
          'price_as_of', 'notes']
NAV = ['nav', 'nav_currency', 'nav_as_of']
DIVIDEND = ['dividend_per_share', 'dividend_currency', 'dividend_period_start',
            'dividend_period_end', 'dividend_basis']
NUMERIC = frozenset({'price', 'nav', 'h_price', 'fx_hkd_cny', 'deal_price',
                     'dividend_per_share', 'rate_pct', 'issue_price', 'pe', 'pb',
                     'change_pct', 'yield_pct', 'income_per_10k'})
LABELS = {
    'code': '代码', 'name': '名称', 'currency': '价格币种', 'source_name': '填写来源',
    'as_of': '资料基准日', 'source_url': '来源链接', 'price': '价格',
    'price_as_of': '价格日期', 'notes': '备注', 'nav': '单位净值',
    'nav_currency': '净值币种', 'nav_as_of': '净值日期', 'h_code': 'H 股代码',
    'h_price': 'H 股价格', 'h_currency': 'H 股币种', 'h_price_as_of': 'H 股日期',
    'fx_hkd_cny': '1 港元折合人民币', 'fx_as_of': '汇率日期',
    'deal_price': '每股现金对价', 'deal_currency': '对价币种', 'deal_as_of': '对价基准日',
    'event_date': '事件日期', 'event_type': '事件类型',
    'dividend_per_share': '所填期间每股现金分红',
    'dividend_currency': '股息币种', 'dividend_period_start': '股息期间开始',
    'dividend_period_end': '股息期间结束', 'dividend_basis': '股息期间口径',
    'rate_pct': '原始利率', 'income_per_10k': '每万份收益',
    'rate_basis': '利率口径', 'maturity_date': '到期日',
    'subscription_status': '申购状态', 'issue_price': '发行价', 'pe': '市盈率',
    'pb': '市净率', 'change_pct': '涨跌幅', 'yield_pct': '导入收益率',
    'yield_basis': '收益率口径', 'nav_premium_pct': '净值溢价率',
    'ah_premium_pct': 'A 股相对 H 股溢价率', 'deal_spread_pct': '对价相对现价空间',
    'dividend_yield_pct': '所填期间股息率',
}
DESCRIPTIONS = {
    'currency': 'CNY/HKD/USD/EUR/JPY/GBP；不自动换汇。',
    'as_of': 'YYYY-MM-DD，用户声明的资料基准日，不代表服务已核验。',
    'source_name': '人工填写的出处，仅供追溯，不作为已核验 API 的证明。',
    'fx_hkd_cny': '人民币/港元；例如 0.88 表示 1 HKD = 0.88 CNY。',
    'dividend_basis': 'trailing_12_months 或 declared_period；不做期间年化。',
    'rate_pct': '百分数值；2.5 表示 2.5%，保持源数据口径，不推算年化。',
    'rate_basis': '仅百分比口径，如七日年化、逆回购报价利率；万份收益填 income_per_10k。',
    'income_per_10k': '所填币种的每一万份收益金额，不是百分比，也不自动换算利率。',
    'event_type': '例如 A股换股、现金要约、中概私有化、港股私有化、供股权；仅作分类。',
    'deal_price': '仅填方案规定的每股现金对价；换股、供股权等非现金对价请留空。',
    'yield_pct': '百分数值；仅导入展示，未计算或验证到期收益率。',
    'deal_spread_pct': '(方案对价 / 现价 - 1) × 100；不代表实现收益。',
}


def _category(key, label, description, extra, columns, notes, sources):
    return dict(id=key, label=label, description=description,
                field_keys=COMMON + extra, column_keys=columns,
                notes=notes, planned_sources=sources, live_status='unavailable')


_NAV_NOTE = '净值溢价率=(价格/单位净值-1)×100；仅同币种、价格日=净值日=资料基准日计算。'
_DISCLOSURE = '候选公开来源只用于下一阶段设计；本版本未接入，不能据此声称已有实时数据。'
_CATEGORIES = [
    _category('arbitrage', '套利股', '事件与方案对价研究',
              ['deal_price', 'deal_currency', 'deal_as_of', 'event_date', 'event_type'],
              ['event_type', 'price', 'deal_price', 'deal_spread_pct', 'event_date'],
              ['对价空间不含税费、交割条件、失败概率或时间价值；不构成可实现收益。',
               '仅对价币种与价格币种一致且对价日=价格日=资料基准日时计算。',
               '当前只计算所填现金对价空间；换股比例、供股权价值与跨境税务引擎待开发。'],
              ['交易所/上市公司公开公告（人工核对）']),
    _category('closed_end', '封闭基金', '封闭期限与净值折溢价', [*NAV, 'maturity_date'],
              ['price', 'nav', 'nav_premium_pct', 'maturity_date'], [_NAV_NOTE],
              ['基金管理人净值公告', '交易所基金行情（待验证授权接口）']),
    _category('etf', 'ETF', '交易价格与单位净值比较', NAV,
              ['price', 'nav', 'nav_premium_pct'],
              [_NAV_NOTE, '净值不等于盘中 IOPV；本版本无申赎清单或套利成交能力。'],
              ['基金管理人净值/PCF 公告', '已配置 provider 的基金行情能力（待验证）']),
    _category('cash', '现金管理', '现金类产品利率与期限记录',
              ['rate_pct', 'rate_basis', 'income_per_10k', 'maturity_date'],
              ['rate_pct', 'rate_basis', 'income_per_10k', 'maturity_date'],
              ['利率仅按填写口径展示，不自动年化；七日年化、万份收益和逆回购报价不可混排。'],
              ['基金管理人收益公告', '交易所逆回购公开信息']),
    _category('reits', 'REITs', '基础设施基金价格与分派研究', DIVIDEND,
              ['price', 'dividend_per_share', 'dividend_yield_pct'],
              ['分派率依赖明确期间和币种；不把资产估值当作每日可赎回净值。'],
              ['基金管理人分派公告', '交易所 REITs 公告']),
    _category('lof', 'LOF', '上市开放式基金折溢价研究', [*NAV, 'subscription_status'],
              ['price', 'nav', 'nav_premium_pct', 'subscription_status'],
              [_NAV_NOTE, '申购状态需人工核验；价格差不等于可完成套利。'],
              ['基金管理人净值/限购公告']),
    _category('ah', 'A/H 比价', '以明确汇率比较两地股价',
              ['h_code', 'h_price', 'h_currency', 'h_price_as_of', 'fx_hkd_cny', 'fx_as_of'],
              ['price', 'h_price', 'fx_hkd_cny', 'ah_premium_pct'],
              ['仅人民币 A 股、港元 H 股；A/H/汇率日期须等于资料基准日。',
               'A/H溢价=(A股价格/(H股价格×每港元人民币汇率)-1)×100；未计税费或可互换性。'],
              ['交易所证券信息', '经授权港股行情', '用户核验的汇率来源']),
    _category('qdii', 'T+0 QDII', '跨境基金日期与溢价研究', [*NAV, 'subscription_status'],
              ['price', 'nav', 'nav_premium_pct', 'subscription_status'],
              [_NAV_NOTE, '海外休市、净值时差和限购需单独核验；类别名称不验证任何标的 T+0 资格。'],
              ['基金管理人净值/限购公告', '交易所交易规则']),
    _category('dividends', '分红', '现金股息与明确期间收益率', [*DIVIDEND, 'event_date'],
              ['price', 'dividend_per_share', 'dividend_yield_pct', 'event_date'],
              ['所填期间股息率=期间每股现金分红/价格×100，不自动年化，不推断未来分红。',
               '必须明确币种、期间开始/结束与口径；滚动12个月要求完整且截至价格日。'],
              ['上市公司分红实施公告', '交易所公告']),
    _category('ipo', '新股', '发行价格与申购事件清单',
              ['issue_price', 'event_date', 'subscription_status'],
              ['issue_price', 'event_date', 'subscription_status'],
              ['事件清单仅依据导入文件；不自动申购，不验证额度或中签结果。'],
              ['交易所发行/上市公告']),
    _category('bonds', '债券', '债券价格、到期与收益率口径',
              ['yield_pct', 'yield_basis', 'maturity_date'],
              ['price', 'yield_pct', 'yield_basis', 'maturity_date'],
              ['收益率仅展示导入值；缺少现金流、净价/全价口径时不计算到期收益率。'],
              ['发行人募集说明书', '交易所债券公告']),
    _category('indices', '指数', '指数估值与变动快照', ['change_pct', 'pe', 'pb'],
              ['price', 'change_pct', 'pe', 'pb'],
              ['指数数值单位为点，不是货币金额；币种字段仅作市场参考，不参与汇率计算。',
               '估值和涨跌幅均为导入口径；不替代主程序四大指数实时展示。'],
              ['指数编制机构公开信息', '既有指数 provider 能力（待验证）']),
]
CATEGORIES = {category['id']: category for category in _CATEGORIES}


def field_metadata(key, category=None):
    field_type = ('number' if key in NUMERIC or key.endswith('_pct')
                  else 'date' if key.endswith('_as_of') or key in {
                      'as_of', 'event_date', 'maturity_date', 'dividend_period_start',
                      'dividend_period_end'} else 'text')
    metadata = dict(key=key, label=LABELS[key], type=field_type,
                    unit='%' if key.endswith('_pct') else None,
                    required=key in {'code', 'name', 'currency', 'source_name', 'as_of'},
                    description=DESCRIPTIONS.get(key))
    if category == 'indices' and key == 'price':
        metadata.update(label='点位', unit='点', description='指数点位，不是货币价格，不作换汇。')
    elif category == 'indices' and key == 'currency':
        metadata.update(label='参考币种（指数点位非金额）',
                        description='仅作市场参考；指数点位不以此币种计价，不参与汇率计算。')
    return metadata


def catalog():
    from app.data_providers.research_market import FILTERS
    categories = []
    for raw in _CATEGORIES:
        item = deepcopy(raw)
        item['fields'] = [field_metadata(key, item['id']) for key in item.pop('field_keys')]
        item['columns'] = [field_metadata(key, item['id']) for key in
                           ['code', 'name', *item.pop('column_keys'), 'currency', 'as_of',
                            'source_name']]
        item['live_status'] = 'available' if item['id'] in FILTERS else 'unavailable'
        item['notes'].append('市场行情按 TickFlow → 扶摇 → 公开补充源（东方财富，异常时备用目录与腾讯报价）尝试；仅集成能力范围内的字段。导入与虚构演示不视为已验证行情。')
        categories.append(item)
    return dict(schema_version=1, categories=categories, existing_modules=[
        dict(label='基金研究', path='/funds'),
        dict(label='可转债工作台', path='/convertibles'),
    ])
