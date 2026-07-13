def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_info(client):
    response = client.get("/api/v1/info")

    assert response.status_code == 200
    payload = response.json()
    assert payload["visualEntry"] == "fronted"
    assert {"key": "workbench", "path": "/workbench", "status": "reserved"} in payload[
        "featurePages"
    ]

