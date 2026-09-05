"""Document store API.

Files here are handed to the agent subprocess and attached to third-party
forms, so the store must only accept sane files, keep users apart, keep the
original filename (it is what an employer receives), and never let a
client-supplied name become a path.
"""

import io
import json

import pytest
from fastapi.testclient import TestClient

import server
from tests.test_server import auth_headers  # shared auth seam


@pytest.fixture()
def documents_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(server, 'USER_DOCUMENTS_DIR', str(tmp_path))
    return tmp_path


def _upload(client, label, filename, content=b'%PDF-1.4', user_id=1, content_type='application/pdf'):
    return client.post(
        '/api/documents',
        headers=auth_headers(user_id),
        data={'label': label},
        files={'file': (filename, content, content_type)},
    )


def test_documents_require_token(documents_dir):
    client = TestClient(server.app)
    assert client.get('/api/documents').status_code == 401


def test_listing_offers_suggested_labels(documents_dir):
    client = TestClient(server.app)
    resp = client.get('/api/documents', headers=auth_headers(1))
    assert resp.status_code == 200
    assert resp.json()['documents'] == {}
    assert 'Resume' in resp.json()['suggested_labels']


def test_upload_rejects_a_label_with_nothing_usable_in_it(documents_dir):
    client = TestClient(server.app)
    assert _upload(client, '!!!', 'r.pdf').status_code == 400
    assert _upload(client, '   ', 'r.pdf').status_code == 400


def test_upload_rejects_unsupported_extension(documents_dir):
    client = TestClient(server.app)
    resp = _upload(client, 'Resume', 'resume.exe', b'MZ', content_type='application/octet-stream')
    assert resp.status_code == 400


def test_upload_rejects_oversize_files(documents_dir):
    client = TestClient(server.app)
    big = io.BytesIO(b'a' * (server.DOCUMENT_MAX_BYTES + 1))
    assert _upload(client, 'Resume', 'resume.pdf', big).status_code == 413


def test_upload_keeps_the_original_filename_under_the_label_slug(documents_dir):
    client = TestClient(server.app)
    resp = _upload(client, 'Resume', 'Edwin_Villanueva_Resume.pdf')
    assert resp.status_code == 200
    listing = resp.json()['documents']
    assert listing == {
        'resume': {
            'label': 'Resume',
            'filename': 'Edwin_Villanueva_Resume.pdf',
            'size': len(b'%PDF-1.4'),
            'updated_at': listing['resume']['updated_at'],
        }
    }
    assert (documents_dir / '1' / 'resume' / 'Edwin_Villanueva_Resume.pdf').is_file()


def test_replacing_a_label_leaves_exactly_one_file(documents_dir):
    client = TestClient(server.app)
    _upload(client, 'Resume', 'old.pdf', b'%PDF-1.4 old')
    resp = _upload(client, 'Resume', 'new.docx', b'PK new', content_type='application/octet-stream')
    assert resp.status_code == 200
    stored = sorted(p.name for p in (documents_dir / '1' / 'resume').iterdir())
    assert stored == ['new.docx']
    assert resp.json()['documents']['resume']['filename'] == 'new.docx'


def test_custom_label_survives_the_round_trip(documents_dir):
    client = TestClient(server.app)
    resp = _upload(client, 'Transcript (Fall 2025)', 'transcript.pdf')
    assert resp.status_code == 200
    doc = resp.json()['documents']['transcript_fall_2025']
    assert doc['label'] == 'Transcript (Fall 2025)'
    # The label is what the manifest is for; the listing itself comes from disk.
    manifest = json.loads((documents_dir / '1' / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest == {'transcript_fall_2025': 'Transcript (Fall 2025)'}


def test_client_filename_cannot_escape_the_slug_directory(documents_dir):
    client = TestClient(server.app)
    resp = _upload(client, 'Resume', '../../evil.pdf')
    assert resp.status_code == 200
    assert resp.json()['documents']['resume']['filename'] == 'evil.pdf'
    assert (documents_dir / '1' / 'resume' / 'evil.pdf').is_file()
    assert not (documents_dir / 'evil.pdf').exists()


def test_unusable_filename_falls_back_to_the_slug(documents_dir):
    client = TestClient(server.app)
    resp = _upload(client, 'Cover letter', '???.pdf')
    assert resp.json()['documents']['cover_letter']['filename'] == 'cover_letter.pdf'


def test_delete_removes_file_and_label(documents_dir):
    client = TestClient(server.app)
    _upload(client, 'Resume', 'r.pdf')
    resp = client.delete('/api/documents/resume', headers=auth_headers(1))
    assert resp.status_code == 200
    assert resp.json()['documents'] == {}
    assert not (documents_dir / '1' / 'resume').exists()
    assert json.loads((documents_dir / '1' / 'manifest.json').read_text(encoding='utf-8')) == {}


def test_delete_validates_the_slug_before_touching_disk(documents_dir):
    client = TestClient(server.app)
    # Uppercase is not a slug this store ever produces, so it is refused rather
    # than used as a path component.
    assert client.delete('/api/documents/Resume', headers=auth_headers(1)).status_code == 400
    assert client.delete('/api/documents/..%2F..%2Fetc', headers=auth_headers(1)).status_code in (400, 404)


def test_documents_are_per_user(documents_dir):
    client = TestClient(server.app)
    _upload(client, 'Resume', 'r.pdf', user_id=1)
    resp = client.get('/api/documents', headers=auth_headers(2))
    assert resp.json()['documents'] == {}


def test_legacy_two_slot_files_are_listed_and_replaced(documents_dir):
    """Files stored by the old fixed-slot store live at <user>/<slug>.<ext>."""
    legacy_dir = documents_dir / '1'
    legacy_dir.mkdir()
    (legacy_dir / 'cover_letter.pdf').write_bytes(b'%PDF-1.4 legacy')

    client = TestClient(server.app)
    resp = client.get('/api/documents', headers=auth_headers(1))
    listed = resp.json()['documents']['cover_letter']
    assert listed['label'] == 'Cover letter'
    assert listed['filename'] == 'cover_letter.pdf'
    assert listed['size'] == len(b'%PDF-1.4 legacy')

    _upload(client, 'Cover letter', 'Letter.pdf')
    assert not (legacy_dir / 'cover_letter.pdf').exists()
    assert (legacy_dir / 'cover_letter' / 'Letter.pdf').is_file()


def test_documents_for_agent_carries_label_filename_and_path(documents_dir):
    client = TestClient(server.app)
    _upload(client, 'Resume', 'Edwin_Resume.pdf')
    _upload(client, 'Cover letter', 'Letter.docx', b'PK', content_type='application/octet-stream')

    blob = server.documents_for_agent(1)

    assert set(blob) == {'resume', 'cover_letter'}
    assert blob['resume']['label'] == 'Resume'
    assert blob['resume']['filename'] == 'Edwin_Resume.pdf'
    assert blob['resume']['path'] == str(documents_dir / '1' / 'resume' / 'Edwin_Resume.pdf')
    assert server.documents_for_agent(2) == {}
