
from fastapi import FastAPI, Request
from pydantic import BaseModel
import hmac, hashlib, time, requests
import urllib.parse

app = FastAPI()

# Endpoint de prueba
@app.get("/")
def root():
    return {"mensaje": "Bot de Binance funcionando", "timestamp": int(time.time())}

@app.get("/test")
def test_conexion():
    try:
        # Probar conexión básica a Binance
        response = requests.get(f"{BINANCE_URL}/fapi/v1/ping")
        if response.status_code == 200:
            return {"conexion": "OK", "binance": "Conectado"}
        else:
            return {"conexion": "ERROR", "detalle": response.text}
    except Exception as e:
        return {"conexion": "ERROR", "excepcion": str(e)}

API_KEY = "73822c2d124c1a40b5168a423375d1969f7dded4900a03e6c17020f8826203c5"
API_SECRET = "5064f117f72bbb97717ab53fe0de515b7be9f66672cdc844da69b85f7533ac54"
BINANCE_URL = "https://testnet.binancefuture.com"

class Orden(BaseModel):
    simbolo: str
    tipo: str  # LONG, SHORT, CLOSE_LONG, CLOSE_SHORT, CLOSE_ALL, STOP_LOSS
    entrada: float = None
    monto: float = None
    apalancamiento: int = None
    cantidad: float = None  # Para cierre específico de cantidad
    stop_loss: float = None  # Precio de stop loss
    take_profit: float = None  # Precio de take profit
    precio_limite: float = None  # Para órdenes límite

@app.post("/webhook")
def recibir_orden(orden: Orden):
    try:
        if orden.tipo == "STOP_LOSS":
            return colocar_stop_loss(orden)
        elif orden.tipo in ["CLOSE_LONG", "CLOSE_SHORT", "CLOSE_ALL"]:
            return cerrar_posicion(orden)
        else:
            # Para LONG y SHORT, primero abrir posición
            resultado = abrir_posicion(orden)
            
            # Si la posición se abrió exitosamente y hay stop loss, colocarlo
            if resultado.get("mensaje") == "Orden enviada correctamente" and orden.stop_loss:
                time.sleep(1)  # Esperar un momento para que se procese la primera orden
                stop_resultado = colocar_stop_loss_automatico(orden)
                resultado["stop_loss"] = stop_resultado
            
            # Si hay take profit, colocarlo también
            if resultado.get("mensaje") == "Orden enviada correctamente" and orden.take_profit:
                time.sleep(1)
                tp_resultado = colocar_take_profit_automatico(orden)
                resultado["take_profit"] = tp_resultado
                
            return resultado
    except Exception as e:
        return {"error": "Excepción al procesar orden", "detalle": str(e)}

def enviar_orden_binance(params):
    """Función auxiliar para enviar órdenes a Binance"""
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        API_SECRET.encode(),
        query_string.encode(),
        hashlib.sha256
    ).hexdigest()
    
    url = f"{BINANCE_URL}/fapi/v1/order?{query_string}&signature={signature}"
    headers = {"X-MBX-APIKEY": API_KEY}
    
    response = requests.post(url, headers=headers)
    
    if response.status_code == 200:
        return {"mensaje": "Orden enviada correctamente", "respuesta": response.json()}
    else:
        return {"error": "Fallo al enviar orden", "detalle": response.text}

def abrir_posicion(orden: Orden):
    """Función para abrir posiciones LONG o SHORT"""
    timestamp = int(time.time() * 1000)
    
    cantidad = calcular_cantidad(orden.simbolo, orden.entrada, orden.monto, orden.apalancamiento)
    
    if cantidad <= 0:
        return {"error": "Cantidad calculada inválida", "cantidad": cantidad, "detalles": {
            "simbolo": orden.simbolo,
            "entrada": orden.entrada,
            "monto": orden.monto,
            "apalancamiento": orden.apalancamiento
        }}
    
    params = {
        "symbol": orden.simbolo,
        "side": "BUY" if orden.tipo == "LONG" else "SELL",
        "type": "MARKET",
        "quantity": cantidad,
        "timestamp": timestamp
    }
    
    print(f"Enviando orden: {params}")
    return enviar_orden_binance(params)

def cerrar_posicion(orden: Orden):
    """Función para cerrar posiciones"""
    if orden.tipo == "CLOSE_ALL":
        return cerrar_todas_posiciones(orden.simbolo)
    
    # Obtener información de la posición actual
    posicion_info = obtener_posicion(orden.simbolo)
    if not posicion_info:
        return {"error": "No se pudo obtener información de la posición", "simbolo": orden.simbolo}
    
    posicion_amt = float(posicion_info['positionAmt'])
    print(f"Posición actual: {posicion_amt}")
    
    if posicion_amt == 0:
        return {"error": "No hay posición abierta para cerrar", "posicion_actual": posicion_amt}
    
    # Determinar la cantidad a cerrar
    if orden.cantidad:
        cantidad = min(orden.cantidad, abs(posicion_amt))  # No cerrar más de lo que tienes
    else:
        cantidad = abs(posicion_amt)  # Cerrar toda la posición
    
    # Aplicar cantidad mínima según el símbolo
    if "BTC" in orden.simbolo:
        cantidad = max(round(cantidad, 3), 0.001)
    elif "ETH" in orden.simbolo:
        cantidad = max(round(cantidad, 2), 0.01)
    else:
        cantidad = max(round(cantidad, 1), 0.1)
    
    print(f"Cantidad a cerrar: {cantidad}")
    
    # Determinar el lado de la orden de cierre
    if posicion_amt > 0:  # Posición LONG abierta
        side = "SELL"  # Vender para cerrar LONG
    else:  # Posición SHORT abierta  
        side = "BUY"   # Comprar para cerrar SHORT
    
    timestamp = int(time.time() * 1000)
    
    params = {
        "symbol": orden.simbolo,
        "side": side,
        "type": "MARKET",
        "quantity": cantidad,
        "reduceOnly": "true",
        "timestamp": timestamp
    }
    
    print(f"Parámetros de cierre: {params}")
    return enviar_orden_binance(params)

def cerrar_todas_posiciones(simbolo):
    """Cerrar todas las posiciones del símbolo"""
    posicion_info = obtener_posicion(simbolo)
    if not posicion_info:
        return {"error": "No se pudo obtener información de la posición"}
    
    posicion_amt = float(posicion_info['positionAmt'])
    
    if posicion_amt == 0:
        return {"mensaje": "No hay posiciones abiertas para cerrar"}
    
    timestamp = int(time.time() * 1000)
    
    params = {
        "symbol": simbolo,
        "side": "SELL" if posicion_amt > 0 else "BUY",
        "type": "MARKET",
        "quantity": abs(posicion_amt),
        "reduceOnly": "true",
        "timestamp": timestamp
    }
    
    return enviar_orden_binance(params)

def obtener_posicion(simbolo):
    """Obtener información de la posición actual"""
    try:
        timestamp = int(time.time() * 1000)
        params = {
            "timestamp": timestamp
        }
        
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            API_SECRET.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{BINANCE_URL}/fapi/v2/positionRisk?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": API_KEY}
        
        print(f"URL consulta posición: {url}")
        response = requests.get(url, headers=headers)
        print(f"Status code: {response.status_code}")
        print(f"Response: {response.text}")
        
        if response.status_code == 200:
            posiciones = response.json()
            for pos in posiciones:
                if pos['symbol'] == simbolo:
                    print(f"Posición encontrada: {pos}")
                    return pos
            print(f"Símbolo {simbolo} no encontrado en las posiciones")
            return None
        else:
            print(f"Error en API: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"Error obteniendo posición: {e}")
        return None

def colocar_stop_loss(orden: Orden):
    """Colocar stop loss manualmente"""
    if not orden.stop_loss:
        return {"error": "Precio de stop loss no especificado"}
    
    # Obtener posición actual
    posicion_info = obtener_posicion(orden.simbolo)
    if not posicion_info:
        return {"error": "No se pudo obtener información de la posición"}
    
    posicion_amt = float(posicion_info['positionAmt'])
    if posicion_amt == 0:
        return {"error": "No hay posición abierta para colocar stop loss"}
    
    timestamp = int(time.time() * 1000)
    cantidad = abs(posicion_amt)
    
    # Determinar el tipo de stop loss según la posición
    if posicion_amt > 0:  # Posición LONG
        side = "SELL"
        stop_price = orden.stop_loss
        if stop_price >= float(posicion_info['entryPrice']):
            return {"error": "Stop loss debe ser menor al precio de entrada para posición LONG"}
    else:  # Posición SHORT
        side = "BUY" 
        stop_price = orden.stop_loss
        if stop_price <= float(posicion_info['entryPrice']):
            return {"error": "Stop loss debe ser mayor al precio de entrada para posición SHORT"}
    
    params = {
        "symbol": orden.simbolo,
        "side": side,
        "type": "STOP_MARKET",
        "quantity": cantidad,
        "stopPrice": stop_price,
        "reduceOnly": "true",
        "timestamp": timestamp
    }
    
    print(f"Colocando stop loss: {params}")
    return enviar_orden_binance(params)

def colocar_stop_loss_automatico(orden: Orden):
    """Colocar stop loss automáticamente después de abrir posición"""
    orden_sl = Orden(
        simbolo=orden.simbolo,
        tipo="STOP_LOSS",
        stop_loss=orden.stop_loss
    )
    return colocar_stop_loss(orden_sl)

def colocar_take_profit_automatico(orden: Orden):
    """Colocar take profit automáticamente después de abrir posición"""
    posicion_info = obtener_posicion(orden.simbolo)
    if not posicion_info:
        return {"error": "No se pudo obtener información de la posición"}
    
    posicion_amt = float(posicion_info['positionAmt'])
    if posicion_amt == 0:
        return {"error": "No hay posición abierta"}
    
    timestamp = int(time.time() * 1000)
    cantidad = abs(posicion_amt)
    
    # Determinar el lado para take profit
    if posicion_amt > 0:  # Posición LONG
        side = "SELL"
    else:  # Posición SHORT  
        side = "BUY"
    
    params = {
        "symbol": orden.simbolo,
        "side": side,
        "type": "TAKE_PROFIT_MARKET",
        "quantity": cantidad,
        "stopPrice": orden.take_profit,
        "reduceOnly": "true",
        "timestamp": timestamp
    }
    
    print(f"Colocando take profit: {params}")
    return enviar_orden_binance(params)

def calcular_cantidad(simbolo, precio_entrada, monto_usdt, apalancamiento):
    if not precio_entrada or not monto_usdt or precio_entrada <= 0 or monto_usdt <= 0:
        print(f"Error: Valores inválidos - precio: {precio_entrada}, monto: {monto_usdt}")
        return 0
    
    cantidad = (monto_usdt * apalancamiento) / precio_entrada
    print(f"Calculando cantidad: ({monto_usdt} * {apalancamiento}) / {precio_entrada} = {cantidad}")
    
    # Aplicar filtros mínimos según el símbolo
    if "USDT" in simbolo:
        if "BTC" in simbolo:
            cantidad = max(cantidad, 0.001)  # Mínimo para BTCUSDT
            cantidad = round(cantidad, 3)
        elif "ETH" in simbolo:
            cantidad = max(cantidad, 0.01)   # Mínimo para ETHUSDT  
            cantidad = round(cantidad, 2)
        else:
            cantidad = max(cantidad, 0.1)    # Mínimo para otros pares
            cantidad = round(cantidad, 1)
    
    print(f"Cantidad final: {cantidad}")
    return cantidad

# Endpoint adicional para consultar posiciones
@app.get("/posicion/{simbolo}")
def consultar_posicion(simbolo: str):
    try:
        posicion = obtener_posicion(simbolo)
        if posicion:
            return {
                "simbolo": posicion['symbol'],
                "cantidad": posicion['positionAmt'],
                "precio_entrada": posicion['entryPrice'],
                "pnl": posicion['unRealizedProfit'],
                "porcentaje_pnl": posicion.get('percentage', '0')
            }
        else:
            return {"error": "No se pudo obtener la posición", "simbolo": simbolo}
    except Exception as e:
        return {"error": f"Excepción al consultar posición: {str(e)}", "simbolo": simbolo}

# Endpoint para consultar balance
@app.get("/balance")
def consultar_balance():
    try:
        timestamp = int(time.time() * 1000)
        params = {"timestamp": timestamp}
        
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(
            API_SECRET.encode(),
            query_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        url = f"{BINANCE_URL}/fapi/v2/balance?{query_string}&signature={signature}"
        headers = {"X-MBX-APIKEY": API_KEY}
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            return {"balance": response.json()}
        else:
            return {"error": "Fallo al obtener balance", "detalle": response.text}
    except Exception as e:
        return {"error": "Excepción al obtener balance", "detalle": str(e)}