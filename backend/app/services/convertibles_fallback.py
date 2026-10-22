"""Research-only quote fallback and safe initialization of an empty watchlist."""
from contextlib import suppress
from datetime import datetime

from app.data_providers.research_market import (
    LABELS,
    PUBLIC,
    SH,
    EastmoneyMarketProvider,
    ResearchMarketService,
    ResearchSourceError,
    market_batch,
    number,
)
from app.services.convertibles_models import ConvertibleItem
from app.services.convertibles_research import ConvertibleConflictError
from app.services.convertibles_sources import (
    ConvertibleDataError,
    ConvertibleQuote,
    ConvertibleQuoteBatch,
    normalize_symbol,
)


class FallbackConvertibleProvider:
    name = 'tickflow_fuyao_eastmoney'

    def configured(self):
        # This means a provider path exists, not successful network/account verification.
        return True

    def quotes(self, symbols):
        try:
            batch = ResearchMarketService().fetch('quotes', symbols)
        except ResearchSourceError as exc:
            raise ConvertibleDataError(502, str(exc)) from None
        return ConvertibleQuoteBatch(
            {r.symbol: ConvertibleQuote(r.symbol, r.price, r.change_pct, r.amount,
                                       r.turnover_pct, r.quote_at, r.source) for r in batch.rows},
            batch.fetched_at,
        )

    def discover(self, store, expected_revision):
        try:
            batch = market_batch('bonds', force=True)
            # Neither integrated primary API supplies bond -> stock bindings or
            # conversion terms. Fill only that unsupported metadata capability;
            # the primary provider's successful prices and timestamps stay intact.
            metadata = {}
            if any(row.source != PUBLIC for row in batch.rows):
                # Price-only discovery is useful even if reference terms fail.
                with suppress(ResearchSourceError):
                    metadata = {row.symbol: row for row in EastmoneyMarketProvider().market('bonds')}
            items = []
            for row in batch.rows:
                # The public market feed supplies an explicit bond -> stock binding.
                # No binding/terms are inferred from a security's name or neighboring code.
                extra = metadata[row.symbol].extra if row.symbol in metadata else row.extra
                stock_code = extra.get('f232')
                try:
                    stock_code = normalize_symbol(stock_code, kind='stock') if stock_code else None
                except (ConvertibleDataError, AttributeError):
                    stock_code = None
                items.append(ConvertibleItem(
                    code=row.symbol, name=row.name, bond_price=row.price,
                    bond_change_pct=row.change_pct, turnover_amount=row.amount,
                    turnover_rate_pct=row.turnover_pct, stock_code=stock_code,
                    stock_name=extra.get('f234') if stock_code else None,
                    # Current conversion price is a public reference, not an issuer-verified term.
                    conversion_price=number(extra.get('f235'), positive=True),
                    terms_source='东方财富公开参考字段，生效日期及公告未核验' if extra.get('f235') else None,
                    quote_at=row.quote_at, fetched_at=batch.fetched_at, quote_source=row.source,
                    source_url=f'https://quote.eastmoney.com/{row.symbol[-2:].lower()}{row.symbol[:6]}.html'
                    if row.source == PUBLIC else None,
                ))
            # Fetch explicitly bound underlying stocks through the same priority chain.
            stocks = sorted({item.stock_code for item in items if item.stock_code})
            try:
                stock_batch = ResearchMarketService().fetch('quotes', stocks) if stocks else None
            except ResearchSourceError:
                stock_batch = None  # Valid bond quotes remain usable; underlying stays unknown.
            lookup = {row.symbol: row for row in stock_batch.rows} if stock_batch else {}
            for i, item in enumerate(items):
                stock = lookup.get(item.stock_code)
                if stock:
                    items[i] = item.model_copy(update={'stock_price': stock.price,
                        'stock_change_pct': stock.change_pct, 'stock_quote_at': stock.quote_at,
                        'quote_source': f'{item.quote_source} / 正股:{stock.source}'})
            day = max(datetime.fromisoformat(r.quote_at).astimezone(SH).date().isoformat() for r in batch.rows)
            sources = '、'.join(sorted({LABELS.get(r.source, r.source) for r in batch.rows}))
            return store.initialize_market(items, day, sources, expected_revision=expected_revision)
        except ConvertibleConflictError:
            raise
        except ResearchSourceError as exc:
            raise ConvertibleDataError(502, str(exc)) from None
        except ValueError:
            raise ConvertibleDataError(502, '市场清单未通过字段或日期校验，原资料已保留') from None
