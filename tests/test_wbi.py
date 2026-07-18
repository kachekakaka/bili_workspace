from app.wbi import get_mixin_key, sign_params


def test_mixin_key_length():
    assert len(get_mixin_key("a" * 64)) == 32


def test_sign_params_known_vector():
    signed = sign_params(
        {"foo": "114", "bar": "514", "zab": 1919810},
        "7cd084941338484aae1ad9425b84077c",
        "4932caff0ff7463802950c7033c9cdac",
        wts=1702204169,
    )
    assert signed["wts"] == 1702204169
    assert signed["w_rid"] == "480ebe7870b8b8b1726e34afbf1b996a"
