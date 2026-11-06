"""Disposable SQLite projection. session.json and .review.json remain authoritative."""
import json
import sqlite3


def _signature(directory):
    try:
        a = (directory / 'session.json').stat()
        b = (directory / '.review.json').stat()
        return f'formats-v1:{a.st_mtime_ns}:{a.st_size}:{b.st_mtime_ns}:{b.st_size}'
    except OSError:
        return None


def _project(directory, clean_title):
    try:
        review = json.loads((directory / '.review.json').read_text(encoding='utf-8'))
        meta = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
        if not isinstance(review, dict) or not isinstance(review.get('items'), list):
            return None
        if not isinstance(meta, dict) or meta.get('archived'):
            return None
        return {'id': directory.name, 'name': clean_title(meta.get('name', directory.name)),
                'duration': meta.get('duration', 0), 'outline': meta.get('outline') or [],
                'notes': meta.get('notes') or [],
                'reviewSegments': [
                    {'t': seg.get('t'), 'text': seg.get('text', ''), 'formats': seg['formats']}
                    for seg in meta.get('segments') or [] if isinstance(seg, dict)
                    and any(r.get('style', {}).get('underline') or r.get('style', {}).get('background')
                            for r in seg.get('formats') or [])],
                'review': review}
    except (OSError, ValueError, TypeError):
        return None


def read_index(root, clean_title):
    """Stat sources on each request; parse only changed pairs, never write sources.

    A new connection per request avoids sharing SQLite connections between HTTP
    threads. A failed cache transaction falls back to source files for this call.
    """
    if not root.is_dir():
        return []
    directories = sorted((d for d in root.iterdir()
                          if d.is_dir() and d.name.casefold() not in ('music', '.cache')))
    db = None
    try:
        cache = root / '.cache'
        cache.mkdir(exist_ok=True)
        db = sqlite3.connect(cache / 'review-index.sqlite3', timeout=2)
        db.execute('PRAGMA journal_mode=WAL')
        with db:
            db.execute('CREATE TABLE IF NOT EXISTS courses '
                       '(id TEXT PRIMARY KEY, signature TEXT NOT NULL, payload TEXT)')
            cached = {sid: (sig, payload) for sid, sig, payload in
                      db.execute('SELECT id, signature, payload FROM courses')}
            seen = set()
            result = []
            for directory in directories:
                signature = _signature(directory)
                if signature is None:
                    continue
                sid = directory.name
                seen.add(sid)
                previous = cached.get(sid)
                if previous is not None and previous[0] == signature:
                    payload = previous[1]
                    item = json.loads(payload) if payload is not None else None
                else:
                    item = _project(directory, clean_title)
                    payload = json.dumps(item, ensure_ascii=False) if item is not None else None
                    db.execute('INSERT OR REPLACE INTO courses VALUES (?, ?, ?)',
                               (sid, signature, payload))
                if item is not None:
                    result.append(item)
            db.executemany('DELETE FROM courses WHERE id = ?',
                           [(sid,) for sid in cached.keys() - seen])
        return result
    except (sqlite3.Error, OSError, ValueError, TypeError):
        # A locked, missing, unwritable or corrupt cache must not hide courses.
        return [item for d in directories if (item := _project(d, clean_title)) is not None]
    finally:
        if db is not None:
            db.close()


def remove_course(root, sid):
    """Best-effort physical eviction after a successful course-directory deletion."""
    path = root / '.cache' / 'review-index.sqlite3'
    db = None
    try:
        # rw mode never creates a missing cache; the next query rebuilds it.
        db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=2)
        with db:
            db.execute('DELETE FROM courses WHERE id = ?', (sid,))
    except (sqlite3.Error, OSError):
        pass
    finally:
        if db is not None:
            db.close()
