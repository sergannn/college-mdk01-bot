#!/usr/bin/env python3
"""Import one Telegram Desktop JSON chat export, keeping live messages intact."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from bot import ROOT, connect


def flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(flatten(part) for part in value)
    if isinstance(value, dict):
        return flatten(value.get('text', ''))
    raise ValueError('Unsupported text format')


def export_chat_id(chat):
    raw = abs(int(chat['id']))
    kind = chat.get('type', '')
    if kind in ('private_group', 'public_group', 'private_supergroup',
                'public_supergroup', 'private_channel', 'public_channel'):
        # Desktop identifies supergroups with their own export type.
        return -(1_000_000_000_000 + raw) if 'supergroup' in kind or 'channel' in kind else -raw
    raise ValueError(f'Unsupported export chat type: {kind}')


def prepare(db, chat, chat_id):
    if not isinstance(chat.get('messages'), list):
        raise ValueError('Export one group as JSON; this file has no messages list')
    expected = export_chat_id(chat)
    if expected != chat_id:
        raise ValueError(f'Export belongs to chat {expected}, not {chat_id}; do not merge migrated chat IDs')
    known = db.execute('SELECT title FROM chats WHERE chat_id=?', (chat_id,)).fetchone()
    if not known:
        raise ValueError('Target chat is not known to the bot')
    records = []
    ids = set()
    old_chat_ids = {row[0] for row in db.execute('SELECT chat_id,payload FROM messages')
                    if json.loads(row[1]).get('migrate_to_chat_id') == chat_id}
    for message in chat['messages']:
        exported_id = int(message['id'])
        if exported_id in ids:
            raise ValueError(f'Duplicate message ID {exported_id} in export')
        ids.add(exported_id)
        target_chat_id = chat_id
        if exported_id < 0:
            if len(old_chat_ids) != 1:
                raise ValueError('Migrated history requires an unambiguous source group recorded by the bot')
            target_chat_id = next(iter(old_chat_ids))
        # Basic-group message IDs belong to each account, not to the chat.
        # Keep imported IDs negative, outside the positive Bot API namespace.
        basic = chat.get('type') in ('private_group', 'public_group') or exported_id < 0
        mid = -abs(exported_id) if basic else exported_id
        sent_at = int(message['date_unixtime'])
        edited_at = int(message['edited_unixtime']) if message.get('edited_unixtime') else None
        sender = message.get('from_id') or message.get('actor_id', '')
        sender_id = int(sender[4:]) if sender.startswith('user') and sender[4:].isdigit() else None
        sender_chat_id = -(1_000_000_000_000 + int(sender[7:])) if sender.startswith('channel') and sender[7:].isdigit() else None
        text = flatten(message.get('text', ''))
        payload = json.dumps({'source': 'telegram_desktop_export', 'message': message}, ensure_ascii=False)
        records.append((target_chat_id, mid, sender_id, message.get('from') or message.get('actor'),
                        sender_chat_id, sent_at, edited_at, text,
                        message.get('reply_to_message_id'), payload))
    return records


def resolve(db, records):
    """Match only unambiguous basic-group overlaps, retaining raw export IDs."""
    signatures = Counter((r[0], r[2], r[5], r[7]) for r in records if r[1] < 0)
    resolved = []
    for row in records:
        cid, mid, sender, name, sender_chat, sent, edited, text, reply, payload = row
        if mid < 0 and sender is not None and text and signatures[(cid, sender, sent, text)] == 1:
            matches = db.execute('''SELECT message_id FROM messages
                WHERE chat_id=? AND sender_id=? AND sent_at=?
                AND COALESCE(text,caption,'')=? AND last_update_id>=0''',
                (cid, sender, sent, text)).fetchall()
            if len(matches) == 1:
                mid = matches[0][0]
        elif mid < 0:
            original = json.loads(payload)['message']
            if original.get('action') == 'migrate_to_supergroup':
                matches = [(m, p) for m, p in db.execute('''SELECT message_id,payload FROM messages
                    WHERE chat_id=? AND sender_id IS ? AND sent_at=? AND last_update_id>=0''',
                    (cid, sender, sent)) if json.loads(p).get('migrate_to_chat_id')]
                if len(matches) == 1:
                    mid = matches[0][0]
        resolved.append((cid, mid, sender, name, sender_chat, sent, edited, text, reply, payload))
    return resolved


def apply(db, records, digest):
    db.execute('''CREATE TABLE IF NOT EXISTS imported_messages (
        chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
        export_sha256 TEXT NOT NULL, payload TEXT NOT NULL,
        imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(chat_id,message_id,export_sha256))''')
    inserted = 0
    with db:
        db.execute('BEGIN IMMEDIATE')
        for cid, mid, sender, name, sender_chat, sent, edited, text, reply, payload in resolve(db, records):
            db.execute('''INSERT OR IGNORE INTO imported_messages
                (chat_id,message_id,export_sha256,payload) VALUES(?,?,?,?)''',
                (cid, json.loads(payload)['message']['id'], digest, payload))
            inserted += db.execute('''INSERT INTO messages
                (chat_id,message_id,sender_id,sender_name,sender_chat_id,sent_at,
                 edited_at,text,reply_to_message_id,payload,last_update_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,-1)
                ON CONFLICT(chat_id,message_id) DO NOTHING''',
                (cid, mid, sender, name, sender_chat, sent, edited, text, reply, payload)).rowcount
    return inserted


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('export', type=Path, help='result.json from an individual chat export')
    parser.add_argument('--chat-id', type=int, required=True, help='Exact chat ID, including minus sign')
    parser.add_argument('--apply', action='store_true', help='Write after validation and backup; default is preview')
    args = parser.parse_args()
    path = ROOT / 'data/messages.sqlite3'
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        raw = args.export.read_bytes()
        chat = json.loads(raw)
        records = prepare(db, chat, args.chat_id)
        resolved = resolve(db, records)
        new = sum(not db.execute('SELECT 1 FROM messages WHERE chat_id=? AND message_id=?',
                                row[:2]).fetchone() for row in resolved)
        print(f'Chat: {chat.get("name", "")} ({args.chat_id})')
        print(f'Export messages: {len(records)}; new: {new}; already archived: {len(records)-new}')
        if not args.apply:
            print('Preview only. Add --apply to import.')
            return
        backup_path = path.parent / ('before-import-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
        db.close()
        db = connect(path)
        inserted = apply(db, records, hashlib.sha256(raw).hexdigest())
        print(f'Imported: {inserted}; preserved existing: {len(records)-inserted}')
        print(f'Backup: {backup_path}')
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'Import failed: {error}\n')
    finally:
        db.close()


if __name__ == '__main__':
    main()
