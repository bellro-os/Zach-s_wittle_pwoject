import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _req(key: str) -> str:
    v = os.getenv(key)
    if not v:
        raise RuntimeError(f"missing env var {key}")
    return v


@dataclass(frozen=True)
class Settings:
    database_url: str
    mls_mode: str
    reso_base_url: str
    reso_token_url: str
    reso_client_id: str
    reso_client_secret: str
    rets_login_url: str
    rets_username: str
    rets_password: str
    rets_user_agent: str
    rets_ua_password: str
    assessor_base: str
    assessor_jurisdiction: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    digest_from: str
    digest_to: str
    absentee_min_tenure_years: int
    absentee_min_equity_ratio: float


def load() -> Settings:
    return Settings(
        database_url=_req("DATABASE_URL"),
        mls_mode=os.getenv("MLS_MODE", "reso").lower(),
        reso_base_url=os.getenv("MLS_RESO_BASE_URL", ""),
        reso_token_url=os.getenv("MLS_RESO_TOKEN_URL", ""),
        reso_client_id=os.getenv("MLS_RESO_CLIENT_ID", ""),
        reso_client_secret=os.getenv("MLS_RESO_CLIENT_SECRET", ""),
        rets_login_url=os.getenv("MLS_RETS_LOGIN_URL", ""),
        rets_username=os.getenv("MLS_RETS_USERNAME", ""),
        rets_password=os.getenv("MLS_RETS_PASSWORD", ""),
        rets_user_agent=os.getenv("MLS_RETS_USER_AGENT", ""),
        rets_ua_password=os.getenv("MLS_RETS_UA_PASSWORD", ""),
        assessor_base=os.getenv(
            "ASSESSOR_BASE",
            "https://maps.montva.com/server/rest/services/Land/Parcels_Public/MapServer/1",
        ),
        assessor_jurisdiction=os.getenv("ASSESSOR_JURISDICTION", "BLACKSBURG"),
        smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_pass=os.getenv("SMTP_PASS", ""),
        digest_from=os.getenv("DIGEST_FROM", ""),
        digest_to=os.getenv("DIGEST_TO", ""),
        absentee_min_tenure_years=int(os.getenv("ABSENTEE_MIN_TENURE_YEARS", "10")),
        absentee_min_equity_ratio=float(os.getenv("ABSENTEE_MIN_EQUITY_RATIO", "0.60")),
    )
