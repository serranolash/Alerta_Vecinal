import unicodedata

def _normalize(text: str) -> str:
    """
    Pasa a minúsculas y quita acentos para comparar mejor.
    Ej: 'Robó con pistola' -> 'robo con pistola'
    """
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return text


def analyze_text(description: str) -> dict:
    """
    Analiza el texto de la denuncia y devuelve:
    - has_weapon: bool
    - has_vehicle: bool
    - risk_level: 'bajo' | 'medio' | 'alto'
    - ai_raw_summary: texto corto con la interpretación
    - ai_confidence: número entre 0 y 1
    """
    raw_text = description or ""
    text = _normalize(raw_text)

    # Palabras clave por grupo (usamos raíces para que coincida 'robaron', 'robó', etc.)
    WEAPON_KEYWORDS = [
        "arma", "pistola", "revolver", "revolv", "cuchill", "tiro", "dispar",
        "fusil", "escopet"
    ]
    VEHICLE_KEYWORDS = [
        "auto", "moto", "camionet", "vehicul", "coche", "taxi", "remis",
        "camion", "furgon", "pick up", "pickup"
    ]
    KIDNAP_KEYWORDS = [
        "secuest", "rapt", "privacion de la libertad", "levantar", "levantaron"
    ]
    ROBBERY_KEYWORDS = [
        "robo", "robar", "robaron", "rob", "afano", "choreo", "chorro",
        "asalto", "asalt", "hurto", "arrebato"
    ]
    VIOLENCE_KEYWORDS = [
        "violenc", "golpe", "golp", "pelea", "agres", "discut", "ataque"
    ]

    def contains_any(words):
        return any(w in text for w in words)

    has_weapon = contains_any(WEAPON_KEYWORDS)
    has_vehicle = contains_any(VEHICLE_KEYWORDS)

    mentions_kidnap = contains_any(KIDNAP_KEYWORDS)
    mentions_robbery = contains_any(ROBBERY_KEYWORDS)
    mentions_violence = contains_any(VIOLENCE_KEYWORDS)

    # --- Cálculo del nivel de riesgo ---
    risk_level = "bajo"

    # Casos más graves
    if has_weapon and has_vehicle:
        risk_level = "alto"
    elif has_weapon and (mentions_robbery or mentions_violence or mentions_kidnap):
        risk_level = "alto"
    elif mentions_kidnap:
        risk_level = "alto"
    # Casos intermedios
    elif mentions_robbery or mentions_violence:
        risk_level = "medio"

    # --- Mensaje de resumen automático ---
    if risk_level == "alto":
        summary = "Texto indica posible situación de ALTO riesgo (arma/secuestro/robo grave)."
        confidence = 0.8
    elif risk_level == "medio":
        summary = "Texto indica incidente relevante, riesgo MEDIO (robo/violencia sin arma clara)."
        confidence = 0.65
    else:
        summary = "Texto sin indicadores claros de violencia grave (riesgo BAJO)."
        confidence = 0.45

    return {
        "has_weapon": has_weapon,
        "has_vehicle": has_vehicle,
        "risk_level": risk_level,
        "ai_raw_summary": summary,
        "ai_confidence": confidence,
    }


def analyze_image(image_path: str | None) -> dict:
    """
    Stub de análisis de imagen.
    Más adelante se conecta a un modelo de visión (OpenAI, Roboflow, etc.).
    De momento devuelve valores neutros para no romper el flujo.
    """
    if not image_path:
        return {
            "has_weapon": False,
            "has_vehicle": False,
            "plate_text": None,
            "risk_boost": None,
            "ai_raw_summary": None,
            "ai_confidence": 0.0,
        }

    # Aquí podrías poner una lógica simplificada basada en el nombre del archivo
    # o dejarlo neutro hasta integrar un modelo real.
    return {
        "has_weapon": False,
        "has_vehicle": False,
        "plate_text": None,
        "risk_boost": None,
        "ai_raw_summary": None,
        "ai_confidence": 0.0,
    }
