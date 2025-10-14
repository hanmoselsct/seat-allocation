import os
import json
import time
from io import BytesIO
from functools import wraps
from flask import Flask, request, jsonify, render_template, session, send_file
from flask_cors import CORS
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine, text

# ========== 配置 ==========
DATABASE_URL = os.environ.get("DATABASE_URL")
SECRET_KEY = os.environ.get("SECRET_KEY", "changeme_secret")
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "changeme")

if DATABASE_URL:
    # Render 提供的 PostgreSQL 数据库
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    print("✅ 使用 PostgreSQL 数据库")
else:
    # 本地 SQLite
    engine = create_engine("sqlite:///database.db", connect_args={"check_same_thread": False})
    print("✅ 使用本地 SQLite 数据库")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)

# ========== 数据库初始化 ==========
with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS students (
            id SERIAL PRIMARY KEY,
            name TEXT,
            score INTEGER,
            volunteers TEXT,
            admitted TEXT,
            last_updated BIGINT
        )
    """))
    conn.commit()

# ========== 权限装饰器 ==========
def require_teacher(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("is_teacher"): return f(*args, **kwargs)
        data = request.get_json(silent=True) or {}
        if data.get("teacher_password") == TEACHER_PASSWORD:
            session["is_teacher"] = True
            return f(*args, **kwargs)
        return jsonify({"error": "teacher authentication required"}), 401
    return wrapper

# ========== 页面 ==========
@app.route("/")
def index_page():
    return render_template("index.html")

@app.route("/student")
def student_page():
    return render_template("student.html")

@app.route("/teacher")
def teacher_page():
    return render_template("teacher.html")

# ========== 学生提交 ==========
@app.route("/api/submit", methods=["POST"])
def submit():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    try:
        score = int(data.get("score", -1))
    except:
        score = -1
    volunteers = data.get("volunteers") or []
    if not name or score < 0 or not isinstance(volunteers, list) or len(volunteers) == 0:
        return jsonify({"error": "invalid data"}), 400

    now = int(time.time())
    with engine.begin() as conn:
        res = conn.execute(text("SELECT id FROM students WHERE name=:name"), {"name": name}).fetchone()
        if res:
            conn.execute(text("""
                UPDATE students
                SET score=:score, volunteers=:volunteers, admitted=NULL, last_updated=:t
                WHERE id=:id
            """), {"score": score, "volunteers": json.dumps(volunteers, ensure_ascii=False), "t": now, "id": res.id})
        else:
            conn.execute(text("""
                INSERT INTO students (name,score,volunteers,last_updated)
                VALUES (:name,:score,:volunteers,:t)
            """), {"name": name, "score": score, "volunteers": json.dumps(volunteers, ensure_ascii=False), "t": now})
    return jsonify({"ok": True})

# ========== 老师端 ==========
@app.route("/api/students", methods=["POST"])
@require_teacher
def all_students():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM students ORDER BY score DESC, last_updated ASC")).mappings().all()
        data = [{"name": r["name"], "score": r["score"],
                 "volunteers": json.loads(r["volunteers"]),
                 "admitted": r["admitted"]} for r in rows]
    return jsonify({"students": data})

@app.route("/api/reset", methods=["POST"])
@require_teacher
def reset_all():
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM students"))
    return jsonify({"ok": True})

@app.route("/api/assign", methods=["POST"])
@require_teacher
def assign():
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT * FROM students ORDER BY score DESC, last_updated ASC")).mappings().all()
        students = [{"id": r["id"], "name": r["name"], "score": r["score"],
                     "volunteers": json.loads(r["volunteers"])} for r in rows]

        seat_quota = {}
        for s in students:
            for v in s["volunteers"]:
                seat_quota.setdefault(v, 2)

        for s in students:
            admitted = None
            for v in s["volunteers"]:
                if seat_quota.get(v, 0) > 0:
                    admitted = v
                    seat_quota[v] -= 1
                    break
            conn.execute(text("UPDATE students SET admitted=:a WHERE id=:i"), {"a": admitted, "i": s["id"]})
    return jsonify({"ok": True})

@app.route("/api/teacher_login", methods=["POST"])
def teacher_login():
    pw = (request.get_json() or {}).get("password")
    if pw == TEACHER_PASSWORD:
        session["is_teacher"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "wrong password"}), 401

# ========== 老师座位图 ==========
@app.route("/seatmap.png")
@require_teacher
def seatmap():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name,admitted FROM students WHERE admitted IS NOT NULL")).mappings().all()
    assigned = {}
    for r in rows:
        assigned.setdefault(r["admitted"], []).append(r["name"])

    groups = [("第一组",7),("第二组",8),("第三组",8),("第四组",7)]
    width, height, padding = 1200, 600, 50
    img = Image.new("RGB", (width, height), (245,250,255))
    draw = ImageDraw.Draw(img)

    font_path = os.path.join(app.static_folder, "fonts", "NotoSansSC-Regular.otf")
    if os.path.exists(font_path):
        font_title = ImageFont.truetype(font_path, 20)
        font_seat = ImageFont.truetype(font_path, 14)
    else:
        font_title = ImageFont.load_default()
        font_seat = ImageFont.load_default()

    group_width = (width - padding*2) / len(groups)
    for gi, (gname, rows) in enumerate(groups):
        gx = padding + gi * group_width
        draw.text((gx + 40, padding - 25), gname, fill=(30,111,186), font=font_title)
        for r in range(1, rows + 1):
            seat_name = f"{gname}第{r}排"
            bx1, by1 = gx, padding + (r - 1) * 30
            bx2, by2 = bx1 + group_width - 20, by1 + 24
            names = assigned.get(seat_name, [])
            fill = (255,255,255)
            if len(names)==1: fill=(255,230,150)
            if len(names)==2: fill=(120,200,120)
            draw.rectangle([(bx1,by1),(bx2,by2)], fill=fill, outline=(180,180,180))
            draw.text((bx1+5, by1+4), f"{r}排 ({len(names)}/2)", fill=(0,0,0), font=font_seat)
            if names:
                draw.text((bx1+80, by1+4), "、".join(names), fill=(40,40,40), font=font_seat)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
