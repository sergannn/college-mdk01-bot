import base64
import json
import gzip
from pathlib import Path
import tempfile
import unittest

from bot import connect
from build_snapshot import snapshot
from media_store import import_photos


class PhotoImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'export/photos').mkdir(parents=True)
        self.photo = self.root / 'export/photos/test.png'
        self.photo.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j8i8AAAAASUVORK5CYII='))
        self.db = connect(':memory:')
        with self.db:
            self.db.execute("INSERT INTO chats(chat_id,title) VALUES(-123,'Группа')")
            self.db.execute('''INSERT INTO messages(chat_id,message_id,sent_at,payload,last_update_id)
                               VALUES(-123,-5,1700000000,'{}',-1)''')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def records(self, photo):
        return [(-123,-5,42,'Иван',None,1700000000,None,'',None,
                 json.dumps({'source':'telegram_desktop_export','message':{'id':5,'photo':photo}}))]

    def test_photos_are_copied_once_and_linked_to_snapshot(self):
        records = self.records('photos/test.png')
        for _ in range(2):
            result = import_photos(self.db, records, self.root/'export', self.root/'private')
            self.assertEqual(result, {'available':1,'missing':0})
        self.assertEqual(self.db.execute('SELECT count(*) FROM message_media').fetchone()[0],1)
        photo = self.db.execute('SELECT local_path FROM message_media').fetchone()[0]
        self.assertEqual(Path(photo).read_bytes(), self.photo.read_bytes())
        data = snapshot(self.db)
        self.assertEqual(data['messages'][0]['images'][0]['mime'],'image/png')
        self.assertNotIn(str(self.root), json.dumps(data))

    def test_parent_path_rejected(self):
        with self.assertRaises(ValueError):
            import_photos(self.db, self.records('../secret.png'), self.root/'export', self.root/'private')

    def test_missing_photo_reported(self):
        result = import_photos(self.db, self.records('photos/missing.png'), self.root/'export', self.root/'private')
        self.assertEqual(result, {'available':0,'missing':1})

    def test_image_sent_as_document_is_imported(self):
        record = list(self.records('unused')[0])
        record[-1] = json.dumps({'source':'telegram_desktop_export','message':{
            'id':5,'file':'photos/test.png','mime_type':'image/png'}})
        result = import_photos(self.db, [record], self.root/'export', self.root/'private')
        self.assertEqual(result, {'available':1,'missing':0})

    def test_animated_sticker_is_kept_as_downloadable_original(self):
        (self.root/'export/sticker.tgs').write_bytes(gzip.compress(b'{"v":"5.7"}'))
        record = list(self.records('unused')[0])
        record[-1] = json.dumps({'source':'telegram_desktop_export','message':{
            'id':5,'file':'sticker.tgs','media_type':'sticker','mime_type':'application/x-tgsticker'}})
        result = import_photos(self.db, [record], self.root/'export', self.root/'private')
        self.assertEqual(result, {'available':1,'missing':0})
        self.assertEqual(self.db.execute('SELECT mime_type FROM message_media').fetchone()[0],'application/x-tgsticker')


if __name__ == '__main__':
    unittest.main()
