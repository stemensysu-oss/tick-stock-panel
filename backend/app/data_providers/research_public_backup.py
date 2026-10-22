"""Public supplement redundancy: disclosed catalogs plus timestamped Tencent quotes.

Price fallback runs after both primary APIs and the Eastmoney quote endpoint fail.
Missing primary HK currency metadata may be supplemented independently while
retaining the primary price and time. No authenticated pages, JavaScript evaluation, fabricated dates or par-value fills.
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

# 2026-10-22 Sina turnover directory; codes only, no cached prices.
HK_DIRECTORY_SNAPSHOT_DATE = '2026-10-22'
HK_DIRECTORY_SNAPSHOT = (
    '00700.HK', '09988.HK', '00981.HK', '00992.HK', '00883.HK', '01810.HK', '02513.HK', '03750.HK',
    '06869.HK', '02269.HK', '03690.HK', '01888.HK', '00939.HK', '01211.HK', '01347.HK', '01299.HK',
    '09992.HK', '02359.HK', '01548.HK', '09926.HK', '00388.HK', '00941.HK', '03308.HK', '01024.HK',
    '01398.HK', '01801.HK', '02318.HK', '00100.HK', '02259.HK', '02628.HK', '02020.HK', '09999.HK',
    '00005.HK', '02899.HK', '01196.HK', '02476.HK', '00325.HK', '00148.HK', '06681.HK', '03988.HK',
    '01088.HK', '09888.HK', '03993.HK', '09618.HK', '00857.HK', '06166.HK', '01093.HK', '09660.HK',
    '09961.HK', '03696.HK', '06160.HK', '01378.HK', '02268.HK', '00027.HK', '01288.HK', '02319.HK',
    '06809.HK', '01109.HK', '00175.HK', '01208.HK', '03986.HK', '06082.HK', '00386.HK', '06651.HK',
    '09868.HK', '03968.HK', '02328.HK', '02388.HK', '02382.HK', '03692.HK', '01336.HK', '03606.HK',
    '01772.HK', '02601.HK', '09903.HK', '01818.HK', '02600.HK', '01138.HK', '09880.HK', '00568.HK',
    '00020.HK', '00669.HK', '00001.HK', '01177.HK', '01928.HK', '00728.HK', '00300.HK', '06618.HK',
    '01787.HK', '02335.HK', '00522.HK', '03939.HK', '02015.HK', '00268.HK', '00358.HK', '02313.HK',
    '00016.HK', '01530.HK', '00012.HK', '01898.HK', '02525.HK', '00585.HK', '00002.HK', '01339.HK',
    '02099.HK', '09987.HK', '00622.HK', '01585.HK', '03330.HK', '06990.HK', '03759.HK', '01919.HK',
    '09626.HK', '02692.HK', '03228.HK', '01658.HK', '02228.HK', '01171.HK', '02338.HK', '01952.HK',
    '01308.HK', '02057.HK', '02423.HK', '06181.HK', '06030.HK', '01797.HK', '06690.HK', '02162.HK',
    '00068.HK', '01816.HK', '02715.HK', '00960.HK', '01258.HK', '00688.HK', '00288.HK', '00285.HK',
    '00291.HK', '06951.HK', '01519.HK', '00763.HK', '02367.HK', '06613.HK', '01276.HK', '01929.HK',
    '09863.HK', '03908.HK', '01918.HK', '00241.HK', '06127.HK', '02475.HK', '01729.HK', '03896.HK',
    '02050.HK', '09901.HK', '00772.HK', '03396.HK', '00189.HK', '02595.HK', '03808.HK', '01357.HK',
    '06886.HK', '09606.HK', '00267.HK', '00998.HK', '03888.HK', '02672.HK', '01384.HK', '02142.HK',
    '09678.HK', '09633.HK', '01988.HK', '02333.HK', '00390.HK', '01989.HK', '09995.HK', '00817.HK',
    '06821.HK', '01070.HK', '02577.HK', '00316.HK', '06693.HK', '03277.HK', '02477.HK', '02245.HK',
    '03328.HK', '00136.HK', '00836.HK', '02788.HK', '00788.HK', '00762.HK', '02018.HK', '02556.HK',
    '01735.HK', '06881.HK', '06862.HK', '00322.HK', '00168.HK', '02865.HK', '02888.HK', '02697.HK',
    '03317.HK', '09976.HK', '03900.HK', '02331.HK', '01209.HK', '02343.HK', '03800.HK', '02631.HK',
    '00780.HK', '02618.HK', '01113.HK', '00003.HK', '01766.HK', '00013.HK', '00966.HK', '09698.HK',
    '09630.HK', '06682.HK', '09696.HK', '09866.HK', '09856.HK', '03200.HK', '06658.HK', '00293.HK',
    '02661.HK', '09927.HK', '03933.HK', '03931.HK', '03858.HK', '01044.HK', '00553.HK', '01392.HK',
    '02611.HK', '06106.HK', '03311.HK', '01768.HK', '06088.HK', '02007.HK', '00006.HK', '07666.HK',
    '03323.HK', '06185.HK', '01860.HK', '09896.HK', '09858.HK', '02315.HK', '09973.HK', '09688.HK',
    '02650.HK', '01913.HK', '06810.HK', '00101.HK', '01038.HK', '00019.HK', '01364.HK', '00914.HK',
    '06066.HK', '01879.HK', '06855.HK', '02097.HK', '00902.HK', '02498.HK', '09887.HK', '02386.HK',
    '00083.HK', '00470.HK', '00008.HK', '00753.HK', '01114.HK', '06055.HK', '02688.HK', '02670.HK',
    '00916.HK', '01164.HK', '09969.HK', '03288.HK', '00270.HK', '00066.HK', '01112.HK', '06060.HK',
    '06675.HK', '00340.HK', '01997.HK', '00425.HK', '00376.HK', '02186.HK', '02208.HK', '00501.HK',
    '02028.HK', '01099.HK', '02400.HK', '01133.HK', '03898.HK', '00384.HK', '00968.HK', '00867.HK',
    '09911.HK', '00991.HK', '02202.HK', '01359.HK', '02685.HK', '01428.HK', '01753.HK', '01191.HK',
    '01908.HK', '02196.HK', '01318.HK', '01072.HK', '01788.HK', '01776.HK', '00144.HK', '02285.HK',
    '02714.HK', '02635.HK', '02947.HK', '02656.HK', '06818.HK', '06969.HK', '02357.HK', '00081.HK',
    '00805.HK', '03668.HK', '01396.HK', '00696.HK', '02272.HK', '06936.HK', '02883.HK', '02096.HK',
    '03347.HK', '00699.HK', '01385.HK', '06656.HK', '03388.HK', '00023.HK', '00631.HK', '00179.HK',
    '06186.HK', '01651.HK', '01071.HK', '07630.HK', '06049.HK', '09980.HK', '01081.HK', '02238.HK',
    '00220.HK', '00017.HK', '03320.HK', '06031.HK', '01579.HK', '02362.HK', '03661.HK', '00576.HK',
    '00326.HK', '07687.HK', '02706.HK', '03306.HK', '02157.HK', '00354.HK', '03618.HK', '00868.HK',
    '02689.HK', '06099.HK', '06823.HK', '03360.HK', '00135.HK', '00625.HK', '01866.HK', '01876.HK',
    '00165.HK', '00317.HK', '02696.HK', '02617.HK', '00586.HK', '01783.HK', '03738.HK', '09899.HK',
    '03393.HK', '01800.HK', '00371.HK', '01060.HK', '02380.HK', '01302.HK', '01186.HK', '03310.HK',
    '03339.HK', '00551.HK', '02553.HK', '06963.HK', '02232.HK', '01681.HK', '03223.HK', '03998.HK',
    '02586.HK', '03296.HK', '01833.HK', '01055.HK', '01128.HK', '06680.HK', '01972.HK', '02636.HK',
    '02419.HK', '01066.HK', '01882.HK', '03958.HK', '02699.HK', '02718.HK', '02510.HK', '01333.HK',
    '01698.HK', '02768.HK', '02276.HK', '02588.HK', '02698.HK', '00826.HK', '02727.HK', '06666.HK',
    '01609.HK', '02616.HK', '02889.HK', '06098.HK', '00303.HK', '02432.HK', '01910.HK', '06655.HK',
    '01179.HK', '01566.HK', '09993.HK', '01415.HK', '02858.HK', '02233.HK', '02590.HK', '00038.HK',
    '03757.HK', '00512.HK', '01511.HK', '02473.HK', '01377.HK', '02580.HK', '01896.HK', '03698.HK',
    '00297.HK', '01688.HK', '00142.HK', '01157.HK', '00152.HK', '02583.HK', '02533.HK', '02465.HK',
    '02799.HK', '00956.HK', '06880.HK', '00945.HK', '06865.HK', '06806.HK', '02356.HK', '01030.HK',
    '01880.HK', '09637.HK', '06731.HK', '01440.HK', '00095.HK', '02666.HK', '00639.HK', '00392.HK',
    '06078.HK', '03877.HK', '00819.HK', '06069.HK', '03996.HK', '02013.HK', '03268.HK', '01779.HK',
    '01277.HK', '00881.HK', '00874.HK', '02442.HK', '00123.HK', '00570.HK', '06979.HK', '06090.HK',
    '02282.HK', '00467.HK', '01368.HK', '02155.HK', '02171.HK', '00667.HK', '07688.HK', '00659.HK',
    '00565.HK', '00552.HK', '03774.HK', '01193.HK', '00999.HK', '01686.HK', '00177.HK', '00598.HK',
    '00670.HK', '00119.HK', '00151.HK', '00638.HK',
)


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
        try:
            return self._live_catalog(node)
        except (ResearchSourceError, ValueError, TypeError, KeyError):
            from app.data_providers.research_reference_catalog import CATALOGS, SNAPSHOT_DATE

            if node not in CATALOGS:
                raise
            self.coverage_notes.append(
                f'在线目录读取失败，使用 {SNAPSHOT_DATE} 公开目录快照；可能缺少新上市品种。价格仍由腾讯接口当次获取，并非目录内的旧价格。')
            return list(CATALOGS[node])

    def _live_catalog(self, node):
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

    def hk_catalog(self):
        try:
            return self._live_hk_catalog()
        except (ResearchSourceError, ValueError, TypeError, KeyError):
            self.coverage_notes.append(
                f'在线港股目录失败，使用 {HK_DIRECTORY_SNAPSHOT_DATE} 公开成交额前 500 只代码快照；可能缺少新上市或活跃品种。'
                '所有展示价格仍由腾讯当次获取，公开报价通常延迟约 15 分钟，币种按来源明确 HKD。')
            return list(HK_DIRECTORY_SNAPSHOT)

    def _live_hk_catalog(self):
        """Bounded live directory, never a scan of guessed five-digit codes."""
        output = []
        for page in range(1, 10):
            rows = self.http.get(SINA + 'Market_Center.getHKStockData', {
                'page': page, 'num': 60, 'sort': 'amount', 'asc': 0, 'node': 'qbgg_hk',
            }).json()
            if not isinstance(rows, list):
                raise ResearchSourceError('公开港股目录格式异常')
            output.extend(f"{r['symbol']}.HK" for r in rows
                          if isinstance(r, dict) and re.fullmatch(r'\d{5}', r.get('symbol', '')))
            if len(rows) < 60:
                break
        if not output:
            raise ResearchSourceError('公开港股目录为空')
        # Turnover changes while pages are fetched. Deduplicate boundary moves
        # rather than discarding all valid securities or using guessed codes.
        output = list(dict.fromkeys(output))[:500]
        self.coverage_notes.append(
            '港股仅展示公开目录按成交额排序的前 500 只中取得有效港元报价的记录，非全港股；'
            '公开报价通常延迟约 15 分钟，以来源时间为准。人民币及其他币种柜台未混入。')
        return output

    def quotes(self, symbols):
        requested = set(symbols)
        output = []
        invalid = 0
        for offset in range(0, len(symbols), 50):
            codes = [('hk' + s[:5] if s.endswith('.HK') else s[-2:].lower() + s[:6])
                     for s in symbols[offset:offset + 50]
                     if re.fullmatch(r'(?:\d{6}\.(SH|SZ)|\d{5}\.HK)', s)]
            if not codes:
                continue
            response = self.http.get('https://qt.gtimg.cn/q=' + ','.join(codes))
            # The feed is GBK. Decode explicitly instead of replacing Chinese names.
            body = response.content.decode('gb18030')
            for match in re.finditer(r'v_((?:(?:sh|sz)\d{6}|hk\d{5}))="([^"\r\n]*)";', body):
                symbol = f'{match[1][2:]}.{match[1][:2].upper()}'
                hk = symbol.endswith('.HK')
                fields = match[2].split('~')
                if symbol not in requested or len(fields) < 33 or fields[2] != symbol.split('.')[0]:
                    continue
                stamp_format = '%Y/%m/%d %H:%M:%S' if hk else '%Y%m%d%H%M%S'
                if hk and (len(fields) <= 75 or fields[75] != 'HKD'):
                    continue  # HK also has RMB/USD counters; currency must be explicit.
                if not hk and not re.fullmatch(r'\d{14}', fields[30]):
                    continue  # No date -> no quote; never attach today's date to ticktime.
                try:
                    dt = datetime.strptime(fields[30], stamp_format).replace(tzinfo=SH)
                    when = quote_time(dt.timestamp())
                    price = number(fields[3], positive=True)
                    if price is None:
                        continue
                    output.append(MarketRow(symbol, fields[1], price, when, TENCENT,
                                            number(fields[32]), extra=({'currency': 'HKD',
                                                'quote_delay_note': '港股公开报价通常延迟约 15 分钟，以来源时间为准。'} if hk else {})))
                except (ResearchSourceError, ValueError, OverflowError):
                    invalid += 1  # One malformed security must not blank the whole market.
        if invalid:
            self.coverage_notes.append(f'{invalid} 条报价的时间或数值异常，已排除，未使用默认值补齐。')
        return output

    def market(self, category):
        metadata = {}
        if category == 'hk':
            symbols = self.hk_catalog()
        elif category == 'bonds':
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
        rows = [replace(row, extra={**row.extra, **metadata.get(row.symbol, {}),
                                   'coverage_note': '；'.join(self.coverage_notes)}) for row in self.quotes(symbols)
                if datetime.fromisoformat(row.quote_at) >= recent]
        return rows
