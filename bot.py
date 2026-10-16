#!/usr/bin/env python3
"""Receive Telegram messages into a local SQLite archive; no third party dependencies."""
import fcntl
import json
import logging
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
KINDS = ('message', 'edited_message', 'channel_post', 'edited_channel_post')
ALLOWED = [*KINDS, 'my_chat_member']


class ApiError(Exception):
    def __init__(self, code, retry_after=0):
        self.code = code
        self.retry_after = retry_after
        super().__init__(f'Telegram API error {code}')


def api(token, method, **params):
    request = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/{method}',
        data=json.dumps(params).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        try:
            result = json.load(error)
        except (ValueError, OSError):
            raise ApiError(error.code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        # Never include the request URL (it contains the token) in logs.
        raise ApiError('network') from None
    if not result.get('ok'):
        raise ApiError(result.get('error_code', 'unknown'),
                       result.get('parameters', {}).get('retry_after', 0))
    return result['result']


def connect(path):
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS updates (
            update_id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
            payload TEXT NOT NULL, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chats (
            chat_id INTEGER PRIMARY KEY, type TEXT, title TEXT, username TEXT,
            bot_status TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS messages (
            chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
            sender_id INTEGER, sender_name TEXT, sender_username TEXT,
            sender_chat_id INTEGER, sent_at INTEGER, edited_at INTEGER,
            text TEXT, caption TEXT, thread_id INTEGER, media_group_id TEXT,
            reply_to_message_id INTEGER, payload TEXT NOT NULL,
            last_update_id INTEGER NOT NULL,
            PRIMARY KEY (chat_id, message_id)
        );
        CREATE INDEX IF NOT EXISTS messages_sent_at ON messages(sent_at);
        CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    ''')
    return db


def store(db, update):
    """Commit raw update, current message and next offset atomically.

    Raw updates preserve all message versions and attachment identifiers.
    Replayed updates are idempotent. Private messages are deliberately excluded.
    """
    uid = update['update_id']
    kind = next((key for key in ALLOWED if key in update), 'other')
    item = update.get(kind, {})
    chat = item.get('chat', {})
    with db:
        duplicate = db.execute('SELECT 1 FROM updates WHERE update_id=?', (uid,)).fetchone()
        if not duplicate and chat.get('type') in ('group', 'supergroup', 'channel'):
            db.execute('INSERT INTO updates(update_id,kind,payload) VALUES(?,?,?)',
                       (uid, kind, json.dumps(update, ensure_ascii=False)))
            db.execute('''INSERT INTO chats(chat_id,type,title,username) VALUES(?,?,?,?)
                ON CONFLICT(chat_id) DO UPDATE SET type=excluded.type,
                title=excluded.title, username=excluded.username, updated_at=CURRENT_TIMESTAMP''',
                (chat['id'], chat['type'], chat.get('title'), chat.get('username')))
            if kind == 'my_chat_member':
                db.execute('UPDATE chats SET bot_status=? WHERE chat_id=?',
                           (item['new_chat_member']['status'], chat['id']))
            elif kind in KINDS:
                sender = item.get('from', {})
                values = (chat['id'], item['message_id'], sender.get('id'),
                          ' '.join(filter(None, [sender.get('first_name'), sender.get('last_name')])),
                          sender.get('username'), item.get('sender_chat', {}).get('id'),
                          item.get('date'), item.get('edit_date'), item.get('text'),
                          item.get('caption'), item.get('message_thread_id'), item.get('media_group_id'),
                          item.get('reply_to_message', {}).get('message_id'),
                          json.dumps(item, ensure_ascii=False), uid)
                db.execute('''INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(chat_id,message_id) DO UPDATE SET
                    sender_id=excluded.sender_id, sender_name=excluded.sender_name,
                    sender_username=excluded.sender_username, sender_chat_id=excluded.sender_chat_id,
                    sent_at=excluded.sent_at, edited_at=excluded.edited_at, text=excluded.text,
                    caption=excluded.caption, thread_id=excluded.thread_id,
                    media_group_id=excluded.media_group_id,
                    reply_to_message_id=excluded.reply_to_message_id,
                    payload=excluded.payload, last_update_id=excluded.last_update_id
                    WHERE excluded.last_update_id > messages.last_update_id''', values)
        db.execute('''INSERT INTO state(key,value) VALUES('offset',?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (str(uid + 1),))


def main():
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    data = ROOT / 'data'
    data.mkdir(mode=0o700, exist_ok=True)
    lock = (data / 'receiver.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logging.error('Another receiver is already running')
        return
    token = json.loads((ROOT / 'config.json').read_text())['token']
    db = connect(data / 'messages.sqlite3')
    delay = 2
    while True:
        try:
            webhook = api(token, 'getWebhookInfo')
            if webhook.get('url'):
                logging.error('An existing webhook is configured; polling will not replace it')
                time.sleep(60)
                continue
            me = api(token, 'getMe')
            logging.info('Connected as @%s; privacy_disabled=%s',
                         me['username'], me.get('can_read_all_group_messages', False))
            while True:
                row = db.execute("SELECT value FROM state WHERE key='offset'").fetchone()
                params = {'timeout': 30, 'allowed_updates': ALLOWED}
                if row:
                    params['offset'] = int(row[0])
                updates = api(token, 'getUpdates', **params)
                for update in updates:
                    store(db, update)
                if updates:
                    logging.info('Committed %d updates', len(updates))
                delay = 2
        except ApiError as error:
            logging.warning('%s; retrying', error)
            time.sleep(max(delay, error.retry_after))
            delay = min(delay * 2, 60)
        except (sqlite3.Error, ValueError, KeyError):
            logging.error('Storage or response error; offset retained, retrying')
            time.sleep(10)


if __name__ == '__main__':
    main()
