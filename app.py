from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import inspect, text
from datetime import datetime
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret')

# Database configuration: prefer DATABASE_URL (PostgreSQL on Render), fallback to local SQLite
db_url = os.environ.get('DATABASE_URL')
if db_url:
    # normalize deprecated postgres:// scheme to postgresql://
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
else:
    # SQLite DB in project folder (dev fallback)
    db_path = os.path.join(os.path.dirname(__file__), 'chat.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Use eventlet/gevent for production websocket support on Render
socketio = SocketIO(app, cors_allowed_origins='*')
db = SQLAlchemy(app)

# keep track of online user sessions: username -> set of sids
online_users = {}


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    # store hashed password (nullable for existing DB migration)
    password_hash = db.Column(db.String(200), nullable=True)

    def __repr__(self):
        return f'<User {self.username}>'


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    room = db.Column(db.String(80), nullable=False, default='main')
    msg = db.Column(db.Text, nullable=False)
    ts = db.Column(db.DateTime, default=datetime.utcnow)

    def as_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'room': self.room,
            'msg': self.msg,
            'ts': self.ts.isoformat()
        }


class Friendship(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    __table_args__ = (db.UniqueConstraint('user_id', 'friend_id', name='_user_friend_uc'),)

    def __repr__(self):
        return f'<Friendship {self.user_id}->{self.friend_id}>'


class FriendRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('requester_id', 'recipient_id', name='_req_reqipient_uc'),)

    def __repr__(self):
        return f'<FriendRequest {self.requester_id}->{self.recipient_id} status={self.status}>'


with app.app_context():
    db.create_all()
    # ensure password_hash column exists for older SQLite DBs only
    try:
        engine_name = db.engine.url.drivername  # e.g., 'sqlite+pysqlite' or 'postgresql+psycopg2'
    except Exception:
        engine_name = ''
    if engine_name.startswith('sqlite'):
        inspector = inspect(db.engine)
        table_candidates = ['user', 'users']
        tbl = None
        for t in table_candidates:
            if t in inspector.get_table_names():
                tbl = t
                break
        if tbl:
            # get column names via PRAGMA using session.execute(text(...))
            res = db.session.execute(text(f"PRAGMA table_info({tbl})")).all()
            cols = [r[1] for r in res]
            if 'password_hash' not in cols:
                # add column (SQLite supports ADD COLUMN)
                db.session.execute(text(f'ALTER TABLE {tbl} ADD COLUMN password_hash VARCHAR(200)'))
                db.session.commit()


@app.route('/')
def index():
    # require login
    if 'username' not in session:
        return redirect(url_for('login'))
    # allow optional room and partner parameters to open private chats from links
    room = request.args.get('room', '')
    partner = request.args.get('partner', '')
    return render_template('index.html', username=session.get('username'), room=room, partner=partner)


def _pm_room_for(u1_id, u2_id):
    # deterministic room name for private messages between two user ids
    a, b = sorted([int(u1_id), int(u2_id)])
    return f'pm:{a}:{b}'


@app.route('/api/friends')
def api_friends():
    # returns JSON list of friends and last message preview for sidebar
    if 'username' not in session:
        return jsonify({'error': 'unauthorized'}), 401
    me = User.query.filter_by(username=session.get('username')).first()
    if not me:
        return jsonify({'error': 'unauthorized'}), 401
    rows = Friendship.query.filter_by(user_id=me.id).all()
    friend_ids = [r.friend_id for r in rows]
    friends_users = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    out = []
    for u in friends_users:
        room = _pm_room_for(me.id, u.id)
        last = Message.query.filter_by(room=room).order_by(Message.ts.desc()).first()
        last_payload = None
        if last:
            last_payload = {'msg': last.msg, 'ts': last.ts.isoformat(), 'username': last.username}
        out.append({'username': u.username, 'id': u.id, 'room': room, 'last': last_payload})
    return jsonify({'friends': out})


@app.route('/friends', methods=['GET', 'POST'])
def friends():
    if 'username' not in session:
        return redirect(url_for('login'))
    me = User.query.filter_by(username=session.get('username')).first()
    if not me:
        flash('User session invalid')
        return redirect(url_for('login'))

    if request.method == 'POST':
        # send friend request by username (recipient must accept)
        target = request.form.get('username', '').strip()
        if not target:
            flash('Friend username required')
            return redirect(url_for('friends'))
        if target == me.username:
            flash('Cannot add yourself')
            return redirect(url_for('friends'))
        other = User.query.filter_by(username=target).first()
        if not other:
            flash('User not found')
            return redirect(url_for('friends'))
        # already friends?
        exists1 = Friendship.query.filter_by(user_id=me.id, friend_id=other.id).first()
        if exists1:
            flash(f'{other.username} is already your friend')
            return redirect(url_for('friends'))
        # existing pending request?
        existing_req = FriendRequest.query.filter_by(requester_id=me.id, recipient_id=other.id, status='pending').first()
        if existing_req:
            flash('Friend request already sent')
            return redirect(url_for('friends'))
        # create request
        req = FriendRequest(requester_id=me.id, recipient_id=other.id)
        db.session.add(req)
        db.session.commit()
        flash(f'Friend request sent to {other.username}')
        return redirect(url_for('friends'))

    # GET: list friends and pending incoming requests
    rows = Friendship.query.filter_by(user_id=me.id).all()
    friend_ids = [r.friend_id for r in rows]
    friends_users = User.query.filter(User.id.in_(friend_ids)).all() if friend_ids else []
    friends_info = [
        {"username": u.username, "id": u.id, "room": _pm_room_for(me.id, u.id)}
        for u in friends_users
    ]

    # incoming pending requests
    incoming = FriendRequest.query.filter_by(recipient_id=me.id, status='pending').all()
    incoming_info = []
    for req in incoming:
        requester = User.query.get(req.requester_id)
        if requester:
            incoming_info.append({"id": req.id, "username": requester.username})

    return render_template('friends.html', friends=friends_info, incoming=incoming_info)



@app.route('/friends/respond', methods=['POST'])
def friends_respond():
    if 'username' not in session:
        return redirect(url_for('login'))
    me = User.query.filter_by(username=session.get('username')).first()
    if not me:
        flash('User session invalid')
        return redirect(url_for('login'))
    req_id = request.form.get('request_id')
    action = request.form.get('action')
    if not req_id or action not in ('accept', 'decline'):
        flash('Invalid request')
        return redirect(url_for('friends'))
    req = FriendRequest.query.get(int(req_id))
    if not req or req.recipient_id != me.id:
        flash('Request not found')
        return redirect(url_for('friends'))
    if action == 'accept':
        # create mutual friendships if not exists
        if not Friendship.query.filter_by(user_id=me.id, friend_id=req.requester_id).first():
            f1 = Friendship(user_id=me.id, friend_id=req.requester_id)
            f2 = Friendship(user_id=req.requester_id, friend_id=me.id)
            db.session.add_all([f1, f2])
        req.status = 'accepted'
        db.session.commit()
        flash('Friend request accepted')
    else:
        req.status = 'declined'
        db.session.commit()
        flash('Friend request declined')
    return redirect(url_for('friends'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        print(f"[auth-debug] register POST username='{username}' password_len={len(password)}")
        # validation
        if not username:
            print("[auth-debug] register: missing username")
            flash('Username required')
            return render_template('register.html', username='')
        if len(username) < 3:
            print("[auth-debug] register: username too short")
            flash('Username must be at least 3 characters')
            return render_template('register.html', username=username)
        if not password:
            print("[auth-debug] register: missing password")
            flash('Password required')
            return render_template('register.html', username=username)
        if len(password) < 6:
            print("[auth-debug] register: password too short")
            flash('Password must be at least 6 characters')
            return render_template('register.html', username=username)
        if User.query.filter_by(username=username).first():
            print("[auth-debug] register: username taken")
            flash('Username already taken')
            return render_template('register.html', username=username)
        # create user
        user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        session['username'] = username
        flash('Registration successful. You are now logged in.')
        return redirect(url_for('index'))
    return render_template('register.html', username='')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        print(f"[auth-debug] login POST username='{username}' password_len={len(password)}")
        # validation
        if not username:
            print("[auth-debug] login: missing username")
            flash('Username required')
            return render_template('login.html', username='')
        if not password:
            print("[auth-debug] login: missing password")
            flash('Password required')
            return render_template('login.html', username=username)
        user = User.query.filter_by(username=username).first()
        print(f"[auth-debug] login: lookup user -> {user}")
        if not user:
            print("[auth-debug] login: unknown user -> redirect to register view (render login with message)")
            flash('Unknown user. Please register first.')
            return render_template('login.html', username='')
        # verify password
        if not user.password_hash or not check_password_hash(user.password_hash, password):
            print("[auth-debug] login: invalid credentials")
            flash('Invalid credentials')
            return render_template('login.html', username=username)
        session['username'] = username
        print(f"[auth-debug] login: success for user={username}")
        flash('Logged in successfully.')
        return redirect(url_for('index'))
    return render_template('login.html', username='')


@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('login'))


@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')


@socketio.on('join')
def handle_join(data):
    username = data.get('username', 'Anonymous')
    room = data.get('room', 'main')
    join_room(room)
    # send last 100 messages for the room to the joining client
    history = Message.query.filter_by(room=room).order_by(Message.ts.asc()).limit(100).all()
    history_payload = [m.as_dict() for m in history]
    # emit only to the joining client
    emit('history', {'messages': history_payload}, room=request.sid)
    emit('status', {'msg': f'{username} has entered the room.'}, room=room)
    # track online by username if provided
    if username and username != 'Anonymous':
        s = online_users.get(username, set())
        s.add(request.sid)
        online_users[username] = s
        # broadcast updated presence
        socketio.emit('presence_list', {'online': list(online_users.keys())})


@socketio.on('message')
def handle_message(data):
    username = data.get('username', 'Anonymous')
    room = data.get('room', 'main')
    msg = data.get('msg', '')
    # persist
    m = Message(username=username, room=room, msg=msg)
    db.session.add(m)
    db.session.commit()
    emit('message', {'username': username, 'msg': msg, 'ts': m.ts.isoformat()}, room=room)


@socketio.on('leave')
def handle_leave(data):
    username = data.get('username', 'Anonymous')
    room = data.get('room', 'main')
    leave_room(room)
    emit('status', {'msg': f'{username} has left the room.'}, room=room)
    # remove sid from online map for this username
    if username and username != 'Anonymous':
        s = online_users.get(username, set())
        s.discard(request.sid)
        if not s:
            online_users.pop(username, None)
        else:
            online_users[username] = s
        socketio.emit('presence_list', {'online': list(online_users.keys())})


@socketio.on('disconnect')
def handle_disconnect():
    print(f'Client disconnected: {request.sid}')
    # clean up any username that had this sid
    to_remove = []
    for uname, sids in list(online_users.items()):
        if request.sid in sids:
            sids.discard(request.sid)
            if not sids:
                to_remove.append(uname)
            else:
                online_users[uname] = sids
    for u in to_remove:
        online_users.pop(u, None)
    socketio.emit('presence_list', {'online': list(online_users.keys())})


if __name__ == '__main__':
    # Use socketio.run which will choose the right async mode if eventlet/gevent is installed
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
