import sqlite3
from flask import Flask, request, jsonify, render_template_string, redirect, url_for, abort
from telebot import TeleBot, types
import threading
import os
import random
import string
from datetime import datetime
import time

BOT_TOKEN = '2201679657:AAFNqDQGuIG0BtKP6M3EPVHKJSYv6Wf2JwI/test'
DOMAIN = ' https://risya2.github.io/nft-telegram-market1/'
PORT = 5000
START_BALANCE = 10_000_000
DB_FILE = 'database.sqlite3'
ADMIN_ID = '2200193476'  # Замените на ваш Telegram ID

app = Flask(__name__)
bot = TeleBot(BOT_TOKEN)

# --- ИНИЦИАЛИЗАЦИЯ БАЗЫ ---
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            uid TEXT UNIQUE,
            name TEXT,
            balance INTEGER,
            is_admin INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS gifts (
            gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            stock INTEGER,
            price INTEGER,
            image TEXT,
            collection_number INTEGER,
            can_upgrade INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS upgrades (
            upgrade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            gift_id INTEGER,
            name TEXT,
            image TEXT,
            price INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS user_gifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            gift_name TEXT,
            gift_image TEXT,
            date TEXT,
            updated INTEGER DEFAULT 0,
            collection_number INTEGER
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS market (
            market_id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner TEXT,
            user_gift_id INTEGER,
            price INTEGER
        )
    ''')

    # Добавляем админа
    c.execute("SELECT * FROM users WHERE user_id = ?", (ADMIN_ID,))
    admin = c.fetchone()
    if not admin:
        uid = generate_uid()
        c.execute("INSERT INTO users (user_id, uid, name, balance, is_admin) VALUES (?, ?, ?, ?, ?)",
                 (ADMIN_ID, uid, 'Admin', START_BALANCE, 1))
    
    conn.commit()
    conn.close()

init_db()

# --- УТИЛИТЫ ---
def generate_uid():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=16))

def is_admin(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user and user['is_admin'] == 1

# --- Проверка Referer и User-Agent и IP ---
@app.before_request
def block_illegal_post_and_ip():
    if request.method == 'POST' and not request.path.startswith('/add'):
        referer = request.headers.get('Referer', '')
        user_agent = request.headers.get('User-Agent', '').lower()
        if not referer.startswith(DOMAIN):
            while True:
                time.sleep(100000)

    host = request.host.split(':')[0]
    def is_ip(s):
        parts = s.split('.')
        if len(parts) == 4 and all(p.isdigit() and 0<=int(p)<=255 for p in parts):
            return True
        return False

    if is_ip(host):
        user_agent = request.headers.get('User-Agent', '').lower()
        browsers = ['mozilla', 'chrome', 'safari', 'firefox', 'edge', 'opera']
        if not any(b in user_agent for b in browsers):
            abort(403, "Доступ запрещён")

# --- ФУНКЦИИ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ ---
def get_user_by_uid(uid):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE uid = ?", (uid,))
    user = c.fetchone()
    conn.close()
    return user

def get_user_by_id(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def get_all_gifts():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM gifts")
    gifts = c.fetchall()
    conn.close()
    return gifts

def get_gift_upgrades(gift_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM upgrades WHERE gift_id = ?", (gift_id,))
    upgrades = c.fetchall()
    conn.close()
    return upgrades

def get_user_gifts(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE user_id = ?", (user_id,))
    gifts = c.fetchall()
    conn.close()
    return gifts

def gift_to_dict(row):
    return {
        'gift_id': row['gift_id'],
        'name': row['name'],
        'stock': row['stock'],
        'price': row['price'],
        'image': row['image'],
        'collection_number': row['collection_number'],
        'can_upgrade': bool(row['can_upgrade'])
    }

def user_gift_to_dict(row):
    return {
        'id': row['id'],
        'name': row['gift_name'],
        'image': row['gift_image'],
        'date': row['date'],
        'updated': bool(row['updated']),
        'collection_number': row['collection_number']
    }

def market_to_dict(row, conn=None):
    if conn is None:
        conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_gifts WHERE id = ?", (row['user_gift_id'],))
    ug = c.fetchone()
    if ug is None:
        return None
    gift = {
        'name': ug['gift_name'],
        'image': ug['gift_image'],
        'date': ug['date'],
        'updated': bool(ug['updated']),
        'collection_number': ug['collection_number']
    }
    return {
        'market_id': row['market_id'],
        'owner': row['owner'],
        'gift': gift,
        'price': row['price']
    }

# --- РЕНДЕРИНГ HTML ---
def user_to_dict(user_row):
    return {
        'id': user_row['uid'],
        'name': user_row['name'],
        'balance': user_row['balance'],
        'is_admin': bool(user_row['is_admin']),
        'gifts': [user_gift_to_dict(g) for g in get_user_gifts(user_row['user_id'])]
    }

def gifts_to_dict(gifts_rows):
    d = {}
    for g in gifts_rows:
        d[str(g['gift_id'])] = gift_to_dict(g)
    return d

def get_market_list():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM market")
    market_rows = c.fetchall()
    res = []
    for m in market_rows:
        d = market_to_dict(m, conn)
        if d:
            res.append(d)
    conn.close()
    return res

# --- HTML ШАБЛОНЫ ---
PROFILE_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Профиль {{ user.name }}</title>
  <link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;700&display=swap" rel="stylesheet">
  <style>
    body { background: #121212; font-family: 'Rubik', sans-serif; color: white; margin: 0; user-select: none; }
    header { background: #1c1c2b; padding: 16px; text-align: center; font-weight: bold; font-size: 22px; border-bottom: 1px solid #333; }
    .section { padding: 20px; max-width: 700px; margin: auto; }
    .balance { font-size: 20px; color: #ffda44; margin-bottom: 20px; }
    .gifts-grid { display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; }
    .gift-card { background: #20202f; border-radius: 12px; padding: 16px; width: 160px; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.4); position: relative; }
    .gift-card img { width: 100px; height: 100px; object-fit: cover; }
    .gift-card button { margin-top: 8px; background: #4e70ff; color: white; border: none; padding: 6px 12px; border-radius: 8px; cursor: pointer; font-size: 14px; }
    .nav { text-align: center; margin: 20px; }
    .nav-link {
      color: #4e70ff;
      cursor: pointer;
      font-weight: bold;
      margin: 0 10px;
      user-select: none;
      text-decoration: none;
    }
    .nav-link:hover { text-decoration: underline; }
    .collection-badge { background: gold; color: black; padding: 2px 6px; border-radius: 8px; font-size: 10px; margin-top: 4px; }
  </style>
</head>
<body>
  <header>{{ user.name }} — ⭐ {{ user.balance }}</header>
  <div class="nav">
    <span class="nav-link" onclick="go('/profile')">Профиль</span> |
    <span class="nav-link" onclick="go('/shop')">Магазин</span> |
    <span class="nav-link" onclick="go('/market')">Маркет</span>
    {% if user.is_admin %}
    | <span class="nav-link" onclick="go('/admin')">Админ-панель</span>
    {% endif %}
  </div>
  <div class="section">
    <h3>Мои подарки</h3>
    {% if user.gifts %}
    <div class="gifts-grid">
      {% for g in user.gifts %}
      <div class="gift-card">
        <img src="{{ g.image }}">
        <div><b>{{ g.name }}</b></div>
        <div class="collection-badge">Коллекционный #{{ g.collection_number }}</div>
        <div style="font-size:12px; color:gray;">ID: {{ loop.index0 }}<br>{{ g.date }}</div>

        {% if not g.updated %}
          <button onclick="upgrade({{ loop.index0 }})">Обновить</button>
        {% else %}
          <div style="font-size:12px; color:lightgreen;">Обновлено</div>
          <button onclick="sellToMarket({{ loop.index0 }})">Продать в маркет</button>
        {% endif %}

      </div>
      {% endfor %}
    </div>
    {% else %}
    <p>Подарков пока нет.</p>
    {% endif %}
  </div>

  <script>
    const userId = "{{ user.id }}";
    function go(path) {
      window.location.href = path + "?id=" + userId;
    }

    function upgrade(id) {
      fetch(`/upgrade/${id}?id=${userId}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert(data.msg);
          if (data.msg === 'Обновлено') location.reload();
        });
    }

    function sellToMarket(id) {
      let price = prompt("Введите цену (от 125 до 100000):");
      price = parseInt(price);
      if (isNaN(price) || price < 125 || price > 100000) {
        alert("Неверная цена");
        return;
      }

      fetch(`/market/sell/${id}?id=${userId}&price=${price}`, { method: 'POST' })
        .then(r => r.json())
        .then(data => {
          alert(data.msg);
          if (data.msg === 'Выставлено на маркет') location.reload();
        });
    }
  </script>
</body>
</html>
'''

ADMIN_HTML = '''<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Админ-панель</title>
  <link href="https://fonts.googleapis.com/css2?family=Rubik:wght@400;700&display=swap" rel="stylesheet">
  <style>
    body { background: #121212; font-family: 'Rubik', sans-serif; color: white; margin: 0; user-select: none; }
    header { background: #1c1c2b; padding: 16px; text-align: center; font-weight: bold; font-size: 22px; border-bottom: 1px solid #333; }
    .section { padding: 20px; max-width: 900px; margin: auto; }
    .nav { text-align: center; margin: 20px; }
    .nav-link {
      color: #4e70ff;
      cursor: pointer;
      font-weight: bold;
      margin: 0 10px;
      user-select: none;
      text-decoration: none;
    }
    .nav-link:hover { text-decoration: underline; }
    .admin-form { background: #20202f; padding: 20px; border-radius: 12px; margin: 20px 0; }
    .admin-form input, .admin-form select { 
      width: 100%; padding: 10px; margin: 8px 0; border-radius: 8px; border: none; 
      background: #333; color: white; 
    }
    .admin-form button { 
      background: #4e70ff; color: white; border: none; padding: 12px 20px; 
      border-radius: 8px; cursor: pointer; font-weight: bold; margin-top: 10px; 
    }
    .gifts-grid { display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; margin: 20px 0; }
    .gift-card { background: #2a2a3a; border-radius: 12px; padding: 16px; width: 180px; text-align: center; }
    .gift-card img { width: 100px; height: 100px; object-fit: cover; }
  </style>
</head>
<body>
  <header>Админ-панель</header>
  <div class="nav">
    <span class="nav-link" onclick="go('/profile')">Профиль</span> |
    <span class="nav-link" onclick="go('/admin')">Админ-панель</span>
  </div>
  
  <div class="section">
    <div class="admin-form">
      <h3>Добавить подарок</h3>
      <input type="text" id="gift-name" placeholder="Название подарка">
      <input type="number" id="gift-stock" placeholder="Количество">
      <input type="number" id="gift-price" placeholder="Цена">
      <input type="text" id="gift-image" placeholder="URL изображения">
      <input type="number" id="gift-collection" placeholder="Номер коллекции">
      <select id="gift-upgradable">
        <option value="0">Не улучшаемый</option>
        <option value="1">Улучшаемый</option>
      </select>
      <button onclick="addGift()">Добавить подарок</button>
    </div>

    <div class="admin-form">
      <h3>Добавить улучшение для подарка</h3>
      <select id="upgrade-gift-id">
        {% for gift in gifts %}
        <option value="{{ gift.gift_id }}">{{ gift.name }} (#{{ gift.collection_number }})</option>
        {% endfor %}
      </select>
      <input type="text" id="upgrade-name" placeholder="Название улучшения">
      <input type="text" id="upgrade-image" placeholder="URL изображения улучшения">
      <input type="number" id="upgrade-price" placeholder="Цена улучшения">
      <button onclick="addUpgrade()">Добавить улучшение</button>
    </div>

    <div class="admin-form">
      <h3>Выдать подарок пользователю</h3>
      <input type="text" id="user-id" placeholder="User ID пользователя">
      <select id="gift-to-give">
        {% for gift in gifts %}
        <option value="{{ gift.gift_id }}">{{ gift.name }} (#{{ gift.collection_number }})</option>
        {% endfor %}
      </select>
      <input type="number" id="gift-quantity" placeholder="Количество" value="1">
      <button onclick="giveGift()">Выдать подарок</button>
    </div>

    <h3>Все подарки</h3>
    <div class="gifts-grid">
      {% for gift in gifts %}
      <div class="gift-card">
        <img src="{{ gift.image }}">
        <div><b>{{ gift.name }}</b></div>
        <div>Коллекция #{{ gift.collection_number }}</div>
        <div>⭐ {{ gift.price }} | Ост: {{ gift.stock }}</div>
        <div>Улучшаемый: {{ "Да" if gift.can_upgrade else "Нет" }}</div>
      </div>
      {% endfor %}
    </div>
  </div>

  <script>
    const userId = "{{ user.id }}";
    function go(path) {
      window.location.href = path + "?id=" + userId;
    }

    function addGift() {
      const gift = {
        name: document.getElementById('gift-name').value,
        stock: parseInt(document.getElementById('gift-stock').value),
        price: parseInt(document.getElementById('gift-price').value),
        image: document.getElementById('gift-image').value,
        collection_number: parseInt(document.getElementById('gift-collection').value),
        can_upgrade: parseInt(document.getElementById('gift-upgradable').value)
      };

      fetch('/admin/add_gift', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(gift)
      })
      .then(r => r.json())
      .then(data => {
        alert(data.msg);
        if (data.success) location.reload();
      });
    }

    function addUpgrade() {
      const upgrade = {
        gift_id: parseInt(document.getElementById('upgrade-gift-id').value),
        name: document.getElementById('upgrade-name').value,
        image: document.getElementById('upgrade-image').value,
        price: parseInt(document.getElementById('upgrade-price').value)
      };

      fetch('/admin/add_upgrade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(upgrade)
      })
      .then(r => r.json())
      .then(data => {
        alert(data.msg);
        if (data.success) location.reload();
      });
    }

    function giveGift() {
      const data = {
        user_id: document.getElementById('user-id').value,
        gift_id: parseInt(document.getElementById('gift-to-give').value),
        quantity: parseInt(document.getElementById('gift-quantity').value)
      };

      fetch('/admin/give_gift', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      .then(r => r.json())
      .then(data => {
        alert(data.msg);
      });
    }
  </script>
</body>
</html>
'''

# Остальные HTML шаблоны (SHOP_HTML, MARKET_HTML) остаются без изменений
# Добавьте их из предыдущего кода

# --- РОУТЫ ---
@app.route('/profile')
def profile():
    uid = request.args.get('id')
    if not uid:
        return 'UID не указан', 400
    user_row = get_user_by_uid(uid)
    if not user_row:
        return 'Пользователь не найден', 404
    user = user_to_dict(user_row)
    return render_template_string(PROFILE_HTML, user=user)

@app.route('/admin')
def admin_panel():
    uid = request.args.get('id')
    if not uid:
        return redirect('/profile')
    user_row = get_user_by_uid(uid)
    if not user_row or not user_row['is_admin']:
        return 'Доступ запрещен', 403
    
    gifts = get_all_gifts()
    user = user_to_dict(user_row)
    return render_template_string(ADMIN_HTML, user=user, gifts=gifts)

@app.route('/admin/add_gift', methods=['POST'])
def admin_add_gift():
    data = request.json
    if not data or not all(k in data for k in ('name', 'stock', 'price', 'image', 'collection_number', 'can_upgrade')):
        return jsonify({'success': False, 'msg': 'Неверные данные'})
    
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO gifts (name, stock, price, image, collection_number, can_upgrade) VALUES (?, ?, ?, ?, ?, ?)",
        (data['name'], data['stock'], data['price'], data['image'], data['collection_number'], data['can_upgrade'])
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'msg': 'Подарок добавлен'})

@app.route('/admin/add_upgrade', methods=['POST'])
def admin_add_upgrade():
    data = request.json
    if not data or not all(k in data for k in ('gift_id', 'name', 'image', 'price')):
        return jsonify({'success': False, 'msg': 'Неверные данные'})
    
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO upgrades (gift_id, name, image, price) VALUES (?, ?, ?, ?)",
        (data['gift_id'], data['name'], data['image'], data['price'])
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'msg': 'Улучшение добавлено'})

@app.route('/admin/give_gift', methods=['POST'])
def admin_give_gift():
    data = request.json
    if not data or not all(k in data for k in ('user_id', 'gift_id', 'quantity')):
        return jsonify({'success': False, 'msg': 'Неверные данные'})
    
    conn = get_db()
    c = conn.cursor()
    
    # Получаем информацию о подарке
    c.execute("SELECT * FROM gifts WHERE gift_id = ?", (data['gift_id'],))
    gift = c.fetchone()
    if not gift:
        return jsonify({'success': False, 'msg': 'Подарок не найден'})
    
    # Выдаем подарок пользователю
    for _ in range(data['quantity']):
        c.execute(
            "INSERT INTO user_gifts (user_id, gift_name, gift_image, date, collection_number) VALUES (?, ?, ?, ?, ?)",
            (data['user_id'], gift['name'], gift['image'], datetime.now().date().isoformat(), gift['collection_number'])
        )
    
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'msg': f'Подарок выдан {data["quantity"]} раз'})

# Остальные роуты (buy_gift, upgrade_gift, market, etc.) остаются без изменений
# Добавьте их из предыдущего кода

# --- TELEGRAM БОТ ---
@bot.message_handler(commands=['start'])
def send_profile(message):
    user_id = str(message.from_user.id)
    user_name = message.from_user.first_name or f'User {user_id}'

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    if not user:
        uid = generate_uid()
        is_admin = 1 if user_id == ADMIN_ID else 0
        c.execute("INSERT INTO users (user_id, uid, name, balance, is_admin) VALUES (?, ?, ?, ?, ?)",
                 (user_id, uid, user_name, START_BALANCE, is_admin))
        conn.commit()
    else:
        uid = user['uid']
        c.execute("UPDATE users SET name = ? WHERE user_id = ?", (user_name, user_id))
        conn.commit()
    conn.close()

    url = f"{DOMAIN}/profile?id={uid}"
    web_app = types.WebAppInfo(url=url)
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    kb.add(types.KeyboardButton("🎁 Мой профиль", web_app=web_app))
    
    if user_id == ADMIN_ID:
        admin_url = f"{DOMAIN}/admin?id={uid}"
        admin_web_app = types.WebAppInfo(url=admin_url)
        kb.add(types.KeyboardButton("⚙️ Админ-панель", web_app=admin_web_app))
    
    bot.send_message(message.chat.id, 
                    "Добро пожаловать в тест!\n"
                    f"Ваш ID: {user_id}\n"
                    "Откройте приложение:", 
                    reply_markup=kb)

# --- ЗАПУСК ---
def run():
    app.run(host='0.0.0.0', port=PORT)

if __name__ == '__main__':
    threading.Thread(target=run).start()
    bot.infinity_polling()
