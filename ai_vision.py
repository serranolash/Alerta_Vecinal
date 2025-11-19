# backend/ai_vision.py
import os
import requests
from typing import Dict, Literal, Tuple, Optional

# === Roboflow (armas) ===
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY")
ROBOFLOW_MODEL_ID = os.getenv("ROBOFLOW_MODEL_ID", "gun-trmre-usutd/3")
ROBOFLOW_API_URL = os.getenv("ROBOFLOW_API_URL", "https://detect.roboflow.com")

# === Plate Recognizer (patentes) ===
PLATE_API_TOKEN = os.getenv("PLATERECOGNIZER_API_TOKEN")
PLATE_API_URL = os.getenv(
    "PLATERECOGNIZER_API_URL",
    "https://api.platerecognizer.com/v1/plate-reader/",
)

RiskLevel = Literal["alto", "medio", "bajo"]


def _debug_env():
    """
    Imprime en logs qué ve el backend respecto a las variables de IA.
    NO imprime los valores completos de las keys, solo si existen.
    """
    print(
        "[AI_DEBUG] ROBOFLOW_API_KEY presente:",
        ROBOFLOW_API_KEY is not None and ROBOFLOW_API_KEY != "",
    )
    print("[AI_DEBUG] ROBOFLOW_MODEL_ID:", repr(ROBOFLOW_MODEL_ID))
    print(
        "[AI_DEBUG] PLATERECOGNIZER_API_TOKEN presente:",
        PLATE_API_TOKEN is not None and PLATE_API_TOKEN != "",
    )
    print("[AI_DEBUG] PLATERECOGNIZER_API_URL:", repr(PLATE_API_URL))


# Llamamos al debug una sola vez al importar el módulo
_debug_env()


# ---------------- Roboflow: detección de armas ----------------

def call_roboflow_hosted(image_bytes: bytes) -> Dict:
    """
    Llama al Hosted Model de Roboflow usando BYTES (como los envía create_report).
    """
    if not ROBOFLOW_API_KEY or not ROBOFLOW_MODEL_ID:
        # Log más explícito para saber qué llegó exactamente
        print(
            "[AI_ERROR] Variables de entorno IA incompletas. "
            f"ROBOFLOW_API_KEY={repr(ROBOFLOW_API_KEY)}, "
            f"ROBOFLOW_MODEL_ID={repr(ROBOFLOW_MODEL_ID)}"
        )
        raise RuntimeError(
            "Faltan ROBOFLOW_API_KEY o ROBOFLOW_MODEL_ID en variables de entorno."
        )

    params = {
        "api_key": ROBOFLOW_API_KEY,
        "format": "json",
    }

    files = {
        "file": ("image.jpg", image_bytes, "application/octet-stream"),
    }

    resp = requests.post(
        f"{ROBOFLOW_API_URL}/{ROBOFLOW_MODEL_ID}",
        params=params,
        files=files,
        timeout=20,
    )

    print("[AI] Roboflow status:", resp.status_code, resp.text[:400])
    resp.raise_for_status()
    return resp.json()


def compute_risk_and_summary(pred_json: Dict) -> Tuple[RiskLevel, bool, str]:
    """
    A partir de las predicciones del modelo devuelve:
      - risk_level
      - weapon_detected (bool)
      - ai_raw_summary (texto para el panel)
    """
    detections = pred_json.get("predictions") or []

    if not detections:
        return (
            "bajo",
            False,
            "Análisis IA (imagen): no se detectaron armas. Riesgo BAJO.",
        )

    max_conf = 0.0
    weapon_detected = False

    for det in detections:
        label = str(det.get("class", "")).lower()
        conf = float(det.get("confidence", 0.0))
        if label in ("handgun", "gun", "pistol", "revolver"):
            weapon_detected = True
            if conf > max_conf:
                max_conf = conf

    if not weapon_detected:
        # Hubo detecciones, pero ninguna arma
        return (
            "bajo",
            False,
            "Análisis IA (imagen): se detectaron objetos, pero no armas claras. Riesgo BAJO.",
        )

    # Hay arma
    if max_conf >= 0.8:
        risk_level: RiskLevel = "alto"
        summary = (
            "Análisis IA (imagen): se detectó al menos un arma de fuego con alta confianza. "
            "Riesgo ALTO."
        )
    elif max_conf >= 0.5:
        risk_level = "medio"
        summary = (
            "Análisis IA (imagen): se detectó posible arma de fuego con confianza media. "
            "Riesgo MEDIO."
        )
    else:
        risk_level = "bajo"
        summary = (
            "Análisis IA (imagen): detecciones poco claras; se considera Riesgo BAJO."
        )

    return risk_level, weapon_detected, summary


# ---------------- Plate Recognizer: detección de patentes ----------------

def call_plate_recognizer(image_bytes: bytes) -> Optional[Dict]:
    """
    Llama a la API de Plate Recognizer para leer patentes.
    Devuelve el JSON o None si no hay token/config.
    """
    if not PLATE_API_TOKEN:
        print("[PLATE] Token no configurado; se omite lectura de patentes.")
        return None

    headers = {
        "Authorization": f"Token {PLATE_API_TOKEN}",
    }
    files = {
        "upload": ("image.jpg", image_bytes, "application/octet-stream"),
    }

    resp = requests.post(
        PLATE_API_URL,
        headers=headers,
        files=files,
        timeout=20,
    )
    print("[PLATE] status:", resp.status_code, resp.text[:400])
    resp.raise_for_status()
    return resp.json()


def extract_best_plate(pr_json: Dict) -> Optional[str]:
    """
    Extrae la mejor patente (por score) del JSON de Plate Recognizer.
    """
    results = pr_json.get("results") or []
    if not results:
        return None

    best = max(results, key=lambda r: r.get("score", 0.0))
    plate = best.get("plate")
    if not plate:
        return None

    # Normalizamos a mayúsculas (ej: abc123 -> ABC123)
    return plate.upper()


# ---------------- Orquestador principal: analyze_image ----------------

def analyze_image(image_bytes: bytes) -> Dict:
    """
    Función principal usada por create_report.
    Hace:
      - Roboflow para armas (riesgo).
      - Plate Recognizer para patentes (si hay token).
    Devuelve:
      - risk_level
      - weapon_detected
      - ai_raw_summary (texto para AdminReportTable.jsx)
      - roboflow (payload crudo, opcional)
      - plate_text (ej: ABC123)
      - plate_raw (payload crudo de Plate Recognizer, opcional)
    """
    # --- 1) Roboflow: armas ---
    try:
        rf_result = call_roboflow_hosted(image_bytes)
        risk_level, weapon_detected, summary = compute_risk_and_summary(rf_result)
    except Exception as e:
        print("[AI] Error llamando a Roboflow Hosted:", e)
        rf_result = None
        risk_level = "bajo"
        weapon_detected = False
        summary = (
            "Análisis IA (imagen): no se pudo procesar la evidencia. Riesgo BAJO."
        )

    # --- 2) Plate Recognizer: patentes ---
    plate_text = None
    plate_raw = None
    try:
        pr_json = call_plate_recognizer(image_bytes)
        if pr_json:
            plate_raw = pr_json
            plate_text = extract_best_plate(pr_json)
    except Exception as e:
        print("[PLATE] Error llamando a Plate Recognizer:", e)

    # Si detectamos patente, añadimos al texto de resumen
    if plate_text:
        summary = f"{summary} Patente detectada: {plate_text}."

    return {
        "risk_level": risk_level,
        "weapon_detected": weapon_detected,
        "ai_raw_summary": summary,
        "roboflow": rf_result,
        "plate_text": plate_text,
        "plate_raw": plate_raw,
    }
