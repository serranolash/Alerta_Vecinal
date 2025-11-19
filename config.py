import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "alerta_vecinal.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

class Config:
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = UPLOAD_FOLDER

    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")

    AI_VISION_ENDPOINT = os.environ.get("AI_VISION_ENDPOINT", "")
    AI_VISION_API_KEY = os.environ.get("AI_VISION_API_KEY", "")
