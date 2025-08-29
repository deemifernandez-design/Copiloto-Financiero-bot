from fastapi import FastAPI, Request
import os, requests, sqlite3

TOKEN = os.getenv("TG_TOKEN")
if not TOKEN:
    raise RuntimeError("Falta la variable de entorno TG_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"

DB_PATH = os.getenv("DB_PATH", "data.db")

def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, tg_id TEXT UNIQUE, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS movimientos (
        id INTEGER PRIMARY KEY, user_id INTEGER, tipo TEXT, monto REAL, categoria TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS deudas (
        id INTEGER PRIMARY KEY, user_id INTEGER, nombre TEXT, saldo REAL, tna REAL, cierre TEXT)""")
    con.commit(); con.close()

def get_user_id(tg_id):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT OR IGNORE INTO users (tg_id) VALUES (?)", (str(tg_id),))
    con.commit()
    cur.execute("SELECT id FROM users WHERE tg_id = ?", (str(tg_id),))
    uid = cur.fetchone()[0]; con.close()
    return uid

def add_mov(user_id, tipo, monto, cat):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT INTO movimientos (user_id, tipo, monto, categoria) VALUES (?, ?, ?, ?)",
                (user_id, tipo, monto, cat))
    con.commit(); con.close()

def add_deuda(user_id, nombre, saldo, tna, cierre=None):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("INSERT INTO deudas (user_id, nombre, saldo, tna, cierre) VALUES (?, ?, ?, ?, ?)",
                (user_id, nombre, saldo, tna, cierre))
    con.commit(); con.close()

def resumen_mes(user_id):
    con = sqlite3.connect(DB_PATH); cur = con.cursor()
    cur.execute("""SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN monto ELSE 0 END),0),
                          COALESCE(SUM(CASE WHEN tipo='gasto' THEN monto ELSE 0 END),0)
                   FROM movimientos WHERE user_id=?""", (user_id,))
    inc, gas = cur.fetchone(); con.close()
    return inc, gas

def recomendar(user_id, infl_m=0.03, tna=0.45):
    costo_m = tna/12.0
    msg = ("Pagá en pesos cuanto antes; financiar cuesta más que la inflación."
           if costo_m > infl_m else
           "Podés diferir parte del pago en pesos; el costo estimado es menor que la inflación.")
    inc, gas = resumen_mes(user_id)
    ahorro_demo = max(0, int((costo_m - infl_m) * 100000))
    return f"{msg}\nIngresos mes: ${int(inc)} | Gastos mes: ${int(gas)}\nAhorro estimado (demo): ${ahorro_demo}"

app = FastAPI()

@app.on_event("startup")
def startup(): init_db()

@app.get("/")
def health(): return {"ok": True}

@app.api_route("/webhook", methods=["POST", "GET"])
async def webhook(req: Request):
    if req.method == "GET":
        # Responder 200 OK al ping/verificación
        return {"ok": True, "webhook": "alive"}
    # ↓ lo demás igual
    data = await req.json()
    if "message" in data and "text" in data["message"]:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"]["text"].strip()
        user_id = get_user_id(chat_id)
        reply = handle(text, user_id)
        requests.post(f"{API}/sendMessage",
                      json={"chat_id": chat_id, "text": reply, "parse_mode": "Markdown"})
    return {"ok": True}

def handle(t, uid):
    if t == "/start":
        return ("¡Hola! Soy tu Copiloto Financiero 🇦🇷.\n"
                "Comandos:\n"
                "• /ingreso 750000\n• /gasto 120000 supermercado\n"
                "• /deuda VISA 250000 45\n• /resumen\n• /recomendar\n• /dolar")
    if t.startswith("/ingreso"):
        try:
            _, monto = t.split(maxsplit=1)
            add_mov(uid, "ingreso", float(monto.replace(',', '.')), "general")
            return "Ingreso registrado ✅"
        except: return "Formato: /ingreso 750000"
    if t.startswith("/gasto"):
        try:
            partes = t.split(maxsplit=2)
            monto = float(partes[1].replace(',', '.'))
            cat = partes[2] if len(partes) > 2 else "general"
            add_mov(uid, "gasto", monto, cat)
            return f"Gasto registrado ✅ ({cat})"
        except: return "Formato: /gasto 120000 supermercado"
    if t.startswith("/deuda"):
        try:
            _, nombre, saldo, tna = t.split(maxsplit=3)
            add_deuda(uid, nombre, float(saldo.replace(',', '.')), float(tna.replace(',', '.'))/100.0)
            return "Deuda registrada ✅"
        except: return "Formato: /deuda VISA 250000 45"
    if t == "/resumen":
        inc, gas = resumen_mes(uid)
        return f"Resumen mensual:\nIngresos: ${int(inc)}\nGastos: ${int(gas)}\nBalance: ${int(inc-gas)}"
    if t == "/recomendar":
        return recomendar(uid)
    if t.lower() in ("dolar", "/dolar", "/usd"):
        return "Dólar (mock): Oficial $1000 | MEP $1250 | Blue $1280"
    return "No te entendí. Probá /start"
