
from app.cookie import check_cookie_status, read_cookie_string


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def get(self, *args, **kwargs):
        del args, kwargs
        if self.error:
            raise self.error
        return FakeResponse(self.payload)


def test_online_login_must_be_verified(tmp_env):
    status = check_cookie_status(
        tmp_env.bbdown_dir,
        client=FakeClient({"code": 0, "data": {"isLogin": True}}),
    )
    assert status.logged_in is True
    assert status.online_verified is True
    assert "fake-session" in read_cookie_string(tmp_env.bbdown_dir)


def test_cookie_string_alone_is_not_treated_as_valid(tmp_env):
    status = check_cookie_status(
        tmp_env.bbdown_dir,
        client=FakeClient({"code": 0, "data": {"isLogin": False}}),
    )
    assert status.logged_in is False
    assert status.login_state == "invalid"


def test_network_error_is_unknown_not_logged_in(tmp_env):
    status = check_cookie_status(
        tmp_env.bbdown_dir, client=FakeClient(error=RuntimeError("offline"))
    )
    assert status.logged_in is False
    assert status.login_state == "unknown"
    assert status.online_verified is False


def test_missing_cookie(tmp_path):
    status = check_cookie_status(tmp_path, client=FakeClient({}))
    assert status.logged_in is False
    assert status.login_state == "missing"
