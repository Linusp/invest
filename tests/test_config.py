from invest_service.config import Settings


def test_settings_load_from_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("INVEST_DATABASE_URL", raising=False)
    monkeypatch.delenv("INVEST_REPORTING_CURRENCY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "INVEST_DATABASE_URL=mysql://invest:secret@db/invest",
                "INVEST_REPORTING_CURRENCY=USD",
                'INVEST_CORS_ORIGINS=["https://invest.example.com"]',
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.database_url == "mysql+pymysql://invest:secret@db/invest"
    assert settings.reporting_currency == "USD"
    assert settings.cors_origins == ["https://invest.example.com"]


def test_environment_variables_override_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("INVEST_REPORTING_CURRENCY=USD\n", encoding="utf-8")
    monkeypatch.setenv("INVEST_REPORTING_CURRENCY", "CNY")

    settings = Settings(_env_file=env_file)

    assert settings.reporting_currency == "CNY"


def test_empty_environment_variable_does_not_hide_dotenv_value(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("INVEST_TUSHARE_TOKEN=from-dotenv\n", encoding="utf-8")
    monkeypatch.setenv("INVEST_TUSHARE_TOKEN", "")

    settings = Settings(_env_file=env_file)

    assert settings.tushare_token == "from-dotenv"
