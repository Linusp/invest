from datetime import date
from decimal import Decimal

from invest_service.models import AssetCategory, ExchangeRate, MarketBar, asset_identity
from invest_service.services import MarketService


def _create_strategy_and_asset(client):
    client.get("/api/v1/assets/search", params={"q": "600000"})
    with client.app.state.session_factory() as session:
        MarketService(session, client.app.state.market_provider).sync_asset(
            "600000.SH",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 13),
        )
    response = client.post(
        "/api/v1/strategies",
        json={"name": "银行价值", "description": "测试策略"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _add_trade(client, strategy_id, **values):
    payload = {
        "type": values.pop("type"),
        "trade_date": values.pop("trade_date"),
        "price": values.pop("price"),
        **values,
    }
    return client.post(f"/api/v1/strategies/{strategy_id}/trades", json=payload)


def test_strategy_detail_trades_positions_and_profit(client):
    strategy_id = _create_strategy_and_asset(client)
    assert (
        _add_trade(
            client,
            strategy_id,
            type="deposit",
            trade_date="2026-07-01",
            price=10000,
            idempotency_key="deposit-1",
        ).status_code
        == 201
    )
    buy = _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-02",
        asset_symbol="600000.SH",
        price=100,
        quantity=10,
        fee=5,
        idempotency_key="buy-1",
    )
    assert buy.status_code == 201

    duplicate = _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-02",
        asset_symbol="600000.SH",
        price=100,
        quantity=10,
        fee=5,
        idempotency_key="buy-1",
    )
    assert duplicate.json()["id"] == buy.json()["id"]

    sell = _add_trade(
        client,
        strategy_id,
        type="sell",
        trade_date="2026-07-11",
        asset_symbol="600000.SH",
        price=120,
        quantity=4,
        fee=2,
    )
    assert sell.status_code == 201

    detail = client.get(f"/api/v1/strategies/{strategy_id}").json()
    assert len(detail["trades"]) == 3
    position = detail["positions"][0]
    assert position["quantity"] == "6.000000"
    assert position["average_cost"] == "100.500000"
    assert position["cost_basis"] == "603.000000"
    assert position["market_value"] == "660.000000"
    assert position["realized_profit"] == "76.000000"
    assert position["unrealized_profit"] == "57.000000"
    assert detail["summary"]["cash_balance"] == "9473.000000"
    assert detail["summary"]["total_value"] == "10133.000000"
    assert detail["summary"]["total_profit"] == "133.000000"

    past = client.get(
        f"/api/v1/strategies/{strategy_id}/positions", params={"as_of": "2026-07-05"}
    ).json()
    assert past[0]["quantity"] == "10.000000"


def test_rejects_oversell_and_supports_strategy_update(client):
    strategy_id = _create_strategy_and_asset(client)
    _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-02",
        asset_symbol="600000.SH",
        price=100,
        quantity=2,
    )
    rejected = _add_trade(
        client,
        strategy_id,
        type="sell",
        trade_date="2026-07-03",
        asset_symbol="600000.SH",
        price=110,
        quantity=3,
    )
    assert rejected.status_code == 409
    assert len(client.get(f"/api/v1/strategies/{strategy_id}/trades").json()) == 1

    updated = client.patch(
        f"/api/v1/strategies/{strategy_id}",
        json={"name": "银行价值增强", "description": None},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "银行价值增强"
    assert updated.json()["description"] is None


def test_portfolio_api_maintains_portfolio_metadata_and_strategy_compatibility(client):
    created = client.post(
        "/api/v1/portfolios",
        json={
            "name": "银河证券",
            "description": "兼容说明",
            "initial_capital": "500000",
            "investment_style": "稳健",
            "is_owned": True,
            "purpose": "家庭长期资产",
            "investment_direction": "A 股红利与宽基",
            "constraints": "单一标的不超过 20%",
            "notes": "每季度复盘",
        },
    )

    assert created.status_code == 201
    portfolio = created.json()
    assert portfolio["initial_capital"] == "500000.000000"
    assert portfolio["investment_style"] == "稳健"
    assert portfolio["is_owned"] is True
    assert portfolio["purpose"] == "家庭长期资产"
    assert portfolio["investment_direction"] == "A 股红利与宽基"
    assert portfolio["constraints"] == "单一标的不超过 20%"
    assert portfolio["notes"] == "每季度复盘"

    strategy = client.get(f"/api/v1/strategies/{portfolio['id']}")
    assert strategy.status_code == 200
    assert strategy.json()["initial_capital"] == "500000.000000"

    updated = client.patch(
        f"/api/v1/portfolios/{portfolio['id']}",
        json={
            "initial_capital": "600000",
            "investment_style": "均衡",
            "is_owned": False,
            "constraints": None,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["initial_capital"] == "600000.000000"
    assert updated.json()["investment_style"] == "均衡"
    assert updated.json()["is_owned"] is False
    assert updated.json()["constraints"] is None

    listed = client.get("/api/v1/portfolios").json()
    assert [item["id"] for item in listed] == [portfolio["id"]]


def test_web_strategy_page_uses_server_api(client):
    page = client.get("/strategy")
    assert page.status_code == 200
    assert "组合管理" in page.text
    assert "投资风格" in page.text
    assert "期初状态" in page.text
    assert "historical_net_contribution" in page.text
    assert 'api("/portfolios' in page.text
    assert 'id="portfolio-commentary"' in page.text
    assert 'subject_type: "portfolio"' in page.text
    assert 'id="trade-plans"' in page.text
    assert 'data-tab="commentary"' in page.text
    assert 'data-tab="trade-plans"' in page.text
    assert 'id="portfolio-info-dialog"' in page.text
    assert 'id="metric-initial-capital"' in page.text
    assert 'id="positions-query"' in page.text
    assert 'id="trades-type"' in page.text
    assert 'id="plans-status"' in page.text
    assert 'id="positions-pager"' in page.text
    assert 'data-sort-table="positions"' in page.text
    assert 'data-sort-table="trades"' in page.text
    assert 'data-sort-table="plans"' in page.text
    assert 'id="positions-sort"' not in page.text
    assert 'api("/trade-plans' in page.text
    assert "/static/commentary.js" in page.text
    assert "localStorage" not in page.text


def test_same_day_deposit_and_buy_are_ordered_consistently(client):
    strategy_id = _create_strategy_and_asset(client)
    deposit = _add_trade(
        client,
        strategy_id,
        type="deposit",
        trade_date="2026-07-02",
        price=10000,
    )
    buy = _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-02",
        asset_symbol="600000.SH",
        price=100,
        quantity=2,
    )
    assert deposit.status_code == 201
    assert buy.status_code == 201
    assert client.get(f"/api/v1/strategies/{strategy_id}").status_code == 200


def test_position_id_changes_only_after_an_end_of_day_close(client):
    strategy_id = _create_strategy_and_asset(client)
    buy = _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-02",
        asset_symbol="600000.SH",
        price=100,
        quantity=10,
    ).json()
    _add_trade(
        client,
        strategy_id,
        type="sell",
        trade_date="2026-07-03",
        asset_symbol="600000.SH",
        price=110,
        quantity=10,
    )
    same_day_rebuy = _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-03",
        asset_symbol="600000.SH",
        price=105,
        quantity=5,
    ).json()
    _add_trade(
        client,
        strategy_id,
        type="sell",
        trade_date="2026-07-04",
        asset_symbol="600000.SH",
        price=106,
        quantity=5,
    )
    next_cycle = _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-05",
        asset_symbol="600000.SH",
        price=100,
        quantity=1,
    ).json()
    cash_trade = _add_trade(
        client,
        strategy_id,
        type="deposit",
        trade_date="2026-07-05",
        price=100,
    ).json()

    trades = client.get(f"/api/v1/strategies/{strategy_id}/trades").json()
    first_cycle_ids = {
        trade["position_id"]
        for trade in trades
        if trade["asset_symbol"] == "600000.SH"
        and trade["trade_date"] <= "2026-07-04"
    }
    assert first_cycle_ids == {buy["position_id"]}
    assert same_day_rebuy["position_id"] == buy["position_id"]
    assert next_cycle["position_id"] != buy["position_id"]
    assert cash_trade["position_id"] is None


def test_win_rate_and_profit_loss_ratio_use_completed_position_returns(client):
    strategy_id = _create_strategy_and_asset(client)
    trades = [
        ("buy", "2026-07-01", 100, 10),
        ("sell", "2026-07-02", 100, 5),
        ("buy", "2026-07-03", 100, 10),
        ("sell", "2026-07-04", 110, 15),
        ("buy", "2026-07-05", 100, 10),
        ("sell", "2026-07-06", 80, 10),
        ("buy", "2026-07-07", 100, 1),
    ]
    for trade_type, trade_date, price, quantity in trades:
        response = _add_trade(
            client,
            strategy_id,
            type=trade_type,
            trade_date=trade_date,
            asset_symbol="600000.SH",
            price=price,
            quantity=quantity,
        )
        assert response.status_code == 201

    summary = client.get(f"/api/v1/strategies/{strategy_id}").json()["summary"]
    assert summary["completed_position_count"] == 2
    assert summary["winning_position_count"] == 1
    assert summary["win_rate"] == "0.500000"
    # Winner: 150 / max(1000, 500 + 1000) = 10%; loser: -200 / 1000 = -20%.
    assert summary["profit_loss_ratio"] == "0.500000"


def test_opening_snapshot_initializes_cash_positions_and_historical_profit(client):
    strategy_id = _create_strategy_and_asset(client)
    response = client.put(
        f"/api/v1/strategies/{strategy_id}/opening-snapshot",
        json={
            "snapshot_date": "2026-07-10",
            "balances": [{
                "currency": "CNY",
                "cash": 10000,
                "historical_net_contribution": 10800,
                "historical_realized_profit": 200,
            }],
            "positions": [
                {
                    "asset_symbol": "600000.SH",
                    "quantity": 10,
                    "average_cost": 100,
                }
            ],
        },
    )
    assert response.status_code == 200
    assert response.json()["positions"][0]["cost_basis"] == "1000.000000"

    detail = client.get(f"/api/v1/strategies/{strategy_id}").json()
    assert detail["opening_snapshot"]["snapshot_date"] == "2026-07-10"
    assert detail["opening_snapshot"]["balances"][0]["currency"] == "CNY"
    assert detail["summary"]["cash_balance"] == "10000.000000"
    assert detail["summary"]["net_contribution"] == "10800.000000"
    assert detail["summary"]["historical_realized_profit"] == "200.000000"
    assert detail["summary"]["realized_profit_since_snapshot"] == "0.000000"
    assert detail["summary"]["realized_profit"] == "200.000000"
    assert detail["summary"]["unrealized_profit"] == "100.000000"
    assert detail["summary"]["total_profit"] == "300.000000"

    rejected = _add_trade(
        client,
        strategy_id,
        type="sell",
        trade_date="2026-07-10",
        asset_symbol="600000.SH",
        price=120,
        quantity=1,
    )
    assert rejected.status_code == 409

    sold = _add_trade(
        client,
        strategy_id,
        type="sell",
        trade_date="2026-07-11",
        asset_symbol="600000.SH",
        price=120,
        quantity=4,
        fee=2,
    )
    assert sold.status_code == 201

    detail = client.get(f"/api/v1/strategies/{strategy_id}").json()
    assert detail["positions"][0]["quantity"] == "6.000000"
    assert detail["positions"][0]["cost_basis"] == "600.000000"
    assert detail["positions"][0]["realized_profit"] == "78.000000"
    assert detail["summary"]["cash_balance"] == "10478.000000"
    assert detail["summary"]["historical_realized_profit"] == "200.000000"
    assert detail["summary"]["realized_profit_since_snapshot"] == "78.000000"
    assert detail["summary"]["realized_profit"] == "278.000000"
    assert detail["summary"]["total_profit"] == "338.000000"


def test_snapshot_without_historical_contribution_keeps_return_basis_unknown(client):
    strategy_id = _create_strategy_and_asset(client)
    response = client.put(
        f"/api/v1/strategies/{strategy_id}/opening-snapshot",
        json={
            "snapshot_date": "2026-07-10",
            "balances": [{
                "currency": "CNY",
                "cash": 100,
                "historical_realized_profit": 50,
            }],
            "positions": [
                {
                    "asset_symbol": "600000.SH",
                    "quantity": 10,
                    "average_cost": 100,
                }
            ],
        },
    )
    assert response.status_code == 200

    detail = client.get(f"/api/v1/strategies/{strategy_id}").json()
    assert detail["summary"]["net_contribution"] is None
    assert detail["summary"]["total_value"] == "1200.000000"
    assert detail["summary"]["total_profit"] == "150.000000"


def test_snapshot_requires_registered_assets_and_must_precede_existing_trades(client):
    strategy_id = _create_strategy_and_asset(client)
    missing = client.put(
        f"/api/v1/strategies/{strategy_id}/opening-snapshot",
        json={
            "snapshot_date": "2026-07-10",
            "balances": [],
            "positions": [
                {
                    "asset_symbol": "MISSING.SH",
                    "quantity": 1,
                    "average_cost": 1,
                }
            ],
        },
    )
    assert missing.status_code == 409

    assert (
        _add_trade(
            client,
            strategy_id,
            type="deposit",
            trade_date="2026-07-11",
            price=100,
        ).status_code
        == 201
    )
    conflict = client.put(
        f"/api/v1/strategies/{strategy_id}/opening-snapshot",
        json={
            "snapshot_date": "2026-07-11",
            "balances": [{"currency": "CNY", "cash": 100}],
            "positions": [],
        },
    )
    assert conflict.status_code == 409


def test_snapshot_can_be_replaced_and_deleted_without_trades(client):
    strategy_id = _create_strategy_and_asset(client)
    endpoint = f"/api/v1/strategies/{strategy_id}/opening-snapshot"
    initial = client.put(
        endpoint,
        json={
            "snapshot_date": "2026-07-10",
            "balances": [{"currency": "CNY", "cash": 100}],
            "positions": [
                {
                    "asset_symbol": "600000.SH",
                    "quantity": 1,
                    "average_cost": 100,
                }
            ],
        },
    )
    assert initial.status_code == 200

    replaced = client.put(
        endpoint,
        json={
            "snapshot_date": "2026-07-11",
            "balances": [{
                "currency": "CNY",
                "cash": 200,
                "historical_net_contribution": 300,
                "historical_realized_profit": -10,
            }],
            "positions": [],
        },
    )
    assert replaced.status_code == 200
    assert replaced.json()["positions"] == []
    assert replaced.json()["balances"][0]["historical_realized_profit"] == "-10.000000"

    deleted = client.delete(endpoint)
    assert deleted.status_code == 204
    assert client.get(endpoint).json() is None


def test_multi_currency_strategy_uses_asset_currency_and_daily_fx(
    client, session_factory
):
    asset = client.post(
        "/api/v1/assets",
        json={
            "symbol": "00700.HK",
            "name": "腾讯控股",
            "category": "stock",
            "currency": "HKD",
            "provider_id": "116.00700",
        },
    )
    assert asset.status_code == 201
    assert asset.json()["currency"] == "HKD"
    with session_factory() as session:
        session.add(
            MarketBar(
                asset_key=asset_identity(AssetCategory.STOCK, "00700.HK"),
                trade_date=date(2026, 7, 10),
                close=Decimal("400"),
                source="test",
            )
        )
        session.add_all(
            [
                ExchangeRate(
                    trade_date=date(2000, 1, 1),
                    currency=currency,
                    units_per_eur=Decimal(rate),
                    source="test",
                )
                for currency, rate in {"CNY": "8", "HKD": "10", "USD": "1"}.items()
            ]
        )
        session.commit()

    strategy = client.post(
        "/api/v1/strategies",
        json={"name": "全球账户", "description": "多币种"},
    )
    assert strategy.status_code == 201
    assert "currency" not in strategy.json()
    strategy_id = strategy.json()["id"]
    snapshot = client.put(
        f"/api/v1/strategies/{strategy_id}/opening-snapshot",
        json={
            "snapshot_date": "2026-07-10",
            "balances": [
                {
                    "currency": "HKD",
                    "cash": 1000,
                    "historical_net_contribution": 4000,
                },
                {
                    "currency": "USD",
                    "cash": 100,
                    "historical_net_contribution": 100,
                },
            ],
            "positions": [
                {
                    "asset_symbol": "00700.HK",
                    "quantity": 10,
                    "average_cost": 300,
                }
            ],
        },
    )
    assert snapshot.status_code == 200

    buy = _add_trade(
        client,
        strategy_id,
        type="buy",
        trade_date="2026-07-11",
        asset_symbol="00700.HK",
        price=350,
        quantity=1,
        currency="USD",
    )
    assert buy.status_code == 201
    assert buy.json()["currency"] == "HKD"

    detail = client.get(f"/api/v1/strategies/{strategy_id}").json()
    assert detail["summary"]["reporting_currency"] == "CNY"
    assert detail["summary"]["cash_balance"] == "1320.000000"
    assert detail["summary"]["market_value"] == "3520.000000"
    assert detail["summary"]["net_contribution"] == "4000.000000"
    assert detail["summary"]["total_value"] == "4840.000000"
    assert detail["summary"]["total_profit"] == "840.000000"
    assert {item["currency"] for item in detail["summary"]["cash_balances"]} == {
        "HKD",
        "USD",
    }
    position = detail["positions"][0]
    assert position["asset"]["currency"] == "HKD"
    assert position["market_value"] == "4400.000000"
    assert position["market_value_report"] == "3520.000000"
    assert position["unrealized_profit_report"] == "840.000000"
