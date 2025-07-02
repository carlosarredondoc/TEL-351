from machine import Pin, ADC
import time
import network
import urequests

# --- PARÁMETROS DE CONFIGURACIÓN ---
WIFI_SSID = "SSID"
WIFI_PASSWORD = "PASSWORD_WIFI"
BASE_URL = "https://api.thingspeak.com/update"
API_KEY = "API_KEY_THINGSPEAK"

FIELD_NAME_PROXIMITY = "field1"
FIELD_NAME_CURRENT = "field2"
FIELD_NAME_POWER = "field3"

UPDATE_INTERVALO_SEG = 30
VOLTAJE_REFERENCIA = 225
BURDEN_RESISTOR = 31.8

# --- PARÁMETROS PARA FILTRADO Y LÓGICA ---
NUM_MUESTRAS = 5 
DELAY_ENTRE_MUESTRAS_MS = 50

UMBRAL_ENTRADA_OCUPADO = 30 # cm, para cambiar de Disponible a Ocupado
UMBRAL_SALIDA_OCUPADO = 40  # cm, para cambiar de Ocupado a Disponible

# --- INICIALIZACIÓN DE HARDWARE ---
trig = Pin(17, Pin.OUT)
echo = Pin(16, Pin.IN, Pin.PULL_DOWN)
adc_current = ADC(28)

def conectar_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f'Conectando a la red {WIFI_SSID}...')
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        max_wait = 15
        while max_wait > 0:
            if wlan.status() < 0 or wlan.status() >= 3: break
            max_wait -= 1; print('.', end=''); time.sleep(1)
    if wlan.isconnected():
        print(f'\nConexión WiFi exitosa. IP: {wlan.ifconfig()[0]}')
        return True
    else:
        print("\nFallo en la conexión WiFi.")
        return False

def enviar_datos(data):
    proximity = data.get('proximity', 0)
    current = data.get('current_A', 0)
    power = data.get('power_W', 0)
    url_final = f"{BASE_URL}?api_key={API_KEY}&{FIELD_NAME_CURRENT}={current}&{FIELD_NAME_PROXIMITY}={proximity}&{FIELD_NAME_POWER}={power}"
    print(f"-> Estado: {data.get('status', 'N/A')} | Enviando: current={current}, proximity={proximity}, power={power}")
    try:
        response = urequests.get(url_final)
        print(f"<- Respuesta de ThingSpeak: {response.status_code}")
        response.close()
    except Exception as e: print(f"!! Error al enviar datos: {e}")

def truncar_decimales(numero_original, digitos):
    factor = 10**digitos
    return int(numero_original * factor) / factor

def _medir_corriente_raw():
    raw = adc_current.read_u16()
    voltaje = raw * (3.3 / 65535)
    corriente = voltaje / BURDEN_RESISTOR
    return truncar_decimales(corriente, 3)

def _medir_distancia_raw():
    trig.value(0)
    time.sleep_us(5)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)
    
    timeout_start = time.ticks_us()
    pulse_start = 0
    while echo.value() == 0:
        pulse_start = time.ticks_us()
        if time.ticks_diff(pulse_start, timeout_start) > 30000: # 30ms timeout
            return -1

    timeout_start = time.ticks_us()
    pulse_end = 0
    while echo.value() == 1:
        pulse_end = time.ticks_us()
        if time.ticks_diff(pulse_end, timeout_start) > 30000: # 30ms timeout
            return -1

    if pulse_start == 0 or pulse_end == 0:
        return -1
        
    pulse_duration = time.ticks_diff(pulse_end, pulse_start)
    distance = (pulse_duration * 17165) / 1000000
    
    if 2 < distance < 400:
        return round(distance, 0)
    else:
        return -1

def medir_distancia_filtrada(num_muestras=NUM_MUESTRAS):
    lecturas = []
    for _ in range(num_muestras):
        lectura = _medir_distancia_raw()
        if lectura > 0:
            lecturas.append(lectura)
        time.sleep_ms(DELAY_ENTRE_MUESTRAS_MS)
    
    if not lecturas: return 0
    lecturas.sort()
    return lecturas[len(lecturas) // 2]

def medir_corriente_filtrada(num_muestras=NUM_MUESTRAS):
    lecturas = []
    for _ in range(num_muestras):
        lecturas.append(_medir_corriente_raw())
        time.sleep_ms(DELAY_ENTRE_MUESTRAS_MS)
        
    if not lecturas: return 0.0
    lecturas.sort()
    return lecturas[len(lecturas) // 2]


if not conectar_wifi():
    print("No se pudo conectar. Reiniciando en 15s...")
    time.sleep(15)
    machine.reset()

esta_ocupado = False
tiempo_desde_ultimo_envio = 0

while True:
    distancia = medir_distancia_filtrada()
    corriente = medir_corriente_filtrada()
    potencia = truncar_decimales(corriente * VOLTAJE_REFERENCIA, 3)

    if distancia < UMBRAL_ENTRADA_OCUPADO:
        esta_ocupado = True
    elif distancia > UMBRAL_SALIDA_OCUPADO:
        esta_ocupado = False
    
    estado_texto = "Ocupado" if esta_ocupado else "Disponible"

    print(f'Dist: {distancia:.1f} cm | Estado: {estado_texto} | Corriente: {corriente:.3f} A | Potencia: {potencia:.3f} W')

    if tiempo_desde_ultimo_envio >= UPDATE_INTERVALO_SEG:
        print("--- Es hora de enviar datos a la nube ---")
        
        datos_a_enviar = {
            "proximity": 1 if esta_ocupado else 0,
            "current_A": corriente,
            "power_W": potencia,
            "status": estado_texto
        }
        
        enviar_datos(datos_a_enviar)
        tiempo_desde_ultimo_envio = 0
    
    time.sleep(1)
    tiempo_desde_ultimo_envio += 1