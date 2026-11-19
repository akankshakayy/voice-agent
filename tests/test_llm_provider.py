from app import llm_engine


def _env(monkeypatch, **env):
    for k in ("LLM_PROVIDER", "GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_auto_skips_claude_code_when_cli_missing(monkeypatch):
    _env(monkeypatch, GROQ_API_KEY="x")
    monkeypatch.setattr(llm_engine.shutil, "which", lambda name: None)
    assert llm_engine.provider() == "groq"


def test_auto_without_cli_or_keys_has_no_provider(monkeypatch):
    _env(monkeypatch)
    monkeypatch.setattr(llm_engine.shutil, "which", lambda name: None)
    assert llm_engine.provider() is None


def test_auto_prefers_claude_code_when_cli_installed(monkeypatch):
    _env(monkeypatch, GROQ_API_KEY="x")
    monkeypatch.setattr(llm_engine.shutil, "which", lambda name: "/usr/bin/claude")
    assert llm_engine.provider() == "claude-code"
