import uuid

import pytest
from httpx import AsyncClient

API_V1_PREFIX = "/api/v1"
PAYMENTS_URL = f"{API_V1_PREFIX}/payments"
API_KEY = "dev_secret_key_change_in_production"
    
@pytest.mark.asyncio
class TestPaymentsAPI:
    
    async def test_create_payment_success(self, client: AsyncClient):
        """Проверка успешного создания платежа (202 Accepted)"""
        idempotency_key = str(uuid.uuid4())
        payload = {
            "amount": 100.50,
            "currency": "RUB",
            "description": "Оплата заказа #123",
            "webhook_url": "https://example.com/webhook",
            "metadata": {"order_id": "123"}
        }
        headers = {
            "X-API-Key": API_KEY,
            "Idempotency-Key": idempotency_key
        }

        response = await client.post(PAYMENTS_URL, json=payload, headers=headers)
        
        assert response.status_code == 202
        data = response.json()
        assert "payment_id" in data
        assert data["status"] == "pending"
        assert "created_at" in data

    async def test_create_payment_idempotency(self, client: AsyncClient):
        """Проверка идемпотентности: повторный запрос с тем же ключом возвращает тот же ID"""
        idempotency_key = str(uuid.uuid4())
        payload = {
            "amount": 50.0,
            "currency": "USD",
            "description": "Idempotent test",
            "webhook_url": "https://example.com/callback"
        }
        headers = {
            "X-API-Key": API_KEY,
            "Idempotency-Key": idempotency_key
        }

        resp1 = await client.post(PAYMENTS_URL, json=payload, headers=headers)
        id1 = resp1.json()["payment_id"]

        resp2 = await client.post(PAYMENTS_URL, json=payload, headers=headers)
        id2 = resp2.json()["payment_id"]

        assert resp1.status_code == 202
        assert resp2.status_code == 202
        assert id1 == id2

    async def test_get_payment_details(self, client: AsyncClient):
        """Проверка получения детальной информации о платеже"""
        id_key = str(uuid.uuid4())
        headers = {"X-API-Key": API_KEY, "Idempotency-Key": id_key}
        payload = {
            "amount": 10.0, 
            "currency": "EUR", 
            "description": "Get test", 
            "webhook_url": "http://hook.io"
        }
        
        create_resp = await client.post(PAYMENTS_URL, json=payload, headers=headers)
        payment_id = create_resp.json()["payment_id"]
        get_resp = await client.get(f"{PAYMENTS_URL}/{payment_id}", headers={"X-API-Key": API_KEY})
        
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["id"] == payment_id
        assert data["amount"] == "10.00"
        assert data["currency"] == "EUR"
        assert data["status"] == "pending"

    async def test_create_payment_validation_error(self, client: AsyncClient):
        """Проверка валидации: отрицательная сумма"""
        headers = {"X-API-Key": API_KEY, "Idempotency-Key": str(uuid.uuid4())}
        payload = {
            "amount": -100,  # Невалидно (gt=0 в схеме)
            "currency": "RUB",
            "description": "Bad amount",
            "webhook_url": "https://example.com"
        }

        response = await client.post(PAYMENTS_URL, json=payload, headers=headers)
        assert response.status_code == 422 # Unprocessable Entity

    async def test_unauthorized_access(self, client: AsyncClient):
        """Проверка защиты API: запрос без X-API-Key или с неверным ключом"""
        headers = {"Idempotency-Key": str(uuid.uuid4())}
    
        # Запрос без ключа
        response = await client.post(PAYMENTS_URL, json={}, headers=headers)
        assert response.status_code == 401
    
        # Запрос с неверным ключом
        headers_wrong = {**headers, "X-API-Key": "wrong_key"}
        response = await client.post(PAYMENTS_URL, json={}, headers=headers_wrong)
        assert response.status_code == 401
        

    async def test_get_non_existent_payment(self, client: AsyncClient):
        """Проверка получения несуществующего платежа (404)"""
        random_id = str(uuid.uuid4())
        response = await client.get(f"{PAYMENTS_URL}/{random_id}", headers={"X-API-Key": API_KEY})
        assert response.status_code == 404