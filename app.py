# backend/app.py
import os
from math import radians, cos, sin, sqrt, atan2

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import Config
from database import db
from models import Report, TrackPoint, PanicEvent


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Carpeta de uploads
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    CORS(app)

    with app.app_context():
        db.create_all()

    # -------- Utilidades --------

    def haversine(lat1, lon1, lat2, lon2):
        R = 6371.0
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c

    # -------- Healthcheck --------

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"ok": True, "message": "AlertaVecinal backend OK"})

    # -------- Crear reporte (con imagen + IA) --------

    @app.route("/api/reports", methods=["POST", "OPTIONS"])
    def create_report():
        # Preflight CORS
        if request.method == "OPTIONS":
            return ("", 200)

        """
        Crea un reporte nuevo.
        Espera form-data:
          - report_type (string)
          - description (string, opcional)
          - latitude (float)
          - longitude (float)
          - image (file, opcional)
          - plate_text (string, opcional)
        """
        data = request.form
        report_type = (data.get("report_type") or "").strip() or "emergencia"
        description = (data.get("description") or "").strip()
        plate_text = (data.get("plate_text") or "").strip() or None

        try:
            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Latitud/Longitud inválidas"}), 400

        image = request.files.get("image")
        image_path = None

        if image and image.filename:
            filename = image.filename or "evidencia.jpg"
            safe_name = filename.replace(" ", "_")
            upload_folder = app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_folder, exist_ok=True)
            full_path = os.path.join(upload_folder, safe_name)

            # Leemos los bytes una sola vez
            image_bytes = image.read()

            # Guardamos el archivo desde esos bytes
            with open(full_path, "wb") as f:
                f.write(image_bytes)

            # Ruta pública para el front
            image_path = f"/api/uploads/{safe_name}"

            # IA con bytes
            try:
                from ai_vision import analyze_image
                ai_info = analyze_image(image_bytes)
            except Exception as e:
                print("[AI] Error en analyze_image:", e)
                ai_info = {
                    "weapon_detected": False,
                    "risk_level": "bajo",
                    "ai_raw_summary": (
                        "Análisis IA (imagen): no se pudo procesar la evidencia. "
                        "Riesgo BAJO."
                    ),
                    "plate_text": None,
                }
        else:
            ai_info = {
                "weapon_detected": False,
                "risk_level": "bajo",
                "ai_raw_summary": "Análisis IA: sin imagen adjunta. Riesgo BAJO.",
                "plate_text": plate_text,
            }

        # texto de análisis IA (para pegarlo a la descripción y para el panel)
        analysis_text = ai_info.get("ai_raw_summary") or ""

        # si la IA (u otro módulo) devolvió patente, la usamos
        if ai_info.get("plate_text"):
            plate_text = ai_info["plate_text"]

        # 👉 AQUÍ copiamos el comportamiento viejo:
        # Descripción del usuario + salto de línea + "Análisis IA: ..."
        if analysis_text:
            if description:
                description_for_db = f"{description}\n{analysis_text}"
            else:
                description_for_db = analysis_text
        else:
            description_for_db = description

        report = Report(
            report_type=report_type,
            description=description_for_db,
            latitude=latitude,
            longitude=longitude,
            image_path=image_path,
            plate_text=plate_text,
            risk_level=ai_info.get("risk_level", "bajo"),
            has_weapon=ai_info.get("weapon_detected", False),
            has_vehicle=bool(plate_text),
            status="pendiente",
            source="ciudadano",
        )

        db.session.add(report)
        db.session.commit()

        # armar dict de respuesta coherente con lo que espera el front
        d = report.to_dict()
        d["weapon_detected"] = bool(report.has_weapon)

        # extra: si logramos separar la parte de IA, la mandamos como ai_raw_summary
        if analysis_text:
            d["ai_raw_summary"] = analysis_text

        return jsonify({"ok": True, "report": d}), 201

    # -------- Listar reportes ciudadanos (APP - recientes) --------

    @app.route("/api/reports", methods=["GET"])
    def list_reports():
        """
        Listado general de reportes (vista APP).
        Query params:
          - status (opcional)
          - limit (opcional, default 50)
        """
        status = request.args.get("status")
        limit = request.args.get("limit", type=int) or 50

        q = Report.query.order_by(Report.created_at.desc())
        if status:
            q = q.filter(Report.status == status)

        reports = []
        for r in q.limit(limit).all():
            d = r.to_dict()

            d["weapon_detected"] = bool(getattr(r, "has_weapon", False))

            # intentar derivar ai_raw_summary desde description si contiene "Análisis IA:"
            desc = d.get("description") or ""
            if "Análisis IA:" in desc:
                idx = desc.find("Análisis IA:")
                summary = desc[idx:].strip()
                d["ai_raw_summary"] = summary

            reports.append(d)

        return jsonify(
            {
                "ok": True,
                "data": reports,
                "items": reports,
                "reports": reports,
            }
        )

    # -------- Heatmap general --------

    @app.route("/api/heatmap", methods=["GET"])
    def heatmap():
        reports = Report.query.all()
        buckets = {}

        for r in reports:
            key = (round(r.latitude, 3), round(r.longitude, 3))
            buckets.setdefault(key, 0)
            buckets[key] += 1

        points = [
            {"lat": lat, "lng": lng, "count": count}
            for (lat, lng), count in buckets.items()
        ]
        return jsonify({"ok": True, "data": points})

    # -------- Reportes cercanos --------

    @app.route("/api/reports/nearby", methods=["GET"])
    def nearby_reports():
        try:
            lat = float(request.args.get("lat"))
            lng = float(request.args.get("lng"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "lat/lng requeridos"}), 400

        radius_km = request.args.get("radius_km", type=float) or 0.5

        out = []
        for r in Report.query.all():
            d = haversine(lat, lng, r.latitude, r.longitude)
            if d <= radius_km:
                rd = r.to_dict()
                rd["distance_km"] = d
                rd["weapon_detected"] = bool(getattr(r, "has_weapon", False))

                desc = rd.get("description") or ""
                if "Análisis IA:" in desc:
                    idx = desc.find("Análisis IA:")
                    summary = desc[idx:].strip()
                    rd["ai_raw_summary"] = summary

                out.append(rd)

        out.sort(key=lambda x: x["distance_km"])
        return jsonify({"ok": True, "data": out})

    # -------- Panel de autoridades: listar --------

    @app.route("/api/admin/reports", methods=["GET", "OPTIONS"])
    def admin_list_reports():
        # Preflight CORS
        if request.method == "OPTIONS":
            return ("", 200)

        """
        Listado para el panel de autoridades.
        Query params:
          - status (opcional)
        """
        status = request.args.get("status")

        q = Report.query.order_by(Report.created_at.desc())
        if status:
            q = q.filter(Report.status == status)

        reports = []
        for r in q.all():
            d = r.to_dict()

            d["weapon_detected"] = bool(getattr(r, "has_weapon", False))

            desc = d.get("description") or ""
            if "Análisis IA:" in desc:
                idx = desc.find("Análisis IA:")
                summary = desc[idx:].strip()
                d["ai_raw_summary"] = summary

            reports.append(d)

        return jsonify(
            {
                "ok": True,
                "data": reports,
                "items": reports,
                "reports": reports,
            }
        )

    # -------- Panel de autoridades: cambiar estado --------

    @app.route("/api/admin/reports/<int:report_id>/status", methods=["PATCH"])
    def change_status(report_id):
        report = Report.query.get_or_404(report_id)
        data = request.get_json(force=True)
        status = data.get("status")

        if status not in ("pendiente", "verificado", "falso"):
            return jsonify({"ok": False, "error": "Estado inválido"}), 400

        report.status = status
        db.session.commit()
        return jsonify({"ok": True, "report": report.to_dict()})

    # -------- Botón de pánico --------

    @app.route("/api/panic", methods=["POST"])
    def panic():
        data = request.get_json() or {}
        try:
            lat = float(data.get("latitude"))
            lng = float(data.get("longitude"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Coordenadas inválidas"}), 400

        under_duress = bool(data.get("under_duress"))
        mode = (data.get("mode") or "normal").strip() or "normal"
        user_id = data.get("user_id")

        report = Report(
            report_type="panico",
            description="Botón de pánico activado desde la app.",
            latitude=lat,
            longitude=lng,
            image_path=None,
            plate_text=None,
            risk_level="alto",
            has_weapon=False,
            has_vehicle=False,
            status="pendiente",
            source="panico",
        )
        db.session.add(report)
        db.session.commit()

        panic_event = PanicEvent(
            report_id=report.id,
            user_id=user_id,
            mode=mode,
            under_duress=under_duress,
            created_at=report.created_at,
        )
        db.session.add(panic_event)
        db.session.commit()

        return jsonify({"ok": True, "report": report.to_dict()})

    # -------- Servir imágenes --------

    @app.route("/api/uploads/<path:filename>", methods=["GET"])
    def get_upload(filename):
        # carpeta física donde se guardan
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
