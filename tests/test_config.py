import pytest
from pydantic import ValidationError

from app.config import Settings

REQUIRED = "SUPABASE_URL=http://localhost\nSUPABASE_SERVICE_KEY=k\nREDUCTO_API_KEY=k\n"


@pytest.mark.parametrize("key", ["SUPABASE_KEY", "LLM_PROVIDER", "OPENAI_API_KEY"])
def test_removed_keys_are_rejected(tmp_path, key):
    env = tmp_path / ".env"
    env.write_text(REQUIRED + f"{key}=x\n", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        Settings(_env_file=env)
    errors = [(e["type"], e["loc"]) for e in exc.value.errors()]
    assert errors == [("extra_forbidden", (key.lower(),))]


def test_minimal_env_is_accepted(tmp_path):
    env = tmp_path / ".env"
    env.write_text(REQUIRED, encoding="utf-8")
    assert isinstance(Settings(_env_file=env), Settings)


def test_confirmation_age_defaults_to_180_days(tmp_path):
    env = tmp_path / ".env"
    env.write_text(REQUIRED, encoding="utf-8")
    assert Settings(_env_file=env).confirmation_max_age_days == 180


def test_confirmation_age_can_be_set(tmp_path):
    env = tmp_path / ".env"
    env.write_text(REQUIRED + "CONFIRMATION_MAX_AGE_DAYS=90\n", encoding="utf-8")
    assert Settings(_env_file=env).confirmation_max_age_days == 90


def test_embedding_rate_limit_defaults(tmp_path):
    env = tmp_path / ".env"
    env.write_text(REQUIRED, encoding="utf-8")
    s = Settings(_env_file=env)
    assert (s.embed_rate_limit_wait_seconds, s.embed_rate_limit_retries) == (61, 5)
