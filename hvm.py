import os
import sys
import subprocess
import requests
import flask
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import docker
import random
import string
import json
import datetime
import time
import logging
import socket
import paramiko
import traceback
import shutil
import sqlite3
import threading
from dotenv import load_dotenv
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import psutil
import pty
import select
import termios
import tty
import fcntl
import struct
import signal
import uuid
import concurrent.futures
import csv
import io
from werkzeug.utils import secure_filename
import tarfile
from io import BytesIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import smtplib
from email.mime.text import MIMEText
from collections import deque
import shlex
import base64
from ecdsa import VerifyingKey, BadSignatureError, NIST384p

PUBLIC_HEX = 'b681f4f051055d844c3f21678db26759adacf292fc649b49e08800b316173927aa08df82ad4a9a9930e26315ddc8531671ba42cdf16e91c086ce30150b6470cb37f390da3b3ec6522bed24cb1703efff9a0c8ec8d744222657e1944f5a08d81e'

AVAILABLE_THEMES = ['light', 'dark', 'cyberpunk', 'emerald', 'sunset', 'neon']

def check_docker_installed():
    try:
        subprocess.run(["docker", "--version"], check=True, capture_output=True)
        return True
    except:
        return False

def check_docker_running():
    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        return True
    except:
        return False

def install_docker():
    try:
        response = requests.get("https://get.docker.com")
        with open("get-docker.sh", "w") as f:
            f.write(response.text)
        subprocess.run(["sh", "get-docker.sh"], check=True)
        subprocess.run(["systemctl", "start", "docker"], check=True)
        subprocess.run(["systemctl", "enable", "docker"], check=True)
        os.remove("get-docker.sh")
        return True
    except Exception as e:
        print(f"Error installing Docker: {e}")
        return False

if not check_docker_installed():
    if not install_docker():
        sys.exit(1)

if not check_docker_running():
    subprocess.run(["systemctl", "start", "docker"], check=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('hvm_panel.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('HVMPanel')

load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY', ''.join(random.choices(string.ascii_letters + string.digits, k=32)))
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin')
PANEL_NAME = os.getenv('PANEL_NAME', 'HVM PANEL')
WATERMARK = os.getenv('WATERMARK', 'HVM VPS Service')
WELCOME_MESSAGE = os.getenv('WELCOME_MESSAGE', 'Welcome to HVM PANEL! Power Your Future!')
MAX_VPS_PER_USER = int(os.getenv('MAX_VPS_PER_USER', '3'))
DEFAULT_OS_IMAGE = os.getenv('DEFAULT_OS_IMAGE', 'ubuntu:22.04')
DOCKER_NETWORK = os.getenv('DOCKER_NETWORK', 'hvm_network')
MAX_CONTAINERS = int(os.getenv('MAX_CONTAINERS', '100'))
DB_FILE = 'hvm_panel.db'
BACKUP_FILE = 'hvm_panel_backup.json'
SERVER_IP = os.getenv('SERVER_IP', socket.gethostbyname(socket.gethostname()))
SERVER_PORT = int(os.getenv('SERVER_PORT', '3000'))
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'tar', 'gz', 'iso', 'dockerfile'}
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.example.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
SMTP_USER = os.getenv('SMTP_USER', 'user@example.com')
SMTP_PASS = os.getenv('SMTP_PASS', 'password')
NOTIFICATION_EMAIL = os.getenv('NOTIFICATION_EMAIL', 'admin@example.com')
BACKUP_SCHEDULE = os.getenv('BACKUP_SCHEDULE', 'daily')
VPS_HOSTNAME_PREFIX = os.getenv('VPS_HOSTNAME_PREFIX', 'hvm-')

DOCKERFILE_TEMPLATE = """
FROM {base_image}
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \\
    apt-get install -y systemd systemd-sysv dbus sudo \\
                       curl gnupg2 apt-transport-https ca-certificates \\
                       software-properties-common \\
                       docker.io openssh-server tmate && \\
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN mkdir /var/run/sshd && \\
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \\
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
RUN systemctl enable ssh && \\
    systemctl enable docker
RUN apt-get update && \\
    apt-get install -y neofetch htop nano vim wget git tmux net-tools dnsutils iputils-ping ufw \\
                       fail2ban nmap iotop btop wireguard openvpn zabbix-agent glances iftop tcpdump samba apache2 prometheus clamav sysbench && \\
    apt-get clean && \\
    rm -rf /var/lib/apt/lists/*
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
"""

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
socketio = SocketIO(app, async_mode='threading', cors_allowed_origins="*")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, role='user', email=None, theme='light', coins=0):
        self.id = id
        self.username = username
        self.role = role
        self.email = email
        self.theme = theme
        self.coins = coins

@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_user_by_id(user_id)
    if user_data:
        return User(
            user_data['id'],
            user_data['username'],
            user_data['role'],
            user_data.get('email'),
            user_data.get('theme', 'light'),
            user_data.get('coins', 0)
        )
    return None

class Database:
    def __init__(self, db_file):
        self.db_file = db_file
        self.lock = threading.Lock()
        self.conn = None
        self.cursor = None
        self._connect()
        self._create_tables()
        self._initialize_settings()
        self._migrate_database()

    def _connect(self):
        self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()

    def _execute(self, query, params=()):
        with self.lock:
            try:
                self.cursor.execute(query, params)
                self.conn.commit()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e):
                    time.sleep(0.1)
                    self.cursor.execute(query, params)
                    self.conn.commit()
                else:
                    raise

    def _fetchone(self, query, params=()):
        with self.lock:
            self.cursor.execute(query, params)
            return self.cursor.fetchone()

    def _fetchall(self, query, params=()):
        with self.lock:
            self.cursor.execute(query, params)
            return self.cursor.fetchall()

    def _create_tables(self):
        self._execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                password TEXT,
                role TEXT DEFAULT 'user',
                email TEXT,
                created_at TEXT,
                theme TEXT DEFAULT 'light',
                coins INTEGER DEFAULT 0,
                last_daily_claim TEXT
            )
        ''')

        self._execute('''
            CREATE TABLE IF NOT EXISTS vps_instances (
                token TEXT PRIMARY KEY,
                vps_id TEXT UNIQUE,
                container_id TEXT,
                memory INTEGER,
                cpu INTEGER,
                disk INTEGER,
                bandwidth_limit INTEGER DEFAULT 0,
                username TEXT,
                password TEXT,
                root_password TEXT,
                created_by INTEGER,
                created_at TEXT,
                tmate_session TEXT,
                watermark TEXT,
                os_image TEXT,
                restart_count INTEGER DEFAULT 0,
                last_restart TEXT,
                status TEXT DEFAULT 'running',
                port INTEGER,
                image_id TEXT,
                expires_at TEXT,
                expires_days INTEGER DEFAULT 30,
                expires_hours INTEGER DEFAULT 0,
                expires_minutes INTEGER DEFAULT 0,
                additional_ports TEXT DEFAULT '',
                uptime_start TEXT,
                tags TEXT DEFAULT '',
                FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        self._execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')

        self._execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                reason TEXT DEFAULT 'No reason provided',
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        self._execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message TEXT,
                created_at TEXT,
                read BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

        self._execute('''
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                details TEXT,
                timestamp TEXT,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        ''')

    def _migrate_database(self):
        user_columns = [col[1] for col in self._fetchall("PRAGMA table_info(users)")]
        if 'email' not in user_columns:
            self._execute('ALTER TABLE users ADD COLUMN email TEXT')
        if 'theme' not in user_columns:
            self._execute('ALTER TABLE users ADD COLUMN theme TEXT DEFAULT "light"')
        if 'coins' not in user_columns:
            self._execute('ALTER TABLE users ADD COLUMN coins INTEGER DEFAULT 0')
        if 'last_daily_claim' not in user_columns:
            self._execute('ALTER TABLE users ADD COLUMN last_daily_claim TEXT')

    def _initialize_settings(self):
        defaults = {
            'max_containers': str(MAX_CONTAINERS),
            'max_vps_per_user': str(MAX_VPS_PER_USER),
            'panel_name': PANEL_NAME,
            'watermark': WATERMARK,
            'welcome_message': WELCOME_MESSAGE,
            'server_ip': SERVER_IP,
            'vps_hostname_prefix': VPS_HOSTNAME_PREFIX,
            'maintenance_mode': 'off',
            'registration_enabled': 'on',
            'daily_coin_reward': '10',
            'vps_coin_cost_7_days': '50'
        }
        for key, value in defaults.items():
            self._execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)', (key, value))
        
        admin = self._fetchone('SELECT id FROM users WHERE username = ?', (ADMIN_USERNAME,))
        if not admin:
            hashed = generate_password_hash(ADMIN_PASSWORD)
            self._execute('INSERT INTO users (username, password, role, created_at, coins) VALUES (?, ?, ?, ?, ?)',
                          (ADMIN_USERNAME, hashed, 'admin', str(datetime.datetime.now()), 500))

    def get_setting(self, key, default=None):
        result = self._fetchone('SELECT value FROM system_settings WHERE key = ?', (key,))
        return result[0] if result else default

    def get_user(self, username):
        row = self._fetchone('SELECT * FROM users WHERE username = ?', (username,))
        if row:
            columns = [desc[0] for desc in self.cursor.description]
            return dict(zip(columns, row))
        return None

    def get_user_by_id(self, user_id):
        row = self._fetchone('SELECT * FROM users WHERE id = ?', (user_id,))
        if row:
            columns = [desc[0] for desc in self.cursor.description]
            return dict(zip(columns, row))
        return None

    def create_user(self, username, password, role='user', email=None, theme='light'):
        try:
            hashed = generate_password_hash(password)
            self._execute('INSERT INTO users (username, password, role, email, created_at, theme, coins) VALUES (?, ?, ?, ?, ?, ?, ?)',
                          (username, hashed, role, email, str(datetime.datetime.now()), theme, 20))
            return True
        except sqlite3.IntegrityError:
            return False

    def update_user_coins(self, user_id, amount):
        self._execute('UPDATE users SET coins = coins + ? WHERE id = ?', (amount, user_id))

    def update_user(self, user_id, username=None, password=None, role=None, email=None, theme=None):
        updates = {}
        if username: updates['username'] = username
        if password: updates['password'] = generate_password_hash(password)
        if role: updates['role'] = role
        if email: updates['email'] = email
        if theme and theme in AVAILABLE_THEMES: updates['theme'] = theme
        if not updates: return False
        set_clause = ', '.join(f'{k} = ?' for k in updates)
        values = list(updates.values()) + [user_id]
        self._execute(f'UPDATE users SET {set_clause} WHERE id = ?', values)
        return self.cursor.rowcount > 0

    def get_user_vps(self, user_id):
        rows = self._fetchall('SELECT * FROM vps_instances WHERE created_by = ?', (user_id,))
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    def get_vps_by_id(self, vps_id):
        row = self._fetchone('SELECT * FROM vps_instances WHERE vps_id = ?', (vps_id,))
        if row:
            columns = [desc[0] for desc in self.cursor.description]
            vps = dict(zip(columns, row))
            return vps['token'], vps
        return None, None

    def is_user_banned(self, user_id):
        return self._fetchone('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,)) is not None

    def get_ban_reason(self, user_id):
        row = self._fetchone('SELECT reason FROM banned_users WHERE user_id = ?', (user_id,))
        return row[0] if row else None

    def get_notifications(self, user_id):
        rows = self._fetchall('SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in rows]

    def log_action(self, user_id, action, details):
        self._execute('INSERT INTO audit_logs (user_id, action, details, timestamp) VALUES (?, ?, ?, ?)',
                      (user_id, action, details, str(datetime.datetime.now())))

db = Database(DB_FILE)

try:
    docker_client = docker.from_env()
except Exception as e:
    logger.error(f"Docker init failed: {e}")
    docker_client = None

def is_admin(user):
    user_data = db.get_user_by_id(user.id)
    return user_data['role'] == 'admin' if user_data else False

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')
        user_data = db.get_user(username)
        if user_data and check_password_hash(user_data['password'], password):
            if db.is_user_banned(user_data['id']):
                return render_template('login.html', error=f'Banned: {db.get_ban_reason(user_data["id"])}', panel_name=db.get_setting('panel_name', PANEL_NAME))
            user = User(user_data['id'], user_data['username'], user_data['role'], user_data.get('email'), user_data.get('theme', 'light'), user_data.get('coins', 0))
            login_user(user)
            db.log_action(user.id, 'login', f'Logged in from {request.remote_addr}')
            return redirect(url_for('dashboard'))
        return render_template('login.html', error='Invalid credentials', panel_name=db.get_setting('panel_name', PANEL_NAME))
    return render_template('login.html', panel_name=db.get_setting('panel_name', PANEL_NAME))

@app.route('/dashboard')
@login_required
def dashboard():
    vps_list = db.get_user_vps(current_user.id)
    notifications = db.get_notifications(current_user.id)
    user_info = db.get_user_by_id(current_user.id)
    return render_template(
        'dashboard.html',
        vps_list=vps_list,
        notifications=notifications,
        panel_name=db.get_setting('panel_name', PANEL_NAME),
        server_ip=db.get_setting('server_ip', SERVER_IP),
        is_admin=is_admin(current_user),
        theme=user_info.get('theme', 'light'),
        coins=user_info.get('coins', 0),
        available_themes=AVAILABLE_THEMES
    )

# --- COIN SYSTEM ENDPOINTS ---

@app.route('/earn_coins', methods=['POST'])
@login_required
def earn_coins():
    user_data = db.get_user_by_id(current_user.id)
    last_claim = user_data.get('last_daily_claim')
    now = datetime.datetime.now()
    
    if last_claim:
        last_date = datetime.datetime.fromisoformat(last_claim).date()
        if last_date == now.date():
            return jsonify({'success': False, 'message': 'Daily reward already claimed today.'}), 400

    reward = int(db.get_setting('daily_coin_reward', 10))
    db.update_user_coins(current_user.id, reward)
    db._execute('UPDATE users SET last_daily_claim = ? WHERE id = ?', (str(now), current_user.id))
    db.log_action(current_user.id, 'claim_daily_coins', f'Claimed {reward} daily coins')
    
    return jsonify({
        'success': True,
        'message': f'You claimed {reward} coins!',
        'new_balance': user_data.get('coins', 0) + reward
    })

@app.route('/redeem_vps', methods=['POST'])
@login_required
def redeem_vps():
    user_data = db.get_user_by_id(current_user.id)
    cost = int(db.get_setting('vps_coin_cost_7_days', 50))
    
    if user_data.get('coins', 0) < cost:
        return jsonify({'success': False, 'message': f'Insufficient coins. You need {cost} coins.'}), 400

    vps_id = request.json.get('vps_id')
    token, vps = db.get_vps_by_id(vps_id)
    if not vps or vps['created_by'] != current_user.id:
        return jsonify({'success': False, 'message': 'VPS not found or unauthorized.'}), 404

    db.update_user_coins(current_user.id, -cost)
    current_expiry = datetime.datetime.fromisoformat(vps['expires_at'])
    new_expiry = current_expiry + datetime.timedelta(days=7)
    db._execute('UPDATE vps_instances SET expires_at = ? WHERE token = ?', (str(new_expiry), token))
    db.log_action(current_user.id, 'redeem_vps_extension', f'Redeemed 7-day extension for VPS {vps_id}')

    return jsonify({
        'success': True,
        'message': 'VPS extended by 7 days successfully!',
        'new_expiry': str(new_expiry),
        'new_balance': user_data.get('coins', 0) - cost
    })

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        theme = request.form.get('theme', 'light')
        if theme in AVAILABLE_THEMES:
            db.update_user(current_user.id, email=email, theme=theme)
            current_user.theme = theme
        return redirect(url_for('profile'))
    
    user_data = db.get_user_by_id(current_user.id)
    return render_template(
        'profile.html',
        panel_name=db.get_setting('panel_name', PANEL_NAME),
        email=user_data.get('email', ''),
        theme=user_data.get('theme', 'light'),
        coins=user_data.get('coins', 0),
        available_themes=AVAILABLE_THEMES
    )

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=SERVER_PORT, debug=DEBUG)
