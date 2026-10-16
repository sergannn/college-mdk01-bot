import copy
import unittest

from bot import connect, store
from import_history import apply, prepare


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        with self.db:
            self.db.execute("INSERT INTO chats(chat_id,type,title) VALUES(-123,'group','Группа')")
        self.chat = {'id': 123, 'type': 'private_group', 'name': 'Группа', 'messages': [
            {'id': 1, 'date_unixtime': '1700000000', 'from': 'Иван', 'from_id': 'user42',
             'text': ['Привет ', {'type': 'bold', 'text': 'всем'}], 'photo': 'photos/a.jpg'}]}

    def tearDown(self):
        self.db.close()

    def test_repeat_import_keeps_offset_and_no_duplicates(self):
        rows = prepare(self.db, self.chat, -123)
        self.assertEqual(apply(self.db, rows, 'digest'), 1)
        self.assertEqual(apply(self.db, rows, 'digest'), 0)
        self.assertEqual(self.db.execute('SELECT text,sender_id FROM messages').fetchone(), ('Привет всем', 42))
        self.assertEqual(self.db.execute('SELECT count(*) FROM imported_messages').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT count(*) FROM state').fetchone()[0], 0)

    def test_live_message_wins_and_import_preserves_it(self):
        rows = prepare(self.db, self.chat, -123)
        store(self.db, {'update_id': 100, 'edited_message': {
            'message_id': 1, 'date': 1700000000, 'edit_date': 1700001000,
            'from': {'id': 42},
            'chat': {'id': -123, 'type': 'group', 'title': 'Группа'}, 'text': 'Привет всем'}})
        self.assertEqual(apply(self.db, rows, 'another-export'), 0)
        self.assertEqual(self.db.execute('SELECT text,last_update_id FROM messages').fetchone(), ('Привет всем', 100))
        self.assertEqual(self.db.execute('SELECT value FROM state').fetchone()[0], '101')

    def test_account_specific_basic_group_ids(self):
        self.chat['messages'][0]['id'] = 600001
        store(self.db, {'update_id': 100, 'message': {
            'message_id': 7, 'date': 1700000000, 'from': {'id': 42},
            'chat': {'id': -123, 'type': 'group'}, 'text': 'Привет всем'}})
        rows = prepare(self.db, self.chat, -123)
        self.assertEqual(apply(self.db, rows, 'one'), 0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM messages').fetchone()[0], 1)

    def test_migrated_export_history_keeps_source_group(self):
        store(self.db, {'update_id': 100, 'message': {
            'message_id': 5, 'date': 1700001000, 'from': {'id': 42},
            'chat': {'id': -123, 'type': 'group'}, 'migrate_to_chat_id': -1000000000456}})
        with self.db:
            self.db.execute("INSERT INTO chats(chat_id,type) VALUES(-1000000000456,'supergroup')")
        self.chat['id'] = 456
        self.chat['type'] = 'private_supergroup'
        self.chat['messages'][0]['id'] = -999000001
        rows = prepare(self.db, self.chat, -1000000000456)
        self.assertEqual(rows[0][0], -123)
        self.assertEqual(rows[0][1], -999000001)

    def test_reject_wrong_chat_and_migration_merge(self):
        with self.assertRaises(ValueError):
            prepare(self.db, self.chat, -1000000000123)
        changed = copy.deepcopy(self.chat)
        changed['type'] = 'private_supergroup'
        with self.assertRaises(ValueError):
            prepare(self.db, changed, -123)

    def test_invalid_file_validates_before_writing(self):
        self.chat['messages'].append({'id': 2, 'date_unixtime': 'invalid'})
        with self.assertRaises(ValueError):
            prepare(self.db, self.chat, -123)
        self.assertEqual(self.db.execute('SELECT count(*) FROM messages').fetchone()[0], 0)

    def test_pre_migration_history_without_known_old_group(self):
        with self.db:
            self.db.execute("INSERT INTO chats(chat_id,type) VALUES(-1000000000456,'supergroup')")
        self.chat['id'] = 456
        self.chat['type'] = 'private_supergroup'
        self.chat['messages'][0]['id'] = -999000001
        rows = prepare(self.db, self.chat, -1000000000456)
        self.assertEqual(rows[0][0], -1000000000456)
        self.assertEqual(apply(self.db, rows, 'digest'), 1)


if __name__ == '__main__':
    unittest.main()
