#!/usr/bin/env python3
"""Build an encrypted, browser-readable snapshot without publishing SQLite or credentials."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
from course_analysis import build as build_course_analysis

ROOT = Path(__file__).resolve().parent


def snapshot(db):
    db.row_factory = sqlite3.Row
    chats = {r['chat_id']: dict(r) for r in db.execute('SELECT chat_id,title FROM chats')}
    rows = list(db.execute('SELECT * FROM messages ORDER BY sent_at,chat_id,message_id'))
    images = {}
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_media'").fetchone():
        for image in db.execute('SELECT chat_id,message_id,sha256,mime_type FROM message_media'):
            images.setdefault((image['chat_id'], image['message_id']), []).append(
                {'path': f'media/{image["sha256"]}.bin', 'mime': image['mime_type']})
    aliases = {}
    for row in rows:
        payload = json.loads(row['payload'])
        if payload.get('migrate_to_chat_id'):
            aliases[row['chat_id']] = payload['migrate_to_chat_id']
    groups = {}
    messages = []
    for row in rows:
        cid = aliases.get(row['chat_id'], row['chat_id'])
        gid = str(cid)
        groups[gid] = {'id': gid, 'title': chats.get(cid, chats[row['chat_id']])['title']}
        payload = json.loads(row['payload'])
        imported = payload.get('source') == 'telegram_desktop_export'
        raw = payload['message'] if imported else payload
        service = raw.get('type') == 'service' if imported else any(k in raw for k in (
            'new_chat_members', 'left_chat_member', 'new_chat_title', 'new_chat_photo',
            'delete_chat_photo', 'group_chat_created', 'supergroup_chat_created',
            'migrate_to_chat_id', 'migrate_from_chat_id', 'pinned_message'))
        media = []
        if imported:
            if raw.get('photo'):
                media.append('Фото')
            if raw.get('file'):
                media.append({'voice_message':'Голосовое', 'video_file':'Видео',
                              'sticker':'Стикер', 'audio_file':'Аудио'}.get(raw.get('media_type'), 'Файл'))
            if raw.get('poll'):
                media.append('Опрос')
        else:
            for key, label in [('photo','Фото'),('video','Видео'),('document','Файл'),
                               ('voice','Голосовое'),('audio','Аудио'),('sticker','Стикер'),('poll','Опрос')]:
                if raw.get(key):
                    media.append(label)
        name = row['sender_name'] or raw.get('actor') or raw.get('sender_chat', {}).get('title') or 'Без имени'
        author_id = row['sender_id'] or row['sender_chat_id']
        messages.append({'id': f'{row["chat_id"]}:{row["message_id"]}', 'group': gid,
                         'author': name, 'authorKey': str(author_id) if author_id else name,
                         'date': row['sent_at'], 'edited': row['edited_at'],
                         'text': row['text'] or row['caption'] or '', 'media': media,
                         'images': images.get((row['chat_id'], row['message_id']), []),
                         'service': bool(service), 'action': raw.get('action') if service else None,
                         'source': 'История' if imported else 'Бот'})
    return {'generatedAt': datetime.now(timezone.utc).isoformat(),
            'courseAnalysis': build_course_analysis(db),
            'groups': sorted(groups.values(), key=lambda x:x['title']), 'messages': messages}


def main():
    os.umask(0o077)
    password_path = ROOT / 'data/pages-password.txt'
    if not password_path.exists():
        password_path.write_text(secrets.token_urlsafe(24) + '\n')
        password_path.chmod(0o600)
    password = password_path.read_text().strip()
    if len(password) < 16:
        raise SystemExit('Snapshot password must be at least 16 characters')
    path = ROOT / 'data/messages.sqlite3'
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        data = snapshot(db)
        assets = []
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='message_media'").fetchone():
            assets = [dict(row) for row in db.execute('SELECT DISTINCT sha256,local_path FROM message_media')]
    docs = ROOT / 'docs'
    docs.mkdir(exist_ok=True)
    (docs / 'media').mkdir(exist_ok=True)
    media_version = secrets.token_hex(8)
    for message in data['messages']:
        for image in message['images']:
            image['path'] = image['path'].replace('.bin', '-' + media_version + '.bin')
    script = '''
      import {pbkdf2Sync,randomBytes,createCipheriv} from 'node:crypto';
      import {readFileSync,writeFileSync} from 'node:fs';
      let input=''; for await (const part of process.stdin) input+=part;
      const {password,payload,assets,output,mediaVersion}=JSON.parse(input);
      const salt=randomBytes(16),iv=randomBytes(12),iterations=310000;
      const key=pbkdf2Sync(password,salt,iterations,32,'sha256');
      const cipher=createCipheriv('aes-256-gcm',key,iv);
      const bytes=Buffer.concat([cipher.update(JSON.stringify(payload),'utf8'),cipher.final(),cipher.getAuthTag()]);
      for(const asset of assets){
        const photoIv=randomBytes(12),photoCipher=createCipheriv('aes-256-gcm',key,photoIv);
        const photoBytes=Buffer.concat([photoIv,photoCipher.update(readFileSync(asset.local_path)),photoCipher.final(),photoCipher.getAuthTag()]);
        writeFileSync(output+'/media/'+asset.sha256+'-'+mediaVersion+'.bin',photoBytes);
      }
      process.stdout.write(JSON.stringify({version:1,algorithm:'AES-256-GCM',kdf:'PBKDF2-SHA256',iterations,
        salt:salt.toString('base64'),iv:iv.toString('base64'),ciphertext:bytes.toString('base64')}));
    '''
    result = subprocess.run(['node','--input-type=module','-e',script],
                            input=json.dumps({'password': password, 'payload': data,
                                              'assets': assets, 'output': str(docs),
                                              'mediaVersion': media_version}),
                            capture_output=True, text=True, check=True)
    tmp = docs / '.archive.tmp'
    tmp.write_text(result.stdout + '\n')
    tmp.replace(docs / 'archive.enc.json')
    for old in (docs / 'media').glob('*.bin'):
        if not old.name.endswith('-' + media_version + '.bin'):
            old.unlink()
    print(f'Encrypted snapshot: {len(data["messages"])} records, {len(data["groups"])} groups')
    print(f'Encrypted image files: {len(assets)}')
    print(f'Password is stored only at {password_path}')


if __name__ == '__main__':
    main()
