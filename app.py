# backend/app.py
import os
from math import radians, cos, sin, sqrt, atan2
from datetime import datetime, timedelta

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from config import Config
from database import db
from models import Report, TrackPoint, PanicEvent, HseqReport


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
        a = (
            sin(dlat / 2) ** 2
            + cos(radians(lat1))
            * cos(radians(lat2))
            * sin(dlon / 2) ** 2
        )
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

        # si la IA devolvió patente, la usamos
        if ai_info.get("plate_text"):
            plate_text = ai_info["plate_text"]

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

        d = report.to_dict()
        d["weapon_detected"] = bool(report.has_weapon)
        if analysis_text:
            d["ai_raw_summary"] = analysis_text

        return jsonify({"ok": True, "report": d}), 201

    # -------- Listar reportes ciudadanos (APP - recientes) --------

    @app.route("/api/reports", methods=["GET"])
    def list_reports():
        status = request.args.get("status")
        limit = request.args.get("limit", type=int) or 50

        q = Report.query.order_by(Report.created_at.desc())
        if status:
            q = q.filter(Report.status == status)

        reports = []
        for r in q.limit(limit).all():
            d = r.to_dict()
            d["weapon_detected"] = bool(getattr(r, "has_weapon", False))

            desc = d.get("description") or ""
            if "Análisis IA:" in desc:
                idx = desc.find("Análisis IA:")
                summary = desc[idx:].strip()
                d["ai_raw_summary"] = summary

            reports.append(d)

        return jsonify({"ok": True, "data": reports, "items": reports, "reports": reports})

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
        return jsonify({"ok": True, "data": out, "items": out, "reports": out})

    # -------- Panel de autoridades: listar --------

    @app.route("/api/admin/reports", methods=["GET", "OPTIONS"])
    def admin_list_reports():
        if request.method == "OPTIONS":
            return ("", 200)

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

        return jsonify({"ok": True, "data": reports, "items": reports, "reports": reports})

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

    # -------- Tracking de ruta de escape --------

    @app.route("/api/reports/<int:report_id>/track", methods=["POST"])
    def add_track_point(report_id):
        data = request.get_json(silent=True) or {}
        try:
            lat = float(data.get("latitude"))
            lng = float(data.get("longitude"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Latitud/Longitud inválidas"}), 400

        report = Report.query.get(report_id)
        if not report:
            return jsonify({"ok": False, "error": "Reporte no encontrado"}), 404

        tp = TrackPoint(report_id=report_id, latitude=lat, longitude=lng)
        db.session.add(tp)
        db.session.commit()

        return jsonify({"ok": True, "item": tp.to_dict()}), 201

    @app.route("/api/reports/<int:report_id>/track", methods=["GET"])
    def list_track_points(report_id):
        report = Report.query.get(report_id)
        if not report:
            return jsonify({"ok": False, "error": "Reporte no encontrado"}), 404

        points = (
            TrackPoint.query.filter_by(report_id=report_id)
            .order_by(TrackPoint.created_at.asc())
            .all()
        )
        return jsonify({"ok": True, "items": [p.to_dict() for p in points]})

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

    # -------- Módulo HSEQ: crear reporte --------

    @app.route("/api/hseq/reports", methods=["POST"])
    def create_hseq_report():
        data = request.form
        type_ = (data.get("type") or "otro").strip()
        area = (data.get("area") or "").strip()
        shift = (data.get("shift") or "").strip() or "dia"
        description = (data.get("description") or "").strip()

        lat = lng = None
        try:
            if data.get("latitude") and data.get("longitude"):
                lat = float(data.get("latitude"))
                lng = float(data.get("longitude"))
        except (TypeError, ValueError):
            # coordenadas opcionales
            pass

        image = request.files.get("image")
        image_path = None
        if image and image.filename:
            filename = image.filename or "hseq_evidencia.jpg"
            safe_name = "hseq_" + filename.replace(" ", "_")
            upload_folder = app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_folder, exist_ok=True)
            full_path = os.path.join(upload_folder, safe_name)
            image.save(full_path)
            image_path = f"/api/uploads/{safe_name}"

        # Heurística simple de riesgo según tipo
        if type_ == "accidente":
            risk_level = "alto"
        elif type_ in ("casi_accidente", "derrame"):
            risk_level = "medio"
        else:
            risk_level = "bajo"

        h = HseqReport(
            type=type_,
            area=area,
            shift=shift,
            description=description,
            latitude=lat,
            longitude=lng,
            image_path=image_path,
            risk_level=risk_level,
            status="abierto",
        )
        db.session.add(h)
        db.session.commit()

        return jsonify({"ok": True, "item": h.to_dict()}), 201

    # -------- Módulo HSEQ: listar reportes --------

    @app.route("/api/hseq/reports", methods=["GET"])
    def list_hseq_reports():
        reports = HseqReport.query.order_by(HseqReport.created_at.desc()).all()
        items = [r.to_dict() for r in reports]
        return jsonify({"ok": True, "items": items, "data": items})

    # -------- Módulo HSEQ: resumen dashboard --------

    @app.route("/api/hseq/summary", methods=["GET"])
    def hseq_summary():
        now = datetime.utcnow()
        since = now - timedelta(days=30)

        last_30 = HseqReport.query.filter(HseqReport.created_at >= since).all()
        total_last_30 = len(last_30)
        accidents_last_30 = sum(1 for r in last_30 if r.type == "accidente")
        near_misses_last_30 = sum(1 for r in last_30 if r.type == "casi_accidente")

        # Top áreas
        area_counts = {}
        for r in last_30:
            if r.area:
                area_counts[r.area] = area_counts.get(r.area, 0) + 1
        top_areas = sorted(
            [{"area": a, "count": c} for a, c in area_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        open_actions = HseqReport.query.filter(
            HseqReport.status.in_(["abierto", "en_progreso"])
        ).count()
        closed_actions = HseqReport.query.filter(
            HseqReport.status == "cerrado"
        ).count()
        overdue_actions = HseqReport.query.filter(
            HseqReport.status == "vencido"
        ).count()

        data = {
            "total_last_30": total_last_30,
            "accidents_last_30": accidents_last_30,
            "near_misses_last_30": near_misses_last_30,
            "top_areas": top_areas,
            "open_actions": open_actions,
            "closed_actions": closed_actions,
            "overdue_actions": overdue_actions,
        }
        return jsonify({"ok": True, "data": data})

    # -------- Servir imágenes --------

    @app.route("/api/uploads/<path:filename>", methods=["GET"])
    def get_upload(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
