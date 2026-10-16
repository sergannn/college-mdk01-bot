import copy
import json
import unittest

from bot import connect, store


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(':memory:')
        self.update = {'update_id': 100, 'message': {
            'message_id': 7, 'date': 1700000000,
            'chat': {'id': -123, 'type': 'supergroup', 'title': 'Учебная группа'},
            'from': {'id': 42, 'first_name': 'Иван'}, 'text': 'Привет',
            'photo': [{'file_id': 'photo-id', 'file_unique_id': 'unique'}]}}

    def tearDown(self):
        self.db.close()

    def test_edit_history_and_redelivery(self):
        store(self.db, self.update)
        store(self.db, self.update)
        edited = copy.deepcopy(self.update)
        edited['update_id'] = 101
        message = edited.pop('message')
        message.update(text='Исправлено', edit_date=1700000100)
        edited['edited_message'] = message
        store(self.db, edited)
        self.assertEqual(self.db.execute('SELECT count(*) FROM updates').fetchone()[0], 2)
        rows = self.db.execute('SELECT text,payload FROM messages').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], 'Исправлено')
        self.assertEqual(json.loads(rows[0][1])['photo'][0]['file_id'], 'photo-id')
        self.assertEqual(self.db.execute('SELECT value FROM state').fetchone()[0], '102')

    def test_storage_failure_does_not_acknowledge_update(self):
        store(self.db, self.update)
        broken = copy.deepcopy(self.update)
        broken['update_id'] = 101
        del broken['message']['message_id']
        with self.assertRaises(KeyError):
            store(self.db, broken)
        self.assertEqual(self.db.execute('SELECT count(*) FROM updates').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT value FROM state').fetchone()[0], '101')

    def test_private_chat_excluded_and_channel_supported(self):
        private = copy.deepcopy(self.update)
        private['message']['chat']['type'] = 'private'
        store(self.db, private)
        self.assertEqual(self.db.execute('SELECT count(*) FROM updates').fetchone()[0], 0)
        channel = copy.deepcopy(self.update)
        channel['update_id'] = 101
        channel['channel_post'] = channel.pop('message')
        channel['channel_post']['chat']['type'] = 'channel'
        store(self.db, channel)
        self.assertEqual(self.db.execute('SELECT count(*) FROM messages').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
