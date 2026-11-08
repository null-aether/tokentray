"""An expired access token is renewed by its owning CLI, not a second OAuth writer."""

import json
import logging
import subprocess
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import respx

from tokentray import connections
from tokentray.core.models import Status
from tokentray.core.secrets import SecretStore
from tokentray.providers import claude

NOW = 1_800_000_000.0
BODY = {"five_hour": {"utilization": 42, "resets_at": "2027-01-15T18:00:00Z"}}


def write_login(path, *, expired=True, refresh=True, refresh_expired=False, now=NOW):
    oauth = {"accessToken": "expired-access" if expired else "new-access",
             "expiresAt": (now - 10 if expired else now + 28800) * 1000,
             "subscriptionType": "pro"}
    if refresh:
        oauth["refreshToken"] = "private-refresh-token"
        oauth["refreshTokenExpiresAt"] = (now - 1 if refresh_expired else now + 86400) * 1000
    path.write_text(json.dumps({"claudeAiOauth": oauth}), encoding="utf-8")


@pytest.fixture
def provider(config, cache, claude_credentials, tmp_path, monkeypatch):
    write_login(claude_credentials)
    monkeypatch.setattr(claude.time, "time", lambda: NOW)
    monkeypatch.setattr(connections, "find_cli", lambda _: Path("/installed/claude"))
    monkeypatch.setattr(claude.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0)))
    instance = claude.ClaudeProvider(config, cache, secrets=SecretStore(tmp_path / "secrets.toml"))
    yield instance
    instance.close()


def test_cli_renews_then_fetch_uses_new_access_token(provider, claude_credentials, monkeypatch, caplog):
    def renew(*_args, **_kwargs):
        write_login(claude_credentials, expired=False)
        return subprocess.CompletedProcess([], 0)

    command = Mock(side_effect=renew)
    monkeypatch.setattr(claude.subprocess, "run", command)
    caplog.set_level(logging.INFO, logger="tokentray.claude")
    with respx.mock:
        route = respx.get(claude.USAGE_URL, headers={"Authorization": "Bearer new-access"}).mock(
            return_value=httpx.Response(200, json=BODY))
        snapshot = provider.fetch()
    assert snapshot.status is Status.OK
    assert snapshot.windows
    assert route.call_count == 1
    assert command.call_count == 1
    call = command.call_args
    assert call.args[0] == ["/installed/claude", "auth", "status", "--json"]
    for stream in ("stdin", "stdout", "stderr"):
        assert call.kwargs[stream] == subprocess.DEVNULL
    assert call.kwargs["timeout"] == claude.CLI_AUTH_TIMEOUT
    assert call.kwargs["env"]["CLAUDE_CONFIG_DIR"] == str(claude_credentials.parent)
    assert "auth_renewal_started" in caplog.text
    assert "auth_renewal_succeeded" in caplog.text
    for secret in ("expired-access", "new-access", "private-refresh-token"):
        assert secret not in caplog.text


@pytest.mark.parametrize("case", ["fresh", "manual", "no_refresh", "refresh_expired", "disabled"])
def test_cli_not_started_without_a_renewable_expired_login(provider, claude_credentials, monkeypatch, case):
    if case == "fresh":
        write_login(claude_credentials, expired=False)
    elif case == "no_refresh":
        write_login(claude_credentials, refresh=False)
    elif case == "refresh_expired":
        write_login(claude_credentials, refresh_expired=True)
    elif case == "disabled":
        provider.config.set("claude.renew_via_cli", False)
    creds = provider.credentials()
    if case == "manual":
        creds.source = "manual"
    assert provider.prepare_credentials(creds) is creds
    assert claude.subprocess.run.call_count == 0


def test_local_inspection_never_starts_cli(provider, monkeypatch):
    monkeypatch.setattr(connections, "make_provider", lambda *_: provider)
    observation = connections.observe("claude", provider.config)
    assert observation.connection.auth is connections.AuthState.EXPIRED
    assert claude.subprocess.run.call_count == 0


def test_keychain_is_not_renewed_by_an_automatic_poll(provider):
    creds = provider.credentials()
    creds.source = "keychain"
    assert provider.prepare_credentials(creds) is creds
    assert claude.subprocess.run.call_count == 0


def test_missing_cli_keeps_expired_status(provider, monkeypatch):
    monkeypatch.setattr(connections, "find_cli", lambda _: None)
    assert provider.fetch().status is Status.EXPIRED
    assert claude.subprocess.run.call_count == 0


@pytest.mark.parametrize("failure", ["timeout", "oserror", "unchanged", "exit_failure"])
def test_temporary_renewal_failure_keeps_stale_quota_and_throttles_cli(
    provider, claude_credentials, monkeypatch, caplog, failure,
):
    clock = [100.0]
    monkeypatch.setattr(claude.time, "monotonic", lambda: clock[0])
    command = claude.subprocess.run
    if failure == "timeout":
        command.side_effect = subprocess.TimeoutExpired(["claude"], 15, output=b"private-refresh-token")
    elif failure == "oserror":
        command.side_effect = OSError("private-refresh-token")
    elif failure == "exit_failure":
        command.return_value = subprocess.CompletedProcess([], 2)
    provider.cache.store("claude", BODY, now=NOW - 600)
    original = claude_credentials.read_bytes()
    for offset in (0, 30):
        snapshot = provider.fetch(force=True, now=NOW + offset)
        assert snapshot.status is Status.STALE
        assert snapshot.failure_kind == "auth_renewal"
        assert snapshot.windows
        assert snapshot.fetched_at == NOW - 600
    assert command.call_count == 1
    assert claude_credentials.read_bytes() == original
    assert "private-refresh-token" not in caplog.text
    clock[0] += 301
    provider.fetch(force=True, now=NOW + 301)
    assert command.call_count == 2


def test_cli_not_logged_in_requires_login(provider, monkeypatch):
    claude.subprocess.run.return_value = subprocess.CompletedProcess([], 1)
    for offset in (0, 120, 3600):
        assert provider.fetch(force=True, now=NOW + offset).status is Status.EXPIRED
    assert claude.subprocess.run.call_count == 1


def test_auth_retry_backoff_cannot_be_bypassed_by_refresh_clicks(provider, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(claude.time, "monotonic", lambda: clock[0])
    command = claude.subprocess.run
    command.side_effect = subprocess.TimeoutExpired(["claude"], 15)
    for attempt, delay in enumerate((300, 600, 1200, 2400, 3600), 1):
        provider.fetch(force=True, now=NOW + clock[0])
        assert command.call_count == attempt
        clock[0] += delay - 1
        provider.fetch(force=True, now=NOW + clock[0])
        assert command.call_count == attempt
        clock[0] += 1


def test_changed_credentials_allow_a_new_attempt_after_cli_reports_logout(
    provider, claude_credentials,
):
    command = claude.subprocess.run
    command.return_value = subprocess.CompletedProcess([], 1)
    assert provider.fetch().status is Status.EXPIRED
    write_login(claude_credentials, now=NOW + 1)
    assert provider.fetch(force=True).status is Status.EXPIRED
    assert command.call_count == 2


def test_concurrent_cli_renewal_wins_over_a_command_failure(provider, claude_credentials, monkeypatch):
    def renew_elsewhere(*_args, **_kwargs):
        write_login(claude_credentials, expired=False)
        raise subprocess.TimeoutExpired(["claude"], 15)

    monkeypatch.setattr(claude.subprocess, "run", Mock(side_effect=renew_elsewhere))
    with respx.mock:
        respx.get(claude.USAGE_URL).mock(return_value=httpx.Response(200, json=BODY))
        assert provider.fetch().status is Status.OK


def test_cli_exit_zero_without_renewal_is_not_success(provider):
    snapshot = provider.fetch()
    assert snapshot.status is Status.ERROR
    assert snapshot.failure_kind == "auth_renewal"


def test_renewal_works_again_after_the_next_eight_hour_expiry(provider, claude_credentials, monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(claude.time, "time", lambda: clock[0])
    monkeypatch.setattr(claude.time, "monotonic", lambda: clock[0])

    def renew(*_args, **_kwargs):
        write_login(claude_credentials, expired=False, now=clock[0])
        return subprocess.CompletedProcess([], 0)

    command = Mock(side_effect=renew)
    monkeypatch.setattr(claude.subprocess, "run", command)
    with respx.mock:
        route = respx.get(claude.USAGE_URL).mock(return_value=httpx.Response(200, json=BODY))
        assert provider.fetch().status is Status.OK
        clock[0] += 28801
        assert provider.fetch().status is Status.OK
        assert route.call_count == 2
    assert command.call_count == 2


def test_relative_account_directory_is_preserved_when_changing_cwd(provider, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "claude")
    provider.fetch()
    assert claude.subprocess.run.call_args.kwargs["env"]["CLAUDE_CONFIG_DIR"] == str(tmp_path / "claude")
