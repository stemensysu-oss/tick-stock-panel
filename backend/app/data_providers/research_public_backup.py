"""Public supplement redundancy: disclosed catalogs plus timestamped Tencent quotes.

Invoked only after the two primary APIs and the Eastmoney quote endpoint fail.
No authenticated pages, JavaScript evaluation, fabricated dates or par-value fills.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta

from app.data_providers.research_market import (
    SH,
    MarketRow,
    PublicHTTP,
    ResearchSourceError,
    number,
    quote_time,
)

TENCENT = 'tencent_public'
SINA = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'


def bond_metadata(http=None):
    """Explicit bond/stock binding and reference terms, never a quote timestamp."""
    http = http or PublicHTTP()
    result = {}
    for page in range(1, 6):
        payload = http.get('https://datacenter-web.eastmoney.com/api/data/v1/get', {
            'reportName': 'RPT_BOND_CB_LIST', 'columns': 'ALL', 'pageSize': 500,
            'pageNumber': page, 'sortColumns': 'PUBLIC_START_DATE', 'sortTypes': '-1',
            'quoteColumns': 'f235~10~SECURITY_CODE~TRANSFER_PRICE',
            'source': 'WEB', 'client': 'WEB',
        }).json()
        data = payload.get('result') or {}
        rows, pages = data.get('data'), int(data.get('pages') or 0)
        if not isinstance(rows, list) or not 1 <= pages <= 5:
            raise ResearchSourceError('公开债券资料分页异常')
        today = datetime.now(SH).date().isoformat()
        for row in rows:
            symbol = row.get('SECUCODE', '')
            # Exclude unlisted, delisted and matured records from discovery.
            if (not re.fullmatch(r'\d{6}\.(SH|SZ)', symbol) or row.get('DELIST_DATE')
                    or not row.get('LISTING_DATE') or row['LISTING_DATE'][:10] > today
                    or (row.get('EXPIRE_DATE') and row['EXPIRE_DATE'][:10] < today)):
                continue
            result[symbol] = {'f232': row.get('CONVERT_STOCK_CODE'), 'f234': None,
                              'f235': row.get('TRANSFER_PRICE')}
        if page == pages:
            return result
    raise ResearchSourceError('公开债券资料分页超限')


class PublicBackupProvider:
    name = 'sina_tencent_public'

    def __init__(self, http=None):
        self.http = http or PublicHTTP()
        self.coverage_notes = []

    def _catalog(self, node):
        raw_count = self.http.get(SINA + 'Market_Center.getHQNodeStockCount', {'node': node}).json()
        count = int(raw_count)
        if not 0 < count <= 2500:
            raise ResearchSourceError('公开证券目录为空或超限')
        output = []
        for page in range(1, 33):
            rows = self.http.get(SINA + 'Market_Center.getHQNodeData', {
                'page': page, 'num': 80, 'sort': 'symbol', 'asc': 1, 'node': node,
            }).json()
            if not isinstance(rows, list):
                raise ResearchSourceError('公开证券目录格式异常')
            output.extend(rows)
            if len(rows) < 80 or len(output) >= count:
                break
        if not output or len({row.get('symbol') for row in output}) != len(output):
            raise ResearchSourceError('公开证券目录为空或重复')
        if len(output) != count:
            self.coverage_notes.append(f'备用目录实际返回 {len(output)} 条，与其数量接口的 {count} 条不一致；仅展示取得有效报价的记录，不保证全量覆盖。')
        return [f'{row["symbol"][2:]}.{row["symbol"][:2].upper()}' for row in output
                if re.fullmatch(r'(sh|sz)\d{6}', row.get('symbol', ''))]

    def quotes(self, symbols):
        requested = set(symbols)
        output = []
        for offset in range(0, len(symbols), 50):
            codes = [s[-2:].lower() + s[:6] for s in symbols[offset:offset + 50]
                     if re.fullmatch(r'\d{6}\.(SH|SZ)', s)]
            if not codes:
                continue
            response = self.http.get('https://qt.gtimg.cn/q=' + ','.join(codes))
            # The feed is GBK. Decode explicitly instead of replacing Chinese names.
            body = response.content.decode('gb18030')
            for match in re.finditer(r'v_((?:sh|sz)\d{6})="([^"\r\n]*)";', body):
                symbol = f'{match[1][2:]}.{match[1][:2].upper()}'
                fields = match[2].split('~')
                if symbol not in requested or len(fields) < 33 or fields[2] != symbol[:6]:
                    continue
                if not re.fullmatch(r'\d{14}', fields[30]):
                    continue  # No date -> no quote; never attach today's date to ticktime.
                dt = datetime.strptime(fields[30], '%Y%m%d%H%M%S').replace(tzinfo=SH)
                when = quote_time(dt.timestamp())
                price = number(fields[3], positive=True)
                if price is None:
                    continue
                output.append(MarketRow(symbol, fields[1], price, when, TENCENT,
                                        number(fields[32])))
        return output

    def market(self, category):
        metadata = {}
        if category == 'bonds':
            metadata = bond_metadata(self.http)
            symbols = sorted(metadata)
        elif category in {'etf', 'lof'}:
            symbols = self._catalog('etf_hq_fund' if category == 'etf' else 'lof_hq_fund')
        elif category == 'reits':
            # The Sina closed-fund directory is broader than REITs; use only
            # the exchanges' dedicated infrastructure fund code families.
            symbols = [s for s in self._catalog('close_fund')
                       if re.fullmatch(r'(?:508\d{3}\.SH|180\d{3}\.SZ)', s)]
        elif category == 'cash':
            # Explicit representative instruments, not an invented full market.
            symbols = ['159001.SZ', '511880.SH']
        elif category == 'indices':
            symbols = ['000001.SH', '399001.SZ', '399006.SZ', '000300.SH', '000905.SH', '000016.SH']
        else:
            raise NotImplementedError
        recent = datetime.now(SH) - timedelta(days=30)
        rows = [replace(row, extra={**metadata.get(row.symbol, {}),
                                   'coverage_note': '；'.join(self.coverage_notes)}) for row in self.quotes(symbols)
                if datetime.fromisoformat(row.quote_at) >= recent]
        return rows
