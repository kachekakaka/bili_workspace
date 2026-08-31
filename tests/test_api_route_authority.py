from collections import defaultdict


def test_composed_http_routes_have_one_authoritative_handler(client):
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)
    for route in client.app.routes:
        path = str(getattr(route, "path", ""))
        methods = getattr(route, "methods", None) or set()
        for method in methods:
            owners[(str(method), path)].append(str(getattr(route, "name", "")))

    duplicates = {
        key: names
        for key, names in owners.items()
        if len(names) > 1
    }
    assert duplicates == {}
