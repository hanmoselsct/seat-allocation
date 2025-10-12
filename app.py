import os
import sqlite3
import json
import time
from functools import wraps
from flask import Flask, request, jsonify, g, render_template, session, send_file
from flask_cors import CORS
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# --- 配置 ---
DATABASE = os.path.join(os.getcwd(), "database.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "changeme_secret")
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "changeme")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)

# ---------- 数据库 ----------
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    c = db.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        score INTEGER,
        volunteers TEXT,
        admitted TEXT,
        last_updated INTEGER
    )
    """)
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db: db.close()

with app.app_context():
    init_db()

# ---------- 权限 ----------
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

# ---------- 页面 ----------
@app.route("/")
def index_page():
    return render_template("index.html")

@app.route("/student")
def student_page():
    return render_template("student.html")

@app.route("/teacher")
def teacher_page():
    return render_template("teacher.html")

# ---------- 学生提交 ----------
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

    db = get_db()
    c = db.cursor()
    now = int(time.time())
    c.execute("SELECT id FROM students WHERE name=?", (name,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE students SET score=?, volunteers=?, admitted=NULL, last_updated=? WHERE id=?",
                  (score, json.dumps(volunteers, ensure_ascii=False), now, row["id"]))
    else:
        c.execute("INSERT INTO students (name,score,volunteers,last_updated) VALUES (?,?,?,?)",
                  (name, score, json.dumps(volunteers, ensure_ascii=False), now))
    db.commit()
    return jsonify({"ok": True})

# ---------- 老师端 ----------
@app.route("/api/students", methods=["POST"])
@require_teacher
def all_students():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    rows = c.fetchall()
    return jsonify({"students": [
        {"name": r["name"], "score": r["score"],
         "volunteers": json.loads(r["volunteers"]),
         "admitted": r["admitted"]} for r in rows
    ]})

@app.route("/api/reset", methods=["POST"])
@require_teacher
def reset_all():
    db = get_db()
    db.execute("DELETE FROM students")
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/assign", methods=["POST"])
@require_teacher
def assign():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    students = [{"id": r["id"], "name": r["name"], "score": r["score"],
                 "volunteers": json.loads(r["volunteers"])} for r in c.fetchall()]

    seat_quota = {}
    for s in students:
        for v in s["volunteers"]:
            seat_quota.setdefault(v, 2)

    process = []
    for s in students:
        admitted = None
        for v in s["volunteers"]:
            if seat_quota.get(v, 0) > 0:
                admitted = v
                seat_quota[v] -= 1
                process.append({"student": s["name"], "score": s["score"],
                                "volunteer": v, "result": "分配成功"})
                break
        c.execute("UPDATE students SET admitted=? WHERE id=?", (admitted, s["id"]))
    db.commit()
    return jsonify({"ok": True, "process": process})

@app.route("/api/teacher_login", methods=["POST"])
def teacher_login():
    pw = (request.get_json() or {}).get("password")
    if pw == TEACHER_PASSWORD:
        session["is_teacher"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "wrong password"}), 401

@app.route("/seatmap.png")
@require_teacher
def seatmap():
    # 老师查看录取座位图
    db = get_db()
    c = db.cursor()
    c.execute("SELECT name,admitted FROM students WHERE admitted IS NOT NULL")
    assigned = {}
    for r in c.fetchall():
        assigned.setdefault(r["admitted"], []).append(r["name"])

    groups = [("第一组",7),("第二组",8),("第三组",8),("第四组",7)]
    width = 1200; height = 600; padding = 50
    img = Image.new("RGB", (width, height), (245,250,255))
    draw = ImageDraw.Draw(img)

    # 中文字体
    font_path = os.path.join(app.static_folder, "fonts", "楷体_GB2312.ttf")
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
            bx1 = gx; by1 = padding + (r - 1) * 30
            bx2 = bx1 + group_width - 20; by2 = by1 + 24
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
