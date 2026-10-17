import os, json, time, hmac, threading, sys
import pymysql
from flask import Flask, request, jsonify, abort
from werkzeug.exceptions import HTTPException
from itsdangerous import URLSafeTimedSerializer
from werkzeug.security import generate_password_hash, check_password_hash

E = os.environ
ADMIN_PASSWORD, SECRET = E["ADMIN_PASSWORD"], E["SECRET_KEY"]
SEED = [("Steel Water Bottle", 499, "1 litre, keeps drinks cold", "bottle.jpg"),
        ("Cotton Kurta", 1299, "Soft, breathable, regular fit", "kurta.jpg"),
        ("Wireless Earbuds", 1799, "20 hour battery with case", "earbuds.jpg"),
        ("Running Shoes", 2499, "Light mesh, cushioned sole", "shoes.jpg"),
        ("Ceramic Mug Set", 699, "Set of 4, dishwasher safe", "mugs.jpg"),
        ("Laptop Backpack", 1599, "Fits 15.6 inch, water resistant", "backpack.jpg")]

app = Flask(__name__)
ser = URLSafeTimedSerializer(SECRET)   # same SECRET_KEY on every instance -> login works on any server
READY = threading.Event()


def db(with_db=True):
    return pymysql.connect(host=E["DB_HOST"], user=E["DB_USER"], password=E["DB_PASS"],
                           database=E["DB_NAME"] if with_db else None,
                           cursorclass=pymysql.cursors.DictCursor, autocommit=True, connect_timeout=5)


def init_db():
    """Runs in the background so the API always starts and always answers with JSON."""
    while True:
        try:
            c = db(False); c.cursor().execute("CREATE DATABASE IF NOT EXISTS `%s` CHARACTER SET utf8mb4" % E["DB_NAME"]); c.close()
            c = db(); cur = c.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS users(id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(80) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE, pw VARCHAR(255) NOT NULL, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("CREATE TABLE IF NOT EXISTS orders(id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL, items TEXT NOT NULL, total INT NOT NULL, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("CREATE TABLE IF NOT EXISTS products(id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL, price INT NOT NULL, description VARCHAR(250) NOT NULL DEFAULT '', image VARCHAR(100) NOT NULL DEFAULT '', created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            cur.execute("SELECT COUNT(*) n FROM products")
            if cur.fetchone()["n"] == 0:
                cur.executemany("INSERT INTO products(name,price,description,image) VALUES(%s,%s,%s,%s)", SEED)
            c.close(); READY.set(); print("database ready", flush=True); return
        except Exception as ex:
            print("database not ready:", ex, file=sys.stderr, flush=True); time.sleep(5)


threading.Thread(target=init_db, daemon=True).start()


@app.errorhandler(Exception)
def any_error(e):   # every failure is JSON, never an HTML page
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    print("error:", repr(e), file=sys.stderr, flush=True)
    return jsonify(error="Something went wrong on the server. Please try again."), 500


def uid():
    t = request.headers.get("Authorization", "").replace("Bearer ", "")
    try: return ser.loads(t, max_age=7 * 86400)["u"]
    except Exception: return None


def is_admin():
    return hmac.compare_digest(request.headers.get("X-Admin-Password", "").encode(), ADMIN_PASSWORD.encode())


def run(sql, args=(), one=False, many=False):
    if not READY.is_set(): abort(503, "Database is starting up. Please retry in a few seconds.")
    c = db()
    try:
        cur = c.cursor(); cur.execute(sql, args)
        if one: return cur.fetchone()
        if many: return cur.fetchall()
        return cur.lastrowid
    finally:
        c.close()


@app.get("/api/health")
def health():
    return jsonify(ok=True, database=READY.is_set())


@app.get("/api/products")
def products():
    return jsonify(products=run("SELECT id,name,price,description,image FROM products ORDER BY id", many=True))


@app.post("/api/signup")
def signup():
    d = request.get_json(silent=True) or {}
    name, email, pw = str(d.get("name", "")).strip(), str(d.get("email", "")).strip().lower(), str(d.get("password", ""))
    if not name or "@" not in email or len(pw) < 6:
        return jsonify(error="Enter a name, a valid email and a password of 6+ characters."), 400
    try:
        u = run("INSERT INTO users(name,email,pw) VALUES(%s,%s,%s)", (name[:80], email[:120], generate_password_hash(pw)))
    except pymysql.err.IntegrityError:
        return jsonify(error="This email is already registered. Please log in."), 409
    return jsonify(token=ser.dumps({"u": u}), name=name)


@app.post("/api/login")
def login():
    d = request.get_json(silent=True) or {}
    u = run("SELECT * FROM users WHERE email=%s", (str(d.get("email", "")).strip().lower(),), one=True)
    if not u or not check_password_hash(u["pw"], str(d.get("password", ""))):
        return jsonify(error="Wrong email or password."), 401
    return jsonify(token=ser.dumps({"u": u["id"]}), name=u["name"])


@app.post("/api/order")
def order():
    u = uid()
    if not u: return jsonify(error="Please log in first."), 401
    items, total = [], 0
    for it in (request.get_json(silent=True) or {}).get("items", []):
        try: pid, qty = int(it.get("id", 0)), max(1, min(int(it.get("qty", 1)), 20))
        except (TypeError, ValueError, AttributeError): continue
        p = run("SELECT name,price FROM products WHERE id=%s", (pid,), one=True)
        if p: items.append({"name": p["name"], "qty": qty, "price": p["price"]}); total += p["price"] * qty
    if not items: return jsonify(error="Those products are no longer available."), 400
    return jsonify(id=run("INSERT INTO orders(user_id,items,total) VALUES(%s,%s,%s)", (u, json.dumps(items), total)), total=total)


@app.get("/api/orders")
def my_orders():
    u = uid()
    if not u: return jsonify(error="Please log in."), 401
    rows = run("SELECT id,items,total,created FROM orders WHERE user_id=%s ORDER BY id DESC LIMIT 20", (u,), many=True)
    for r in rows: r["items"] = json.loads(r["items"]); r["created"] = str(r["created"])
    return jsonify(orders=rows)


@app.get("/api/admin/summary")
def summary():
    if not is_admin(): return jsonify(error="Wrong admin password."), 401
    n = lambda q: run(q, one=True)["n"]
    ser_ = lambda rows: [{k: str(v) if k == "created" else v for k, v in r.items()} for r in rows]
    return jsonify(
        counts={"users": n("SELECT COUNT(*) n FROM users"), "orders": n("SELECT COUNT(*) n FROM orders"),
                "revenue": int(n("SELECT COALESCE(SUM(total),0) n FROM orders")), "products": n("SELECT COUNT(*) n FROM products")},
        users=ser_(run("SELECT id,name,email,created FROM users ORDER BY id DESC LIMIT 25", many=True)),
        orders=ser_(run("SELECT o.id,u.name,o.total,o.created FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.id DESC LIMIT 25", many=True)),
        products=run("SELECT id,name,price,description,image FROM products ORDER BY id DESC", many=True))


@app.post("/api/admin/products")
def add_product():
    if not is_admin(): return jsonify(error="Wrong admin password."), 401
    d = request.get_json(silent=True) or {}
    name, desc, img = str(d.get("name", "")).strip()[:100], str(d.get("description", "")).strip()[:250], str(d.get("image", "")).strip()[:100]
    try: price = int(d.get("price"))
    except (TypeError, ValueError): price = 0
    if not name or price <= 0: return jsonify(error="Enter a product name and a price above 0."), 400
    return jsonify(id=run("INSERT INTO products(name,price,description,image) VALUES(%s,%s,%s,%s)", (name, price, desc, img)))


@app.delete("/api/admin/products/<int:pid>")
def delete_product(pid):
    if not is_admin(): return jsonify(error="Wrong admin password."), 401
    run("DELETE FROM products WHERE id=%s", (pid,))
    return jsonify(ok=True)
