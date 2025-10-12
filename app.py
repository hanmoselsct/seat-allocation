import os
import sqlite3
import json
import time
from functools import wraps
from flask import Flask, request, jsonify, g, render_template, session, send_file, abort
from flask_cors import CORS
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

# 配置
DATABASE = os.path.join(os.getcwd(), "database.db")
SECRET_KEY = os.environ.get("SECRET_KEY", "changeme_secret")
TEACHER_PASSWORD = os.environ.get("TEACHER_PASSWORD", "changeme")

app = Flask(__name__, static_folder='static', template_folder='templates')
app.config['SECRET_KEY'] = SECRET_KEY
CORS(app, supports_credentials=True)

# --- DB 工具 ---
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

# --- 权限装饰器 ---
def require_teacher(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # session 验证
        if session.get("is_teacher"):
            return f(*args, **kwargs)
        # 也接受一次性密码（方便 API 调试）
        data = request.get_json(silent=True) or {}
        if data.get("teacher_password") == TEACHER_PASSWORD:
            session["is_teacher"] = True
            return f(*args, **kwargs)
        return jsonify({"error":"teacher authentication required"}), 401
    return wrapper

# ---------- 页面路由 ----------
@app.route("/")
def index():
    # 首页入口（会重定向到 templates/index.html）
    return render_template("index.html")

@app.route("/student")
def student_page():
    return render_template("student.html")

@app.route("/teacher")
def teacher_page():
    return render_template("teacher.html")

# ---------- API: 提交 / 查询 ----------
@app.route("/api/submit", methods=["POST"])
def api_submit():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    try:
        score = int(data.get("score", -1))
    except:
        score = -1
    volunteers = data.get("volunteers") or []

    if not name:
        return jsonify({"error":"name required"}), 400
    if score < 0:
        return jsonify({"error":"score invalid"}), 400
    if not isinstance(volunteers, list) or len(volunteers) == 0:
        return jsonify({"error":"volunteers list required"}), 400

    db = get_db()
    c = db.cursor()
    now = int(time.time())
    c.execute("SELECT id FROM students WHERE name = ?", (name,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE students SET score=?, volunteers=?, admitted=NULL, last_updated=? WHERE id=?",
                  (score, json.dumps(volunteers, ensure_ascii=False), now, row["id"]))
    else:
        c.execute("INSERT INTO students (name, score, volunteers, last_updated) VALUES (?,?,?,?)",
                  (name, score, json.dumps(volunteers, ensure_ascii=False), now))
    db.commit()
    return jsonify({"ok":True})

@app.route("/api/student", methods=["GET"])
def api_get_student():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error":"name parameter required"}), 400
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students WHERE name = ?", (name,))
    r = c.fetchone()
    if not r:
        return jsonify({"found": False})
    return jsonify({
        "found": True,
        "id": r["id"],
        "name": r["name"],
        "score": r["score"],
        "volunteers": json.loads(r["volunteers"]),
        "admitted": r["admitted"]
    })

# ---------- API: 老师操作 ----------
@app.route("/api/students", methods=["GET"])
@require_teacher
def api_get_all_students():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    rows = c.fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "name": r["name"],
            "score": r["score"],
            "volunteers": json.loads(r["volunteers"]),
            "admitted": r["admitted"]
        })
    return jsonify({"students": out})

@app.route("/api/reset", methods=["POST"])
@require_teacher
def api_reset():
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM students")
    db.commit()
    return jsonify({"ok":True})

@app.route("/api/assign", methods=["POST"])
@require_teacher
def api_assign():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM students ORDER BY score DESC, last_updated ASC")
    rows = c.fetchall()
    students = []
    for r in rows:
        students.append({
            "id": r["id"],
            "name": r["name"],
            "score": r["score"],
            "volunteers": json.loads(r["volunteers"])
        })

    # 每排容量 2
    seat_quota = {}
    for s in students:
        for v in s["volunteers"]:
            seat_quota.setdefault(v, 2)

    process_log = []
    for s in students:
        admitted = None
        for vol in s["volunteers"]:
            if seat_quota.get(vol, 0) > 0:
                admitted = vol
                seat_quota[vol] -= 1
                process_log.append({
                    "student": s["name"],
                    "score": s["score"],
                    "volunteer": vol,
                    "result": "分配成功"
                })
                break
        c.execute("UPDATE students SET admitted = ? WHERE id = ?", (admitted, s["id"]))
    db.commit()

    c.execute("SELECT name, admitted FROM students ORDER BY name ASC")
    results = [{"name": r["name"], "admitted": r["admitted"]} for r in c.fetchall()]
    return jsonify({"ok":True, "process": process_log, "results": results})

@app.route("/api/results", methods=["GET"])
def api_results():
    db = get_db()
    c = db.cursor()
    c.execute("SELECT name, score, admitted FROM students ORDER BY score DESC")
    rows = c.fetchall()
    out = [{"name": r["name"], "score": r["score"], "admitted": r["admitted"]} for r in rows]
    return jsonify({"results": out})

@app.route("/api/teacher_login", methods=["POST"])
def api_teacher_login():
    data = request.get_json() or {}
    pw = data.get("password", "")
    if pw == TEACHER_PASSWORD:
        session["is_teacher"] = True
        return jsonify({"ok":True})
    return jsonify({"error":"wrong password"}), 401

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("is_teacher", None)
    return jsonify({"ok":True})

# ---------- 生成座位分布图（PNG） ----------
# 参数：
#   mode=public -> 不显示学生名字（适用于学生）
#   若请求携带 teacher session 或 ?teacher_password=xxx 则显示录取学生姓名
@app.route("/seatmap.png", methods=["GET"])
def seatmap_png():
    mode = request.args.get("mode", "public")
    # 判断是否可以显示姓名
    show_names = False
    if session.get("is_teacher"):
        show_names = True
    else:
        # 允许通过 query param teacher_password 临时查看（老师端可用）
        tp = request.args.get("teacher_password")
        if tp and tp == TEACHER_PASSWORD:
            show_names = True

    # 如果 mode=public 强制不显示姓名
    if mode == "public":
        show_names = False

    # 读取当前数据库分配结果，构建每排被录取学生列表
    db = get_db()
    c = db.cursor()
    c.execute("SELECT name, admitted FROM students WHERE admitted IS NOT NULL")
    rows = c.fetchall()
    assigned_map = {}  # seat_name -> [names]
    for r in rows:
        seat = r["admitted"]
        if not seat: continue
        assigned_map.setdefault(seat, []).append(r["name"])

    # 座位结构（与前端一致）
    groups = [("第一组",7), ("第二组",8), ("第三组",8), ("第四组",7)]
    # 图片尺寸与绘制参数
    width = 1400
    height_per_group = 160
    padding = 40
    group_gap = 18
    # compute height
    total_height = padding*2 + sum([height_per_group for _ in groups]) + group_gap*(len(groups)-1)
    img = Image.new("RGBA", (width, max(total_height, 420)), (255,255,255,255))
    draw = ImageDraw.Draw(img)

    # 字体（使用默认 PIL 字体，兼容性好）
    try:
        # 尝试加载系统字体（若可用）
        font_title = ImageFont.truetype("DejaVuSans-Bold.ttf", 20)
        font_seat = ImageFont.truetype("DejaVuSans.ttf", 14)
    except:
        font_title = ImageFont.load_default()
        font_seat = ImageFont.load_default()

    # 背景渐变（轻微）
    # 简单填充浅蓝背景
    draw.rectangle([(0,0),(width,height_per_group*len(groups)+padding*2)], fill=(245,250,255))

    y = padding
    col_w = (width - padding*2) // 4
    for gi, (gname, rows_count) in enumerate(groups):
        gx = padding
        gy = y
        # 标题
        draw.text((gx, gy-28), f"{gname}", fill=(30,111,186), font=font_title)
        # 每排占用矩形
        seat_box_w = col_w - 40
        # center area for rows
        for r in range(1, rows_count+1):
            # calculate x/y for this row: distribute rows vertically inside group area
            # arrange rows vertically stacked with small spacing
            row_h = 28
            row_top = gy + (r-1)*(row_h+8)
            seat_name = f"{gname}第{r}排"
            # box coordinates centered horizontally within column
            bx1 = gx + 10
            bx2 = bx1 + seat_box_w
            by1 = row_top
            by2 = by1 + row_h
            # draw box background depending on how many assigned
            assigned_list = assigned_map.get(seat_name, [])
            count = len(assigned_list)
            if count >= 2:
                fill = (40,167,69)  # green
                text_fill = (255,255,255)
            elif count == 1:
                fill = (255,223,93)  # amber for partially filled
                text_fill = (0,0,0)
            else:
                fill = (245,249,255)
                text_fill = (0,0,0)
            # box border
            draw.rectangle([(bx1, by1), (bx2, by2)], fill=fill, outline=(200,210,220))
            # write seat name and occupancy
            txt = f"{seat_name}  ({count}/2)"
            draw.text((bx1+8, by1+4), txt, font=font_seat, fill=text_fill)
            # if show_names and assigned, draw names inside (small)
            if show_names and assigned_list:
                names_text = "、".join(assigned_list)
                # limit length
                max_chars = 40
                if len(names_text) > max_chars:
                    names_text = names_text[:max_chars-3] + "..."
                draw.text((bx1+8, by1+4+16), names_text, font=font_seat, fill=text_fill)
        # move y to next group
        y += height_per_group + group_gap

    # footer
    draw.text((padding, y+6), f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}", fill=(120,120,120), font=font_seat)

    # 输出 PNG
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype='image/png', as_attachment=False, download_name='seatmap.png')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=True)
