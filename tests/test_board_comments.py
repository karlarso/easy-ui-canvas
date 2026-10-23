#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Board-wide comments, server side (scripts/canvas.py): frame title / subtitle targets, notes (project.notes) and their elements, the
"Canvas" frame column, stored position, group title bar targets (group~<name>~title), notes validation, annotated serving (live and snapshot), and that comments inside the phone and
comments saved before this feature keep their exact shape. Python 3.9-compatible; stdlib only. Run: python3 tests/test_board_comments.py
Uses a temp project dir and an ephemeral 127.0.0.1 port only."""
import http.client
import importlib.util
import json
import os
import shutil
import tempfile
import threading
import unittest
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

SKILL = Path(os.environ.get('UIC_SKILL', str(Path(__file__).resolve().parents[1])))
spec = importlib.util.spec_from_file_location('canvas_mod', SKILL / 'scripts' / 'canvas.py')
canvas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canvas)
canvas.Handler.log_message = lambda self, *a, **k: None
DICT = json.loads((SKILL / 'assets' / 'i18n.json').read_text(encoding='utf-8'))

# The record of a comment inside a phone, exactly as it was before notes existed.
OLD_KEYS = ['id', 'project_id', 'revision', 'frame_id', 'frame', 'target', 'element', 'text', 'created_at', 'status', 'replies', 'source_hash', 'excerpt']

FRAME1 = '<main><h1 data-ui-id="head" data-ui-label="Heading">Hi</h1><button data-ui-id="go" data-ui-label="Go button">Go</button></main>'
FRAME2 = '<main><p>Second</p></main>'
NOTE1 = '<h3 data-ui-id="heading" data-ui-label="Note heading">Reading order</h3><p data-ui-id="tip">Start at the first screen. <small>Fine print.</small></p>'


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def project(**extra):
    data = {'id': 'board-test', 'name': 'Board', 'revision': 'r1', 'frames': [
        {'id': 'f1', 'title': 'Frame One', 'width': 390, 'height': 600, 'path': 'frames/f1.html', 'group': 'Flow A', 'state': 'Draft'},
        {'id': 'f2', 'title': 'Frame Two', 'width': 390, 'height': 600, 'path': 'frames/f2.html'}]}
    data.update(extra)
    return data


NOTE_ENTRY = {'id': 'n1', 'path': 'frames/n1.html', 'x': 900, 'y': 12, 'title': 'Reading notes'}


class BoardCommentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix='uic-board-'))
        cls.root = cls.tmp / 'canvas'
        write(cls.root / 'frames/f1.html', FRAME1)
        write(cls.root / 'frames/f2.html', FRAME2)
        write(cls.root / 'frames/n1.html', NOTE1)
        cls.save_project(project(notes=[NOTE_ENTRY]))
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), partial(canvas.Handler, root=cls.root, ctx={'id': 'board-test'}))
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    @classmethod
    def save_project(cls, data):
        write(cls.root / 'project.json', json.dumps(data))

    def request(self, method, path, body=None, lang='en'):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {'X-UIC-Lang': lang}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode('utf-8')
        conn.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw

    n = 0

    def post(self, target, text='feedback', lang='en', **extra):
        BoardCommentsTest.n += 1
        body = {'client_id': 'c%d' % BoardCommentsTest.n, 'project_id': 'board-test', 'revision': 'r1', 'target': target, 'text': text}
        body.update(extra)
        return self.request('POST', '/api/comments', body, lang)

    def setUp(self):
        self.save_project(project(notes=[NOTE_ENTRY]))

    # --- inside the phone: unchanged ------------------------------------------------------------------------------
    def test_phone_comment_record_is_exactly_the_old_shape(self):
        for target, label in (('f1--screen', 'Frame One · Whole layout'), ('f1--go', 'Go button')):
            status, data = self.post(target, position={'x': 0.25, 'y': 0.5}, excerpt='Go')
            self.assertEqual(status, 201, data)
            comment = data['comment']
            self.assertEqual(sorted(comment), sorted(OLD_KEYS))  # no position, no position_ref, no new field
            self.assertEqual((comment['frame_id'], comment['frame'], comment['target'], comment['element']), ('f1', 'Frame One', target, label))

    def test_comments_saved_before_this_feature_are_returned_unchanged(self):
        old = {'id': 'old-1', 'project_id': 'board-test', 'revision': 'r1', 'frame_id': 'f1', 'frame': 'Frame One', 'target': 'f1--go', 'element': 'Go button',
               'text': 'older', 'created_at': '2025-01-01T00:00:00+00:00', 'status': 'changed', 'replies': [{'text': 'done', 'created_at': '2025-01-02T00:00:00+00:00', 'status': 'changed'}],
               'source_hash': 'abc', 'excerpt': 'Go'}
        con = canvas.database(self.root)
        with con:
            con.execute('INSERT OR REPLACE INTO comments VALUES (?,?,?,?,?)', ('old-1', 'board-test', 'r1', 'old-client', json.dumps(old)))
        con.close()
        status, data = self.request('GET', '/api/comments')
        self.assertEqual(status, 200)
        self.assertIn(old, data['comments'])
        # the project works without any notes key, and old targets are still accepted
        data = json.loads((self.root / 'project.json').read_text())
        data.pop('notes')
        self.save_project(data)
        self.assertEqual(self.request('GET', '/api/project')[0], 200)
        self.assertEqual(self.post('f1--go')[0], 201)

    # --- frame title and subtitle ---------------------------------------------------------------------------------
    def test_title_and_subtitle_are_targets_of_their_frame(self):
        status, data = self.post('f1~title', position={'x': 0.1, 'y': 0.01})
        self.assertEqual(status, 201, data)
        c = data['comment']
        self.assertEqual((c['frame_id'], c['frame'], c['element']), ('f1', 'Frame One', 'Title: Frame One'))
        self.assertEqual((c['position'], c['position_ref']), ({'x': 0.1, 'y': 0.01}, 'frame'))
        status, data = self.post('f1~subtitle', position={'x': 0.2, 'y': 0.05})
        self.assertEqual(status, 201, data)
        self.assertEqual((data['comment']['frame_id'], data['comment']['element']), ('f1', 'Subtitle: Flow A / Draft'))
        self.assertEqual(data['comment']['position_ref'], 'frame')

    def test_subtitle_target_exists_only_when_the_frame_has_one(self):
        self.assertEqual(self.post('f2~title')[0], 201)
        status, data = self.post('f2~subtitle')
        self.assertEqual(status, 400, data)
        self.assertEqual(data['error'], DICT['en']['s.noElement'])

    def test_title_ids_cannot_collide_with_element_ids(self):
        # an element whose data-ui-id is "title" keeps its own target
        write(self.root / 'frames/f2.html', '<main><h1 data-ui-id="title" data-ui-label="Own title">x</h1></main>')
        try:
            status, data = self.post('f2--title')
            self.assertEqual((status, data['comment']['element']), (201, 'Own title'))
            self.assertEqual(self.post('f2~title')[1]['comment']['element'], 'Title: Frame Two')
        finally:
            write(self.root / 'frames/f2.html', FRAME2)

    # --- notes outside every frame --------------------------------------------------------------------------------
    def test_note_and_its_elements_belong_to_the_canvas(self):
        status, data = self.post('~note~n1', position={'x': 0.7, 'y': 0.02})
        self.assertEqual(status, 201, data)
        c = data['comment']
        self.assertEqual((c['frame_id'], c['frame'], c['element']), ('', 'Canvas', 'Note: Reading notes'))
        self.assertEqual((c['position'], c['position_ref']), ({'x': 0.7, 'y': 0.02}, 'board'))
        for key, label in (('heading', 'Note heading'), ('tip', 'tip')):
            status, data = self.post('~note~n1~' + key, position={'x': 0.7, 'y': 0.03})
            self.assertEqual(status, 201, data)
            self.assertEqual((data['comment']['frame'], data['comment']['target'], data['comment']['position_ref']), ('Canvas', '~note~n1~' + key, 'board'))
            self.assertEqual(data['comment']['element'], label)
        self.assertEqual(self.post('~note~n1~nope')[0], 400)
        self.assertEqual(self.post('~note~missing')[0], 400)

    def test_canvas_frame_column_follows_the_language(self):
        self.assertEqual(self.post('~note~n1', lang='en')[1]['comment']['frame'], DICT['en']['c.canvas'])
        self.assertEqual(self.post('~note~n1', lang='zh')[1]['comment']['frame'], DICT['zh']['c.canvas'])
        self.assertNotEqual(DICT['en']['c.canvas'], DICT['zh']['c.canvas'])

    def test_note_without_title_is_named_by_its_id(self):
        self.save_project(project(notes=[{'id': 'n1', 'path': 'frames/n1.html', 'x': 0, 'y': 0}]))
        self.assertEqual(self.post('~note~n1')[1]['comment']['element'], 'Note: n1')

    def test_position_is_optional_and_junk_is_dropped(self):
        for bad in (None, 'x', {'x': 1}, {'x': 'a', 'y': 0}, {'x': True, 'y': 0}, {'x': 1e9, 'y': 0}, {'x': float('nan'), 'y': 0}):
            extra = {} if bad is None else {'position': bad}
            status, data = self.post('~note~n1', **extra)
            self.assertEqual(status, 201, (bad, data))
            self.assertNotIn('position', data['comment'], bad)
            self.assertNotIn('position_ref', data['comment'], bad)

    def test_stored_comments_come_back_through_the_list(self):
        self.post('~note~n1~tip', text='listed on the canvas', position={'x': 0.5, 'y': 0.5})
        listed = [c for c in self.request('GET', '/api/comments')[1]['comments'] if c['text'] == 'listed on the canvas']
        self.assertEqual(len(listed), 1)
        self.assertEqual((listed[0]['frame'], listed[0]['position_ref']), ('Canvas', 'board'))

    # --- group title bars (sections of the tile view) ---------------------------------------------------------------------
    def frames_with_groups(self, groups):
        return [{'id': 'g%d' % i, 'title': 'G%d' % i, 'width': 390, 'height': 600, 'path': 'frames/f2.html', **({} if g is None else {'group': g})} for i, g in enumerate(groups)]

    def test_group_title_is_a_canvas_target_with_a_board_position(self):
        status, data = self.post('group~Flow A~title', position={'x': 0.05, 'y': 0.01})
        self.assertEqual(status, 201, data)
        c = data['comment']
        self.assertEqual((c['frame_id'], c['frame'], c['target'], c['element']), ('', 'Canvas', 'group~Flow A~title', 'Group: Flow A'))
        self.assertEqual((c['position'], c['position_ref']), ({'x': 0.05, 'y': 0.01}, 'board'))
        self.assertEqual(sorted(c), sorted(OLD_KEYS + ['position', 'position_ref']))
        # the position is optional, like for every canvas target
        status, data = self.post('group~Flow A~title', position='junk')
        self.assertEqual(status, 201, data)
        self.assertNotIn('position', data['comment'])
        self.assertNotIn('position_ref', data['comment'])
        # the frame's own subtitle (group / state) is unchanged
        self.assertEqual(self.post('f1~subtitle')[1]['comment']['element'], 'Subtitle: Flow A / Draft')

    def test_group_title_follows_the_language_and_unknown_groups_are_refused(self):
        c = self.post('group~Flow A~title', lang='zh')[1]['comment']
        self.assertEqual((c['frame'], c['element']), (DICT['zh']['c.canvas'], DICT['zh']['c.groupTitle'].replace('{title}', 'Flow A')))
        self.assertNotEqual(DICT['en']['c.groupTitle'], DICT['zh']['c.groupTitle'])
        for target in ('group~Nope~title', 'group~Flow A~2~title', 'group~Flow A', 'group~~title', 'group~title'):
            status, data = self.post(target)
            self.assertEqual((status, data['error']), (400, DICT['en']['s.noElement']), target)

    def test_group_title_targets_follow_the_sections(self):
        for groups, want in (
            ([None, None], []),
            (['', '  ', None, 5, ['x'], {}], []),  # blank or non-string groups make no bar
            (['A', 'A', 'A'], ['group~A~title']),  # one run, one bar
            (['A', 'B', 'A'], ['group~A~title', 'group~B~title', 'group~A~2~title']),  # a group that comes back is another section
            (['A', None, 'A', '', 'A'], ['group~A~title', 'group~A~2~title', 'group~A~3~title']),
            ([' A', 'A'], ['group~ A~title', 'group~A~title']),  # names are exact
            (['a', 'a~2', 'a', 'a~2'], ['group~a~title', 'group~a%7E2~title', 'group~a~2~title', 'group~a%7E2~2~title']),  # '~' is escaped: never collides with a repeat
            (['100%', '100%25'], ['group~100%25~title', 'group~100%2525~title']),
        ):
            self.assertEqual([t for t, _ in canvas.group_title_targets(self.frames_with_groups(groups))], want, groups)
            self.save_project(project(frames=self.frames_with_groups(groups)))
            _, targets = canvas.manifest(self.root)
            self.assertEqual([t for t in targets if t.startswith('group~')], want, groups)
            for target in want:
                status, data = self.post(target)
                self.assertEqual((status, data['comment']['frame_id'], data['comment']['frame']), (201, '', 'Canvas'), (groups, target))

    def test_group_title_ids_never_collide_with_frame_titles_or_elements(self):
        frames = self.frames_with_groups(['x', 'y'])
        frames[0]['id'] = 'group'  # a frame called "group": group--screen, group~title, group~subtitle
        self.save_project(project(frames=frames))
        _, targets = canvas.manifest(self.root)
        self.assertEqual(sorted(t for t in targets if t.startswith('group') and '__auto-' not in t), sorted(['group--screen', 'group~title', 'group~subtitle', 'group~x~title', 'group~y~title']))
        self.assertEqual(self.post('group~title')[1]['comment']['element'], 'Title: G0')
        self.assertEqual(self.post('group~x~title')[1]['comment']['element'], 'Group: x')

    def test_group_title_comments_come_back_through_the_list(self):
        self.post('group~Flow A~title', text='group comment in the list')
        listed = [c for c in self.request('GET', '/api/comments')[1]['comments'] if c['text'] == 'group comment in the list']
        self.assertEqual((len(listed), listed[0]['frame'], listed[0]['target']), (1, 'Canvas', 'group~Flow A~title'))

    # --- validation of project.notes -----------------------------------------------------------------------------
    def test_invalid_notes_are_rejected_with_a_translated_message(self):
        good = dict(NOTE_ENTRY)
        cases = [
            ('not a list', {'notes': {'id': 'n1'}}, 's.notesFormat'),
            ('entry not an object', {'notes': ['x']}, 's.notesFormat'),
            ('bad id', {'notes': [dict(good, id='a b')]}, 's.notesFormat'),
            ('duplicate id', {'notes': [good, dict(good)]}, 's.notesFormat'),
            ('negative x', {'notes': [dict(good, x=-1)]}, 's.notesFormat'),
            ('bool y', {'notes': [dict(good, y=True)]}, 's.notesFormat'),
            ('x too large', {'notes': [dict(good, x=20001)]}, 's.notesFormat'),
            ('width too small', {'notes': [dict(good, width=10)]}, 's.notesFormat'),
            ('title not a string', {'notes': [dict(good, title=5)]}, 's.notesFormat'),
            ('missing path', {'notes': [{'id': 'n1', 'x': 0, 'y': 0}]}, 's.notesFormat'),
            ('unknown anchor', {'notes': [dict(good, anchor='nope')]}, 's.noteAnchor'),
            ('outside frames/', {'notes': [dict(good, path='project.json')]}, 's.noteEntry'),
            ('not html', {'notes': [dict(good, path='frames/n1.txt')]}, 's.noteEntry'),
            ('missing file', {'notes': [dict(good, path='frames/none.html')]}, 's.noteEntry'),
        ]
        write(self.root / 'frames/n1.txt', 'x')
        for name, extra, key in cases:
            self.save_project(project(**extra))
            for lang in ('en', 'zh'):
                status, data = self.request('GET', '/api/project', lang=lang)
                self.assertEqual(status, 400, name)
                self.assertEqual(data['error'], DICT[lang][key].replace('{id}', 'n1'), name + ' ' + lang)
        self.save_project(project(notes=[dict(good, anchor='f2', width=200)]))
        self.assertEqual(self.request('GET', '/api/project')[0], 200)

    def test_project_json_is_served_with_notes_untouched(self):
        status, data = self.request('GET', '/api/project')
        self.assertEqual((status, data['notes']), (200, [NOTE_ENTRY]))

    # --- serving: notes get automatic targets like frames ----------------------------------------------------------
    def test_note_fragment_is_annotated_live_and_in_snapshots(self):
        status, body = self.request('GET', '/project/frames/n1.html')
        self.assertEqual(status, 200)
        self.assertIn('data-ui-id="heading"', body)
        self.assertIn('<small data-ui-id="__auto-', body)  # unmarked elements of a note get automatic targets too, like in a frame
        snap = self.root / 'snapshots' / 'r0'
        write(snap / 'project.json', json.dumps(project(revision='r0', notes=[NOTE_ENTRY])))
        write(snap / 'frames/n1.html', NOTE1)
        write(snap / 'frames/f1.html', FRAME1)
        write(snap / 'frames/f2.html', FRAME2)
        write(snap / 'frames/loose.html', '<p>not listed</p>')
        write(snap / 'comments.json', '[]')
        status, body = self.request('GET', '/api/snapshots/r0/frames/n1.html')
        self.assertEqual(status, 200)
        self.assertIn('<small data-ui-id="__auto-', body)
        status, body = self.request('GET', '/api/snapshots/r0/frames/loose.html')
        self.assertEqual((status, body), (200, '<p>not listed</p>'))  # not a frame and not a note: served as is
        status, data = self.request('GET', '/api/snapshots/r0/project')
        self.assertEqual(data['notes'], [NOTE_ENTRY])

    # --- revision the open tab loaded (may lag the live project.revision) ----------------------------------------
    def test_live_revision_write_is_stored_on_that_revision(self):
        status, data = self.post('f1--go', text='live path still works')
        self.assertEqual(status, 201, data)
        comment = data['comment']
        self.assertEqual((comment['revision'], comment['project_id'], comment['target']), ('r1', 'board-test', 'f1--go'))
        self.assertIn(comment['id'], [item['id'] for item in self.request('GET', '/api/comments')[1]['comments']])
        status, patched = self.request('PATCH', '/api/comments/' + comment['id'],
                                       {'project_id': 'board-test', 'revision': 'r1', 'status': 'discussion'})
        self.assertEqual(status, 200, patched)
        self.assertEqual((patched['comment']['status'], patched['comment']['revision']), ('discussion', 'r1'))
        status, batched = self.request('PATCH', '/api/comments/batch',
                                       {'project_id': 'board-test', 'revision': 'r1', 'ids': [comment['id']], 'status': 'changed'})
        self.assertEqual(status, 200, batched)
        self.assertEqual(batched['comments'][0]['status'], 'changed')

    def test_stale_revision_is_stored_and_listed_under_the_client_revision(self):
        self.save_project(project(notes=[NOTE_ENTRY], revision='r2'))
        status, data = self.post('f1--go', revision='r1', text='left on the open tab')
        self.assertEqual(status, 201, data)
        comment = data['comment']
        self.assertEqual((comment['revision'], comment['project_id'], comment['target']), ('r1', 'board-test', 'f1--go'))
        con = canvas.database(self.root)
        try:
            row = con.execute('SELECT project, revision FROM comments WHERE id=?', (comment['id'],)).fetchone()
        finally:
            con.close()
        self.assertEqual(row, ('board-test', 'r1'))
        live = self.request('GET', '/api/comments')[1]['comments']
        self.assertNotIn(comment['id'], [item['id'] for item in live])
        pinned = self.request('GET', '/api/comments?revision=r1')[1]['comments']
        self.assertIn(comment['id'], [item['id'] for item in pinned])
        self.assertEqual(self.request('GET', '/api/comments?revision=r-nobody')[1]['comments'], [])
        status, body = self.post('f1--go', revision='   ', text='blank rev')
        self.assertEqual((status, body['error']), (400, DICT['en']['s.projectMismatch']))
        status, body = self.request('GET', '/api/comments?revision=%20')
        self.assertEqual((status, body['error']), (400, DICT['en']['s.projectMismatch']))

    def test_stale_revision_edit_delete_and_batch(self):
        self.save_project(project(notes=[NOTE_ENTRY], revision='r9'))
        created = []
        for text in ('edit me on open rev', 'batch me on open rev', 'drop me on open rev'):
            status, data = self.post('f1--head', revision='r1', text=text)
            self.assertEqual(status, 201, data)
            created.append(data['comment'])
        status, data = self.request('PATCH', '/api/comments/' + created[0]['id'],
                                    {'project_id': 'board-test', 'revision': 'r1', 'text': 'edited on r1'})
        self.assertEqual(status, 200, data)
        self.assertEqual((data['comment']['text'], data['comment']['revision']), ('edited on r1', 'r1'))
        status, data = self.request('PATCH', '/api/comments/' + created[0]['id'],
                                    {'project_id': 'board-test', 'revision': 'r9', 'text': 'nope'})
        self.assertEqual(status, 404, data)
        status, data = self.request('PATCH', '/api/comments/batch',
                                    {'project_id': 'board-test', 'revision': 'r1', 'ids': [created[1]['id']], 'status': 'changed'})
        self.assertEqual(status, 200, data)
        self.assertEqual((data['comments'][0]['status'], data['comments'][0]['revision']), ('changed', 'r1'))
        status, data = self.request('DELETE', '/api/comments/batch',
                                    {'project_id': 'board-test', 'revision': 'r1', 'ids': [created[2]['id']]})
        self.assertEqual(status, 200, data)
        self.assertTrue(data['comments'][0].get('deleted_at'))
        listed = [item['id'] for item in self.request('GET', '/api/comments?revision=r1')[1]['comments']]
        self.assertNotIn(created[2]['id'], listed)
        self.assertIn(created[0]['id'], listed)
        status, data = self.request('DELETE', '/api/comments/' + created[0]['id'],
                                    {'project_id': 'board-test', 'revision': 'r1'})
        self.assertEqual(status, 200, data)
        self.assertTrue(data['comment'].get('deleted_at'))
        self.assertEqual(data['comment']['revision'], 'r1')

    def test_wrong_project_id_is_rejected_for_live_and_stale_revisions(self):
        self.save_project(project(notes=[NOTE_ENTRY], revision='r2'))
        for revision in ('r2', 'r1'):
            status, data = self.post('f1--go', project_id='other-project', revision=revision, text='wrong project')
            self.assertEqual(status, 400, (revision, data))
            self.assertEqual(data['error'], DICT['en']['s.projectMismatch'])
        status, made = self.post('f1--go', revision='r1', text='owned by this project')
        self.assertEqual(status, 201, made)
        cid = made['comment']['id']
        for method, body in (
            ('PATCH', {'project_id': 'other-project', 'revision': 'r1', 'text': 'x'}),
            ('DELETE', {'project_id': 'other-project', 'revision': 'r1'}),
        ):
            status, data = self.request(method, '/api/comments/' + cid, body)
            self.assertEqual((status, data['error']), (400, DICT['en']['s.projectMismatch']), method)
        status, data = self.request('PATCH', '/api/comments/batch',
                                    {'project_id': 'other-project', 'revision': 'r1', 'ids': [cid], 'status': 'changed'})
        self.assertEqual((status, data['error']), (400, DICT['en']['s.projectMismatch']))
        status, data = self.request('DELETE', '/api/comments/batch',
                                    {'project_id': 'other-project', 'revision': 'r1', 'ids': [cid]})
        self.assertEqual((status, data['error']), (400, DICT['en']['s.projectMismatch']))

    def test_missing_target_still_fails_when_no_snapshot_exists(self):
        self.save_project(project(notes=[NOTE_ENTRY], revision='r2'))
        status, data = self.post('f1--gone', revision='r1', text='no such element')
        self.assertEqual((status, data['error']), (400, DICT['en']['s.noElement']))

    def test_pinned_revision_uses_its_snapshot_manifest_when_one_exists(self):
        snap = self.root / 'snapshots' / 'pinned'
        foreign = self.root / 'snapshots' / 'foreign'
        broken = self.root / 'snapshots' / 'brokenrev'
        try:
            write(snap / 'project.json', json.dumps({
                'id': 'board-test', 'name': 'Board', 'revision': 'pinned',
                'frames': [{'id': 'f1', 'title': 'Old Frame', 'width': 390, 'height': 600, 'path': 'frames/f1.html'}]}))
            write(snap / 'frames/f1.html', '<main><button data-ui-id="oldbtn" data-ui-label="Old button">Old</button></main>')
            self.save_project(project(notes=[NOTE_ENTRY], revision='r2'))
            status, data = self.post('f1--oldbtn', revision='pinned', text='on the snapshot element')
            self.assertEqual(status, 201, data)
            self.assertEqual((data['comment']['revision'], data['comment']['element'], data['comment']['frame']),
                             ('pinned', 'Old button', 'Old Frame'))
            status, data = self.post('f1--go', revision='pinned', text='live element on old rev')
            self.assertEqual((status, data['error']), (400, DICT['en']['s.noElement']))
            # A snapshot of another project is not this revision's manifest; the live files are.
            write(foreign / 'project.json', json.dumps({
                'id': 'someone-else', 'name': 'Other', 'revision': 'foreign',
                'frames': [{'id': 'f1', 'title': 'X', 'width': 390, 'height': 600, 'path': 'frames/f1.html'}]}))
            write(foreign / 'frames/f1.html', '<main><i data-ui-id="secret" data-ui-label="Secret">s</i></main>')
            status, data = self.post('f1--secret', revision='foreign', text='foreign target')
            self.assertEqual((status, data['error']), (400, DICT['en']['s.noElement']))
            status, data = self.post('f1--go', revision='foreign', text='falls back to live files')
            self.assertEqual(status, 201, data)
            self.assertEqual(data['comment']['revision'], 'foreign')
            write(broken / 'project.json', '{')
            status, data = self.post('f1--go', revision='brokenrev', text='broken snapshot still allows a live target')
            self.assertEqual(status, 201, data)
            self.assertEqual(data['comment']['revision'], 'brokenrev')
        finally:
            for folder in (snap, foreign, broken):
                shutil.rmtree(str(folder), ignore_errors=True)

    def test_comments_report_flags_other_revisions(self):
        self.save_project(project(notes=[NOTE_ENTRY], revision='r2'))
        status, data = self.post('f1--go', revision='r1', text='counted on the open revision')
        self.assertEqual(status, 201, data)
        config, _ = canvas.manifest(self.root)
        report = canvas.comments_report(self.root, config, False)
        self.assertEqual(report['project_id'], 'board-test')
        self.assertNotIn(data['comment']['id'], [item['id'] for item in report['comments']])
        self.assertGreaterEqual(report['other_revisions'].get('r1', 0), 1)
        self.assertNotIn('r2', report['other_revisions'])
        everything = canvas.comments_report(self.root, config, True)
        self.assertNotIn('other_revisions', everything)
        self.assertIn(data['comment']['id'], [item['id'] for item in everything['comments']])

    def test_open_tab_requests_the_revision_it_loaded(self):
        source = (SKILL / 'assets' / 'canvas.js').read_text(encoding='utf-8')
        self.assertIn("fetch('/api/comments?revision='+encodeURIComponent(revision))", source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
