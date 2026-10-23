"""Tests for pure helpers in pangolin_gui.tray (no GTK required)."""
from datetime import datetime, timedelta, timezone


from pangolin_gui.models import Account, AppState, ConnState, OlmStatus, Org, Peer
from pangolin_gui.tray import (
    compute_menu_signature,
    format_relative_time,
    format_status,
    get_peer_connection_type,
    get_status_color,
    get_status_colour,
    get_status_label,
    menu_signature,
    peer_connection_type,
    relative_time,
    status_color,
    status_colour,
    status_label,
)


class TestStatusHelpers:
    """Tests for status label and color formatting from AppState."""

    def test_status_connected(self):
        state = AppState(conn=ConnState.CONNECTED)
        assert get_status_label(state) == "Connected"
        assert get_status_color(state) == "green"
        assert format_status(state) == ("Connected", "green")
        assert status_label(state) == "Connected"
        assert status_color(state) == "green"
        assert status_colour(state) == "green"
        assert get_status_colour(state) == "green"

    def test_status_connecting(self):
        state = AppState(conn=ConnState.CONNECTING)
        assert get_status_label(state) == "Registering…"
        assert get_status_color(state) == "orange"
        assert format_status(state) == ("Registering…", "orange")

    def test_status_disconnecting(self):
        state = AppState(conn=ConnState.DISCONNECTING)
        assert get_status_label(state) == "Disconnecting…"
        assert get_status_color(state) == "gray"
        assert format_status(state) == ("Disconnecting…", "gray")

    def test_status_disconnected(self):
        state = AppState(conn=ConnState.DISCONNECTED)
        assert get_status_label(state) == "Disconnected"
        assert get_status_color(state) == "gray"
        assert format_status(state) == ("Disconnected", "gray")

    def test_status_error_with_last_error(self):
        state = AppState(conn=ConnState.ERROR, last_error="Sudo permission denied")
        assert get_status_label(state) == "Sudo permission denied"
        assert get_status_color(state) == "red"
        assert format_status(state) == ("Sudo permission denied", "red")

    def test_status_error_with_olm_message(self):
        olm_status = OlmStatus(error_message="OLM daemon unreachable")
        state = AppState(conn=ConnState.ERROR, status=olm_status, last_error="")
        assert get_status_label(state) == "OLM daemon unreachable"
        assert get_status_color(state) == "red"
        assert format_status(state) == ("OLM daemon unreachable", "red")

    def test_status_error_fallback(self):
        state = AppState(conn=ConnState.ERROR, last_error="", status=None)
        assert get_status_label(state) == "Error"
        assert get_status_color(state) == "red"
        assert format_status(state) == ("Error", "red")


class TestRelativeTime:
    """Tests for relative time formatting from ISO 8601 strings."""

    def test_empty_or_none(self):
        assert format_relative_time(None) == ""
        assert format_relative_time("") == ""
        assert relative_time(None) == ""

    def test_invalid_string(self):
        invalid = "not-a-valid-timestamp"
        assert format_relative_time(invalid) == invalid

    def test_now_and_future(self):
        now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        iso_str = "2026-10-23T12:00:00Z"
        assert format_relative_time(iso_str, now=now) == "0s ago"

        # Future time clamps to 0s ago
        future_iso = "2026-10-23T12:05:00Z"
        assert format_relative_time(future_iso, now=now) == "0s ago"

    def test_seconds(self):
        now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        iso_str = (now - timedelta(seconds=15)).isoformat()
        assert format_relative_time(iso_str, now=now) == "15s ago"

        iso_str_59 = (now - timedelta(seconds=59)).isoformat()
        assert format_relative_time(iso_str_59, now=now) == "59s ago"

    def test_minutes(self):
        now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        iso_str_60 = (now - timedelta(seconds=60)).isoformat()
        assert format_relative_time(iso_str_60, now=now) == "1m ago"

        iso_str_5m = (now - timedelta(minutes=5, seconds=30)).isoformat()
        assert format_relative_time(iso_str_5m, now=now) == "5m ago"

        iso_str_59m = (now - timedelta(minutes=59, seconds=59)).isoformat()
        assert format_relative_time(iso_str_59m, now=now) == "59m ago"

    def test_hours(self):
        now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        iso_str_1h = (now - timedelta(hours=1)).isoformat()
        assert format_relative_time(iso_str_1h, now=now) == "1h ago"

        iso_str_3h = (now - timedelta(hours=3, minutes=12)).isoformat()
        assert format_relative_time(iso_str_3h, now=now) == "3h ago"

        iso_str_23h = (now - timedelta(hours=23, minutes=59)).isoformat()
        assert format_relative_time(iso_str_23h, now=now) == "23h ago"

    def test_days(self):
        now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        iso_str_1d = (now - timedelta(days=1)).isoformat()
        assert format_relative_time(iso_str_1d, now=now) == "1d ago"

        iso_str_2d = (now - timedelta(days=2, hours=4)).isoformat()
        assert format_relative_time(iso_str_2d, now=now) == "2d ago"

    def test_offset_handling(self):
        now = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
        # 12:00:00+02:00 is 10:00:00 UTC (2 hours prior)
        iso_str = "2026-10-23T12:00:00+02:00"
        assert format_relative_time(iso_str, now=now) == "2h ago"


class TestPeerConnectionType:
    """Tests for peer connection classification."""

    def test_local_peer(self):
        peer = Peer(
            site_id=1,
            name="Office",
            connected=True,
            rtt_ms=1.5,
            last_seen=None,
            is_local=True,
            is_relay=False,
        )
        assert peer_connection_type(peer) == "Local"
        assert get_peer_connection_type(peer) == "Local"

    def test_relay_peer(self):
        peer = Peer(
            site_id=2,
            name="Remote",
            connected=True,
            rtt_ms=55.0,
            last_seen=None,
            is_local=False,
            is_relay=True,
        )
        assert peer_connection_type(peer) == "Relay"

    def test_direct_peer(self):
        peer = Peer(
            site_id=3,
            name="Laptop",
            connected=True,
            rtt_ms=20.0,
            last_seen=None,
            is_local=False,
            is_relay=False,
        )
        assert peer_connection_type(peer) == "Direct"

    def test_disconnected_peer_fallback(self):
        peer = Peer(
            site_id=4,
            name="Backup",
            connected=False,
            rtt_ms=0.0,
            last_seen=None,
            is_local=False,
            is_relay=False,
        )
        assert peer_connection_type(peer) == "Direct"


class TestMenuSignature:
    """Tests for compute_menu_signature stability and sensitivity."""

    def test_identical_states_have_equal_signatures(self):
        acc = Account(user_id="u1", host="https://app.pangolin.net", email="user@example.com")
        org = Org(org_id="o1", name="Acme Inc")
        state1 = AppState(
            conn=ConnState.DISCONNECTED,
            accounts=[acc],
            active_account=acc,
            orgs=[org],
            cli_installed=True,
            cli_version="1.2.0",
        )
        state2 = AppState(
            conn=ConnState.DISCONNECTED,
            accounts=[acc],
            active_account=acc,
            orgs=[org],
            cli_installed=True,
            cli_version="1.2.0",
        )
        sig1 = compute_menu_signature(state1)
        sig2 = compute_menu_signature(state2)
        assert sig1 == sig2
        assert menu_signature(state1) == sig1
        # Signature is hashable
        assert hash(sig1) == hash(sig2)

    def test_signature_changes_on_conn_state(self):
        acc = Account(user_id="u1", host="https://app.pangolin.net", email="user@example.com")
        state1 = AppState(conn=ConnState.DISCONNECTED, accounts=[acc], active_account=acc)
        state2 = AppState(conn=ConnState.CONNECTED, accounts=[acc], active_account=acc)
        assert compute_menu_signature(state1) != compute_menu_signature(state2)

    def test_signature_changes_on_active_account(self):
        acc1 = Account(user_id="u1", host="https://app.pangolin.net", email="u1@example.com")
        acc2 = Account(user_id="u2", host="https://app.pangolin.net", email="u2@example.com")
        state1 = AppState(accounts=[acc1, acc2], active_account=acc1)
        state2 = AppState(accounts=[acc1, acc2], active_account=acc2)
        assert compute_menu_signature(state1) != compute_menu_signature(state2)

    def test_signature_changes_on_orgs(self):
        acc = Account(user_id="u1", host="https://app.pangolin.net", email="user@example.com", org_id="o1")
        org1 = Org(org_id="o1", name="Org One")
        org2 = Org(org_id="o2", name="Org Two")
        state1 = AppState(accounts=[acc], active_account=acc, orgs=[org1])
        state2 = AppState(accounts=[acc], active_account=acc, orgs=[org1, org2])
        assert compute_menu_signature(state1) != compute_menu_signature(state2)

    def test_signature_changes_on_cli_installed(self):
        state1 = AppState(cli_installed=True)
        state2 = AppState(cli_installed=False)
        assert compute_menu_signature(state1) != compute_menu_signature(state2)

    def test_signature_changes_on_error(self):
        state1 = AppState(conn=ConnState.ERROR, last_error="Err A")
        state2 = AppState(conn=ConnState.ERROR, last_error="Err B")
        assert compute_menu_signature(state1) != compute_menu_signature(state2)

    def test_signature_changes_on_peers_when_connected(self):
        acc = Account(user_id="u1", host="https://app.pangolin.net", email="user@example.com")
        peer1 = Peer(site_id=1, name="P1", connected=True, rtt_ms=10.0, last_seen="2026-10-23T10:00:00Z")
        peer2 = Peer(site_id=1, name="P1", connected=True, rtt_ms=25.0, last_seen="2026-10-23T10:00:00Z")

        status1 = OlmStatus(peers=[peer1])
        status2 = OlmStatus(peers=[peer2])

        state1 = AppState(conn=ConnState.CONNECTED, accounts=[acc], active_account=acc, status=status1)
        state2 = AppState(conn=ConnState.CONNECTED, accounts=[acc], active_account=acc, status=status2)

        assert compute_menu_signature(state1) != compute_menu_signature(state2)

    def test_peers_ignored_when_disconnected(self):
        # When disconnected, sites submenu is not built, so peer changes don't cause rebuild
        peer1 = Peer(site_id=1, name="P1", connected=True, rtt_ms=10.0, last_seen="2026-10-23T10:00:00Z")
        peer2 = Peer(site_id=1, name="P1", connected=True, rtt_ms=50.0, last_seen="2026-10-23T10:00:00Z")

        status1 = OlmStatus(peers=[peer1])
        status2 = OlmStatus(peers=[peer2])

        state1 = AppState(conn=ConnState.DISCONNECTED, status=status1)
        state2 = AppState(conn=ConnState.DISCONNECTED, status=status2)

        assert compute_menu_signature(state1) == compute_menu_signature(state2)
