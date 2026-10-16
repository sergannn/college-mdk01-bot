"""Private local storage for photos contained in Telegram Desktop exports."""
import hashlib
import json
from pathlib import Path
import shutil


def image_type(header, sticker=False):
    if header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg', '.jpg'
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png', '.png'
    if header.startswith((b'GIF87a', b'GIF89a')):
        return 'image/gif', '.gif'
    if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
        return 'image/webp', '.webp'
    if sticker and header.startswith(b'\x1f\x8b'):
        return 'application/x-tgsticker', '.tgs'
    if sticker and header.startswith(b'\x1aE\xdf\xa3'):
        return 'video/webm', '.webm'
    raise ValueError('Unsupported or invalid image file')


def import_photos(db, resolved_records, export_root, storage_root):
    export_root = Path(export_root).resolve()
    storage_root = Path(storage_root)
    storage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    assets = []
    missing = 0
    for row in resolved_records:
        raw = json.loads(row[-1])['message']
        photo = raw.get('photo')
        sticker = raw.get('media_type') == 'sticker'
        if not photo and (sticker or raw.get('mime_type', '').startswith('image/')):
            photo = raw.get('file')
        if not photo:
            continue
        source = (export_root / photo).resolve()
        if not source.is_relative_to(export_root):
            raise ValueError('Image path is outside the export folder')
        if not source.is_file():
            missing += 1
            continue
        with source.open('rb') as stream:
            mime, ext = image_type(stream.read(16), sticker=sticker)
            stream.seek(0)
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        dest = storage_root / (digest + ext)
        if not dest.exists():
            shutil.copyfile(source, dest)
            dest.chmod(0o600)
        assets.append((row[0], row[1], digest, mime, str(dest.resolve())))
    db.execute('''CREATE TABLE IF NOT EXISTS message_media (
        chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, sha256 TEXT NOT NULL,
        mime_type TEXT NOT NULL, local_path TEXT NOT NULL,
        PRIMARY KEY(chat_id,message_id,sha256))''')
    with db:
        db.executemany('INSERT OR IGNORE INTO message_media VALUES(?,?,?,?,?)', assets)
    return {'available': len(assets), 'missing': missing}
