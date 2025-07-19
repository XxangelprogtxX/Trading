from fastapi import FastAPI, Request
import hmac
import hashlib
import time
import requests

app = FastAPI()

API_KEY = "73822c2d124c1a40b5168a423375d1969f7dded4900a03e6c17020f8826203c5"
SECRET_KEY = "5064f117f72bbb97717ab53fe0de515b7be9f66672cdc844da69b85f7533ac54"
BINANCE_API_URL = "https://testnet.binancefuture.com"  # Futures USDⓈ-M

def sign_request(params: dict, secret: str):
    # Construye query string ordenado alfabéticamente
    query_string = '&'.join([f"{key}={params[key]}" for key in sorted(params)])
    # Firma con HMAC SHA256
    signature = hmac.new(secret.encode(), query_string.encode(), hashlib.sha256).hexdigest()
    return signature

def calcular_cantidad(monto_usdt, precio, apalancamiento=1):
    cantidad = (float(monto_usdt) * apalancamiento) / float(precio)
    return round(cantidad, 3)  # Ajusta según precisión requerida

@app.post("/webhook")
async def recibir_orden(request: Request):
    data = await request.json()
    print("Señal recibida:", data)

    symbol = data.get("simbolo")
    tipo = data.get("tipo")  # "LONG" o "SHORT"
    price = data.get("entrada")
    monto = data.get("monto")
    apalancamiento = data.get("apalancamiento") or 1

    if not all([symbol, tipo, price, monto]):
        return {"error": "Faltan datos para ejecutar orden"}

    side = "BUY" if tipo == "LONG" else "SELL"
    quantity = calcular_cantidad(monto, price, apalancamiento)
    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "side": side,
        "type": "LIMIT",
        "timeInForce": "GTC",
        "quantity": quantity,
        "price": f"{price:.2f}",
        "timestamp": timestamp
    }

    signature = sign_request(params, SECRET_KEY)
    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = f"{BINANCE_API_URL}/fapi/v1/order"

    response = requests.post(url, params=params, headers=headers)
    print("Respuesta Binance:", response.text)

    if response.status_code == 200:
        return {"status": "Orden ejecutada", "response": response.json()}
    else:
        return {"error": "Error al ejecutar orden", "response": response.text}
