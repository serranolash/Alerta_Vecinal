from datetime import datetime
from database import db

class Report(db.Model):
    __tablename__ = "reports"

    id = db.Column(db.Integer, primary_key=True)
    report_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    image_path = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    risk_level = db.Column(db.String(20), default="desconocido")
    has_weapon = db.Column(db.Boolean, default=False)
    has_vehicle = db.Column(db.Boolean, default=False)
    plate_text = db.Column(db.String(32), nullable=True)

    status = db.Column(db.String(20), default="pendiente")
    source = db.Column(db.String(20), default="ciudadano")

    ai_raw_summary = db.Column(db.Text, nullable=True)
    ai_confidence = db.Column(db.Float, default=0.0)

    def to_dict(self):
        return {
            "id": self.id,
            "report_type": self.report_type,
            "description": self.description,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "image_path": self.image_path,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "risk_level": self.risk_level,
            "has_weapon": self.has_weapon,
            "has_vehicle": self.has_vehicle,
            "plate_text": self.plate_text,
            "status": self.status,
            "source": self.source,
            "ai_raw_summary": self.ai_raw_summary,
            "ai_confidence": self.ai_confidence,
        }


class TrackPoint(db.Model):
    __tablename__ = "track_points"

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id"), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    report = db.relationship("Report", backref=db.backref("track_points", lazy=True))

    def to_dict(self):
        return {
            "id": self.id,
            "report_id": self.report_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
    

from database import db

class PanicEvent(db.Model):
    __tablename__ = "panic_events"

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("reports.id"), nullable=False)
    user_id = db.Column(db.Integer, nullable=True)
    mode = db.Column(db.String(20), default="normal")  # normal | silent
    under_duress = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, nullable=False)

    report = db.relationship("Report", backref="panic_event", uselist=False)



class HseqReport(db.Model):
    __tablename__ = "hseq_reports"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)          # accidente, casi_accidente, etc.
    area = db.Column(db.String(120))                         # Planta / unidad
    shift = db.Column(db.String(20))                         # dia / tarde / noche
    description = db.Column(db.Text)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    image_path = db.Column(db.String(255))
    risk_level = db.Column(db.String(20), default="medio")   # alto / medio / bajo
    status = db.Column(db.String(20), default="abierto")     # abierto / en_progreso / cerrado / vencido

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "area": self.area,
            "shift": self.shift,
            "description": self.description,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "image_path": self.image_path,
            "risk_level": self.risk_level,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }        
